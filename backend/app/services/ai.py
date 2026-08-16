"""
The model layer. Provider-agnostic, flag-gated, and never load-bearing.

Mirrors `app.services.whatsapp`: a setting picks the provider, and an
unconfigured provider produces a 503 carrying setup instructions rather than an
obscure failure deeper in.

The split of responsibility is the important part and it is deliberate:

* The **statistics find the outlier.** Every figure the insights endpoints
  return is computed in SQL from the books. The model is handed those figures
  and asked only to write the sentence that explains them and to name the jobs
  involved. It is never asked to compute, compare or rank, because a model that
  is allowed to produce a number will eventually produce a wrong one and the
  shop has no way to tell.
* `narrate` **cannot raise.** A missing key, an expired card, a timeout or a
  provider outage returns `None` and the endpoint ships its numbers with the
  prose omitted. A shop running this during a power cut is worse off with an
  ERP that stops than with one that never had narration.

`/ask` is the one place a model is on the critical path, because the request
*is* "have the model write a query". That endpoint 503s when unconfigured, and
everything the model produces there is validated before it reaches Postgres and
returned alongside the answer so it can be checked.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_config import OPENROUTER_BASE_URL, AISettings, get_ai_settings

log = logging.getLogger(__name__)

# A generated query is a report, not a job. These bound how much damage a
# runaway one can do to a shop that is also trying to bill a customer.
QUERY_TIMEOUT_MS = 5_000
MAX_ROWS = 200

_NARRATION_TIMEOUT_S = 30.0
# How many result rows the narrator is shown. Kept well under the row cap so a
# large result doesn't blow the prompt; the model is told when it is seeing a
# slice so it can say so rather than summarising what it wasn't given.
_NARRATION_ROWS = 50
_SQL_TIMEOUT_S = 60.0


# --------------------------------------------------------------------------
# Provider plumbing
# --------------------------------------------------------------------------
def ai_settings() -> AISettings:
    return get_ai_settings()


def ai_available() -> bool:
    return ai_settings().configured


def require_provider() -> AISettings:
    """503 with instructions, in the shape whatsapp.send_text uses."""
    cfg = ai_settings()
    if not cfg.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=cfg.unconfigured_reason,
        )
    return cfg


@dataclass
class _Block:
    type: str
    text: str


@dataclass
class _Message:
    """
    The shape the call sites already expect, whoever produced it.

    `model` is part of that shape: `generate_sql` returns it so the owner can
    see which model wrote a query. Omitting it here meant every OpenRouter call
    that reached that line died with an AttributeError — invisible until a real
    key existed, because without one the request 503s long before it.
    """

    content: list[_Block]
    stop_reason: str | None = None
    # What actually served the request, which is not always what was asked for:
    # OpenRouter falls back to another provider for a model under load, and the
    # response says so.
    model: str = ""


class _OpenRouterMessages:
    """
    OpenRouter behind the Anthropic SDK's `messages.create` signature.

    An adapter rather than a second code path on purpose: the three places that
    call a model are about wastage, margins and answering questions, and none of
    them should know or care which vendor is switched on. Anything that leaks
    the provider into those call sites becomes a place where switching provider
    silently changes behaviour.
    """

    def __init__(self, cfg: AISettings, timeout: float) -> None:
        self._cfg = cfg
        self._timeout = timeout

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
        output_config: dict[str, Any] | None = None,
    ) -> _Message:
        import httpx

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *messages],
        }

        # Structured output where the model supports it. Not every model on the
        # gateway honours json_schema, so the prompts also state the shape in
        # words and the parse below tolerates a fenced block — belt and braces
        # beats a 500 on a report that is meant to degrade gracefully.
        fmt = (output_config or {}).get("format")
        if isinstance(fmt, dict) and fmt.get("type") == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": fmt["schema"]},
            }

        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
            "X-Title": self._cfg.app_name,
        }
        if self._cfg.app_url:
            headers["HTTP-Referer"] = self._cfg.app_url

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            resp = await http.post(
                f"{OPENROUTER_BASE_URL}/chat/completions", json=body, headers=headers
            )
        if resp.status_code >= 400:
            # The key must never reach a log or a response; only the status and
            # the provider's own message do.
            raise RuntimeError(f"OpenRouter returned {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        finish = choice.get("finish_reason")
        return _Message(
            content=[_Block(type="text", text=text)],
            stop_reason="refusal" if finish == "content_filter" else finish,
            model=data.get("model") or model,
        )


class _OpenRouterClient:
    def __init__(self, cfg: AISettings, timeout: float) -> None:
        self.messages = _OpenRouterMessages(cfg, timeout)


def _client(cfg: AISettings, timeout: float):
    """
    Built per call, and the SDK is imported here rather than at module scope.

    The dependency is optional: with AI_PROVIDER unset the app must import and
    serve every deterministic endpoint on a machine that has never seen either
    client library.
    """
    if cfg.provider == "openrouter":
        return _OpenRouterClient(cfg, timeout)

    if cfg.provider != "anthropic":  # pragma: no cover - guarded by require_provider
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unknown AI_PROVIDER '{cfg.provider}'",
        )

    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:  # pragma: no cover - depends on the deployment
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AI_PROVIDER is set to 'anthropic' but the SDK is not installed. "
                "Run `pip install anthropic` in the backend virtualenv, or switch to "
                "AI_PROVIDER=openrouter, which needs no extra package."
            ),
        ) from exc

    return AsyncAnthropic(api_key=cfg.anthropic_api_key).with_options(timeout=timeout)


def _text_of(message) -> str:
    """
    The text of a reply, with any markdown fence stripped.

    Frontier models asked for JSON return JSON. Cheaper gateway models often
    wrap it in ```json anyway, and a report that degrades gracefully must not
    fall over because of a code fence.
    """
    text = "".join(b.text for b in message.content if b.type == "text").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


# --------------------------------------------------------------------------
# Narration — decoration, never a dependency
# --------------------------------------------------------------------------
NARRATION_RULES = (
    "You explain figures that have already been computed from a jewellery "
    "workshop's books. Absolute rules:\n"
    "- Never state a number that is not in the data you were given. Do not "
    "add, average, project or estimate. If a figure is not there, describe it "
    "in words instead.\n"
    "- One sentence per subject, at most about 30 words. Plain shop English.\n"
    "- Say what the figures show and cite the identifiers given (job/leg "
    "numbers, invoice numbers). Do not recommend disciplinary action or "
    "accuse anyone of theft; a shortfall has many innocent causes.\n"
)


async def narrate_map(
    *,
    task: str,
    payload: dict[str, Any],
    keys: list[str],
) -> dict[str, str]:
    """
    One sentence per key, or `{}` if anything at all goes wrong.

    Batched into a single request: the flagged rows on a report are explained
    together, so a shop with eight flagged workers pays for one call rather
    than eight.
    """
    if not keys:
        return {}
    cfg = ai_settings()
    if not cfg.configured:
        return {}

    schema = {
        "type": "object",
        "properties": {
            "narratives": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "enum": keys},
                        "sentence": {"type": "string"},
                    },
                    "required": ["key", "sentence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["narratives"],
        "additionalProperties": False,
    }

    try:
        client = _client(cfg, _NARRATION_TIMEOUT_S)
        message = await client.messages.create(
            model=cfg.model,
            max_tokens=4000,
            system=NARRATION_RULES + "\n" + task,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Write one sentence for each of these keys: "
                        f"{json.dumps(keys)}\n\nComputed figures:\n"
                        f"{json.dumps(payload, default=str, indent=1)}"
                    ),
                }
            ],
        )
        if message.stop_reason == "refusal":
            log.warning("ai.narrate refused by the model; shipping figures only")
            return {}
        data = json.loads(_text_of(message))
        return {
            str(row["key"]): str(row["sentence"]).strip()
            for row in data.get("narratives", [])
            if row.get("key") in keys and row.get("sentence")
        }
    except Exception as exc:  # narration is decoration — never fail the report
        log.warning("ai.narrate unavailable (%s: %s)", type(exc).__name__, exc)
        return {}


# --------------------------------------------------------------------------
# Natural language over the books
# --------------------------------------------------------------------------
# A curated, read-only view of the schema. Handing over the real DDL would give
# the model users.hashed_password and every audit row; this is the subset a
# question about the business can legitimately need, and the guard below
# enforces that the query stays inside it.
ALLOWED_TABLES = {
    "designs",
    "job_legs",
    "leg_stones",
    "departments",
    "items",
    "vendors",
    "customers",
    "products",
    "invoices",
    "invoice_items",
    "journal_entries",
    "journal_lines",
    "accounts",
    "stones",
}

SCHEMA_DESCRIPTION = """\
Postgres. Money is numeric in PKR unless a currency column says otherwise;
weights are grams, stone weights are carats. Only these tables and columns
exist for you:

designs(id, design_no, tag_no, item_id, customer_id, current_department_id,
  status['in_production','stocked','sold','cancelled'], product_id, notes,
  created_at, updated_at)
  -- one physical piece, identified from the moment work starts on it.

job_legs(id, design_id, sequence, department_id, worker_id,
  status['issued','received','cancelled'], issued_at, received_at,
  gold_issued_g, gold_issued_purity, gold_received_g, piece_count,
  stones_issued_ct, stones_used_ct, stones_returned_ct,
  wastage_basis['percent_of_issued','per_100_pieces'], wastage_allowed_pct,
  wastage_per_100_pcs_g, wastage_allowed_g, wastage_actual_g,
  wastage_excess_g, labour_basis['per_gram','per_piece','flat'], labour_rate,
  labour_amount, created_at)
  -- one visit to one department. wastage_actual_g = issued - received and is
  -- SIGNED (negative means the piece came back heavier, which is normal).
  -- wastage_excess_g is only the part beyond what the worker was allowed.
  -- A leg is finished when status = 'received'.

leg_stones(id, leg_id, stone_id, quantity_issued, weight_issued_ct,
  quantity_returned, weight_returned_ct, rate_per_ct)
stones(id, name, shape, quality, colour, size, rate_per_ct)
departments(id, name, code, sequence, consumes_stones, default_wastage_pct,
  default_rate_per_piece)
items(id, name, abbreviation)
vendors(id, name, phone, type, default_wastage_pct, is_active)
  -- workers/karigars as well as suppliers.
customers(id, name, phone, city_id, opening_balance, is_active)

products(id, sku, name, item_id, gross_weight_g, net_weight_g, purity,
  material_cost, total_cost, selling_price)
  -- total_cost is making (labour) cost, material_cost is capitalised gold and
  -- stones. COGS for a sold line = (total_cost + material_cost) * quantity.

invoices(id, invoice_no, customer_id, currency, sale_type['normal',
  'on_approval'], status['draft','issued','paid','returned','void'],
  gold_rate_per_g, subtotal, discount_amount, discount_weight_g, tax_amount,
  total, issued_at, paid_at, created_at)
  -- only 'issued' and 'paid' are real sales.
invoice_items(id, invoice_id, product_id, description, quantity,
  gold_weight_g, gold_purity, gold_rate_per_g, gold_amount, stone_weight_ct,
  stone_rate_per_ct, stone_amount, labor_amount, line_discount,
  discount_ratti, ratti_base, line_total)
  -- discount_ratti is a discount quoted in ratti against ratti_base (usually
  -- 96): the customer is billed for gold_weight_g/base*(base-ratti).

journal_entries(id, entry_no, entry_date, memo, source_type, source_id,
  reverses_entry_id, posted_at)
journal_lines(id, entry_id, account_id, commodity['PKR','USD','GOLD'],
  quantity, rate, value_pkr, native_weight_g, native_purity,
  party_type['customer','worker','supplier'], party_id, memo)
  -- double entry: quantity is signed, positive = debit. GOLD lines carry FINE
  -- grams in quantity; native_weight_g is as weighed.
accounts(id, code, name, type['asset','liability','equity','income',
  'expense'], parent_id, is_active)
"""

SQL_RULES = f"""\
You turn a jewellery shop owner's question into exactly ONE read-only Postgres
SELECT statement over the schema below.

Hard requirements:
- Output a single SELECT (a leading read-only WITH is allowed). No semicolons,
  no comments, no second statement.
- Never write: INSERT, UPDATE, DELETE, MERGE, DROP, ALTER, CREATE, TRUNCATE,
  GRANT, COPY, SET, or a writing CTE.
- Only the tables listed below exist. Do not reference any other table.
- Always alias computed columns with a readable name.
- Add an ORDER BY when "top", "worst", "most" or "least" is implied, and a
  LIMIT when the question implies a handful of rows.
- Only count invoices with status IN ('issued','paid') as sales, and only
  job_legs with status = 'received' as finished work, unless asked otherwise.
- Cast money and weights so they read cleanly; round to 2 decimals for money
  and 4 for grams.

The question may be in English, Urdu (اردو) or Roman-Urdu — shop staff type
all three, often mixed. "Karigar" is a worker, "sona"/"gold" is gold,
"kitna"/"kitni" is how much, "nuqsan"/"zaya"/"waste" is wastage, "munafa" is
profit, "bikri" is sales, "udhaar" is amount owed. Read the question in
whichever language it is written and produce SQL for it.

Schema:
{SCHEMA_DESCRIPTION}"""

_FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
    r"copy|vacuum|reindex|refresh|cluster|comment|call|do|execute|prepare|"
    r"deallocate|set|reset|listen|notify|lock|begin|commit|rollback|savepoint|"
    r"into|returning|pg_sleep|pg_read_file|pg_read_binary_file|pg_ls_dir|"
    r"lo_import|lo_export|dblink"
    r")\b",
    re.IGNORECASE,
)
# The table name after FROM/JOIN. Subqueries open with '(' and are skipped —
# their own FROM clauses get matched on the next pass of the same regex.
_SOURCES = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_.\"]*)", re.IGNORECASE)
# Names introduced by a WITH clause. They are selected from like tables, so
# without this a perfectly legal read-only CTE reads as an unknown table.
_CTE_NAMES = re.compile(
    r"(?:\bwith\b(?:\s+recursive\b)?|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\([^)]*\))?\s+as\s*\(",
    re.IGNORECASE,
)


@dataclass
class GeneratedQuery:
    sql: str
    model: str
    notes: str | None


def validate_select(sql: str) -> str:
    """
    Reject anything that is not one bare SELECT over the curated tables.

    This is the security boundary, not the prompt. The prompt is a request; a
    model that ignores it, or a question crafted to make it ignore it, has to
    fail here. Everything is a rejection rather than a repair — silently
    rewriting a query the owner is about to read would defeat the point of
    showing them the SQL.
    """
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The model returned no SQL.")

    if ";" in cleaned:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Refusing to run more than one statement.",
        )
    # Comments can hide a second statement from a human reading the result,
    # which is the one thing this endpoint promises not to do.
    if "--" in cleaned or "/*" in cleaned:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Refusing to run SQL containing comments."
        )
    if not re.match(r"^(select|with)\b", cleaned, re.IGNORECASE):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only a single SELECT can be run here."
        )
    forbidden = _FORBIDDEN.search(cleaned)
    if forbidden:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Refusing to run SQL containing '{forbidden.group(1).upper()}'.",
        )

    readable = ALLOWED_TABLES | {n.lower() for n in _CTE_NAMES.findall(cleaned)}
    for raw_name in _SOURCES.findall(cleaned):
        name = raw_name.strip('"').lower()
        # Schema-qualified names are rejected outright rather than unwrapped:
        # pg_catalog.pg_authid is a table too.
        if "." in name or name not in readable:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"'{raw_name}' is not one of the tables this report may read.",
            )
    return cleaned


async def generate_sql(question: str) -> GeneratedQuery:
    """Ask the model for one SELECT. Raises 503 when no provider is configured."""
    cfg = require_provider()
    schema = {
        "type": "object",
        "properties": {
            "sql": {"type": "string"},
            "notes": {
                "type": "string",
                "description": "One short line on what the query counts, in the question's language.",
            },
        },
        "required": ["sql", "notes"],
        "additionalProperties": False,
    }
    client = _client(cfg, _SQL_TIMEOUT_S)
    try:
        message = await client.messages.create(
            model=cfg.model,
            max_tokens=8000,
            system=SQL_RULES,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": question}],
        )
    except Exception as exc:
        log.warning("ai.generate_sql failed (%s: %s)", type(exc).__name__, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"The model could not be reached: {type(exc).__name__}.",
        ) from exc

    if message.stop_reason == "refusal":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The model declined to answer that question.",
        )
    raw = _text_of(message)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # The model answered in prose rather than the schema. In practice this
        # is how a small model declines — asked for the users table and its
        # password hashes, it explains why it won't instead of emitting the
        # refusal token. That is a 400 with the model's own words, not a 500:
        # nothing was run, and the person asking should see the reason.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"The model did not return a query for that question. It said: {raw[:300]}"
            if raw
            else "The model returned nothing for that question.",
        ) from None
    return GeneratedQuery(
        sql=validate_select(data.get("sql", "")),
        model=message.model,
        notes=(data.get("notes") or "").strip() or None,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        # Decimal all the way to the wire; TS parses the string.
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _plan_relations(node: Any, found: set[str]) -> None:
    """Walk an EXPLAIN plan collecting every relation the planner will touch."""
    if isinstance(node, dict):
        name = node.get("Relation Name")
        if isinstance(name, str):
            found.add(name.lower())
        for value in node.values():
            _plan_relations(value, found)
    elif isinstance(node, list):
        for value in node:
            _plan_relations(value, found)


async def _assert_planner_only_reads_allowed_tables(db: AsyncSession, sql: str) -> None:
    """
    Ask Postgres which tables the query actually reads, and refuse anything
    outside the allowlist.

    The text checks upstream are a cheap first pass, but pattern-matching SQL is
    not something a regex can do correctly — a comma-separated FROM list, an
    unusually quoted identifier or a relation reached through a sublink all slip
    past one. The planner has already resolved the query properly, so asking it
    is the difference between a guard that looks right and one that is. This runs
    inside the same read-only transaction, and EXPLAIN without ANALYZE plans
    without executing, so a rejected query never touches a row.
    """
    try:
        plan_rows = (await db.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"))).scalar_one()
    except Exception as exc:
        log.warning("ai.explain_failed", extra={"error": str(exc).splitlines()[0][:300]})
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The generated query could not be planned. Try rephrasing the question.",
        ) from exc

    if isinstance(plan_rows, str):
        plan_rows = json.loads(plan_rows)
    relations: set[str] = set()
    _plan_relations(plan_rows, relations)

    disallowed = sorted(r for r in relations if r not in ALLOWED_TABLES)
    if disallowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"That question would read {', '.join(disallowed)}, which this report may not access.",
        )


async def run_select(db: AsyncSession, sql: str) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Run a validated SELECT in a read-only transaction with a statement timeout.

    The guard above is a text check and text checks are never complete, so the
    database is told the same thing in a way it will enforce: this transaction
    may not write, and it may not run for longer than a report should. The row
    cap is applied by wrapping the query rather than by trusting a LIMIT the
    model may or may not have written.
    """
    capped = f"SELECT * FROM (\n{sql}\n) AS ai_query LIMIT {MAX_ROWS}"
    try:
        await db.execute(text(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT_MS}"))
        await db.execute(text("SET LOCAL transaction_read_only = on"))
        await _assert_planner_only_reads_allowed_tables(db, capped)
        result = await db.execute(text(capped))
        columns = list(result.keys())
        rows = [
            {k: _jsonable(v) for k, v in row.items()} for row in result.mappings().all()
        ]
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        # Deliberately opaque. Echoing the database's error turns a failed
        # generated query into a schema-probing oracle: an attacker steering the
        # question can read column and table names straight out of the error
        # text, which is precisely what the allowlist above exists to prevent.
        log.warning("ai.query_failed", extra={"error": str(exc).splitlines()[0][:300]})
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The generated query could not be run. Try rephrasing the question.",
        ) from exc
    finally:
        # Nothing was written, and rolling back is what drops the SET LOCALs so
        # the next request on this session is not silently read-only.
        await db.rollback()
    return columns, rows


async def answer_from_rows(
    *, question: str, sql: str, columns: list[str], rows: list[dict[str, Any]]
) -> str | None:
    """
    Turn the rows into a sentence. `None` if the model is unreachable — the
    rows and the SQL are the answer; this is the reading of them.
    """
    cfg = ai_settings()
    if not cfg.configured:
        return None
    try:
        client = _client(cfg, _NARRATION_TIMEOUT_S)
        message = await client.messages.create(
            model=cfg.model,
            max_tokens=4000,
            system=(
                "You read the result of a database query back to a jewellery "
                "shop owner. Answer in one or two sentences, in the same "
                "language the question was asked in (English, Urdu or "
                "Roman-Urdu). Use ONLY numbers that appear in the rows — never "
                "compute, total or estimate anything yourself. If the rows are "
                "empty, say plainly that nothing matched. If they were capped "
                f"at {MAX_ROWS} rows, say so."
            ),
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    # Tell the model exactly how much of the result it can see.
                    # Labelling the prompt with the full count while showing a
                    # slice invites a confident summary of data it never
                    # received — "the highest is X" when the real highest sat in
                    # the rows that were cut.
                    "content": (
                        f"Question: {question}\n\nSQL run:\n{sql}\n\n"
                        f"Columns: {json.dumps(columns)}\n"
                        + (
                            f"Rows: showing the first {_NARRATION_ROWS} of {len(rows)}. "
                            "Say so if the answer depends on rows you cannot see.\n"
                            if len(rows) > _NARRATION_ROWS
                            else f"Rows ({len(rows)}):\n"
                        )
                        + json.dumps(rows[:_NARRATION_ROWS], default=str)
                    ),
                }
            ],
        )
        if message.stop_reason == "refusal":
            return None
        return _text_of(message) or None
    except Exception as exc:
        log.warning("ai.answer_from_rows unavailable (%s: %s)", type(exc).__name__, exc)
        return None


# --------------------------------------------------------------------------
# Conversation
# --------------------------------------------------------------------------
# What the shop's own screens do, in the words the counter uses. The model is
# given this so that "how do I give gold to Zahid" is answered with this app's
# actual workflow instead of a plausible-sounding invention, which is the
# failure mode that matters: a confident wrong instruction sends somebody
# looking for a button that does not exist, or worse, into the wrong one.
#
# Kept as prose rather than pulled from the routes, deliberately. A route list
# describes the API; a shop assistant has to describe the work.
WORKFLOW_GUIDE = """\
How this system is used, screen by screen:

MAKING A PIECE (Designs)
- Every piece is a Design, created on the Designs screen. It gets a number
  (TK-00001) the moment work starts, before anything is finished.
- Work is recorded as legs: one visit to one department. Open the design and
  use "Issue to department" — pick the department, the worker, the gold source
  and the weight. That is what takes metal out of the safe.
- Leave the worker as "In-house" for stages the shop does itself (cleaning,
  burning, rhodium, finish). Then nobody is holding the metal and no shortfall
  is charged to anyone.
- When the work comes back, press Receive on that leg and enter the weight
  returned. The system works out the wastage: what was allowed, what actually
  went, and what ran past the allowance. Only the excess is charged back.
- A piece may come back heavier than it went out. That is normal — solder and
  findings add weight — and it is recorded as a gain, not a shortfall.
- Cancelling a leg needs a password and asks how much metal was recovered.
  Whatever was not recovered stays owed by that worker.
- When the piece is finished, use the stock form to turn the design into a
  Product. That rolls up every leg's labour into the piece's making cost.

WORKERS
- Workers live under Workers. Each belongs to a department, and that is what
  decides where they can be given work — a worker with no department cannot be
  picked on a design at all.
- Each worker carries the wastage percentage agreed with him. If he has none,
  the department's default applies.

BUYING
- Old gold: metal bought back over the counter, at a rate below the day's rate.
- Stone purchases: supplier bills, entered by graded lot (quality, cut, colour,
  clarity), so stone stock can be counted by grade rather than in total.

SELLING (Invoices)
- An invoice starts as a draft, is Issued (which is when stock moves and the
  books are posted), and is then paid. On-approval sales do not deduct stock.
- Each line can carry: wastage charged to the customer (a percentage or flat
  grams), a ratti discount, and a line discount.
- The ratti discount is quoted against a base of 96: six ratti bills 90/96 of
  the gold weight. It reduces the metal billed, not the money.
- Payments are taken against the invoice. Cash, bank, gold exchange or advance.
  A payment can be reversed; it is never deleted.

THE BOOKS
- Position: cash, metal, and who owes whom, as of this morning.
- Journal: every balanced entry, newest first. Nothing is ever edited — a
  mistake is corrected by posting its reversal.
- Statements: a running account for one head, optionally for one party.

REPORTS
- Overview: stock, what was billed, what the bench lost.
- Margin: the profit split by which lever produced it — rate spread, wastage
  charged, making charges, stone margin — less what was given away.
- Workers: what each worker was allowed, what he actually lost, and what he is
  holding right now.
- Operations: department throughput and item performance.
"""

_CHAT_ROUTER_RULES = """\
You are the assistant inside a jewellery shop's ERP. Decide what the latest
message needs, and rewrite it as one standalone question.

kind:
- "data"   the answer is in the shop's records — figures, balances, who owes
           what, which worker lost most, how many of something there are.
- "howto"  the person is asking how to use the system, or what something in it
           means.
- "chat"   greetings, thanks, or anything neither of the above.

question: the latest message rewritten so it stands alone, with any pronoun or
ellipsis resolved from the conversation. "And last month?" after a question
about wastage becomes "What was the wastage last month?". Keep the language the
person used (English, Urdu or Roman-Urdu).
"""


@dataclass
class ChatTurn:
    reply: str
    kind: str
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[dict[str, Any]] | None = None
    notes: str | None = None
    model: str | None = None


def _history_text(messages: list[dict[str, str]]) -> str:
    """The conversation as plain text for the router. Trimmed to the recent
    turns: resolving a pronoun needs the last few exchanges, not the hour."""
    recent = messages[-12:]
    return "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in recent)


def _provider_failure(exc: Exception, what: str) -> HTTPException:
    """
    Turn a provider fault into something the operator can act on.

    `generate_sql` already does this and the conversation paths did not, so an
    out-of-credit account — which is the ordinary first-run state of a new
    OpenRouter key — surfaced as a 500 and a traceback instead of the one
    sentence that tells you to top up. The provider's own message is passed
    through: "insufficient credits", "no such model" and "rate limited" need
    three different actions, and collapsing them strands you.
    """
    log.warning("ai.%s failed (%s)", what, type(exc).__name__)
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        f"The model could not be reached: {exc}"[:500],
    )


async def _route(messages: list[dict[str, str]]) -> tuple[str, str]:
    cfg = require_provider()
    schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["data", "howto", "chat"]},
            "question": {"type": "string"},
        },
        "required": ["kind", "question"],
        "additionalProperties": False,
    }
    client = _client(cfg, _NARRATION_TIMEOUT_S)
    latest = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
    )
    try:
        message = await client.messages.create(
            model=cfg.model,
            max_tokens=2000,
            system=_CHAT_ROUTER_RULES,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": _history_text(messages)}],
        )
    except Exception as exc:
        raise _provider_failure(exc, "chat routing") from None
    try:
        data = json.loads(_text_of(message))
    except json.JSONDecodeError:
        # A model that ignored the schema should not sink the turn. Treating it
        # as a data question is the useful default: that path validates
        # everything it produces anyway, so a wrong guess is refused, not run.
        return "data", latest
    return data.get("kind", "chat"), (data.get("question") or latest).strip()


async def _answer_howto(question: str, messages: list[dict[str, str]]) -> str:
    cfg = require_provider()
    client = _client(cfg, _NARRATION_TIMEOUT_S)
    try:
        message = await client.messages.create(
            model=cfg.model,
            max_tokens=4000,
            system=(
                "You are the assistant inside a jewellery shop's ERP. Explain how to "
            "do things using ONLY the guide below — it describes this system, and "
            "screens or buttons outside it do not exist. If the guide does not "
            "cover something, say so plainly rather than guessing. Answer in the "
            "language the person used (English, Urdu or Roman-Urdu), in a few "
                "short sentences or steps.\n\n" + WORKFLOW_GUIDE
            ),
            output_config={"effort": "low"},
            messages=[
                {"role": "user", "content": f"{_history_text(messages)}\n\nAnswer: {question}"}
            ],
        )
    except Exception as exc:
        raise _provider_failure(exc, "chat how-to") from None
    return _text_of(message) or "I could not answer that."


async def chat(db: AsyncSession, messages: list[dict[str, str]]) -> ChatTurn:
    """
    One conversational turn. Read-only by construction.

    A data question goes through exactly the same path as `/ask` — generated
    SELECT, validated, planner-checked against the table allowlist, run in a
    read-only transaction — so the conversation cannot reach anything the
    single-shot endpoint could not, and cannot write at all. The SQL comes back
    with the answer for the same reason it does there: it is the only way the
    owner can tell a right answer from a confidently wrong one.
    """
    kind, question = await _route(messages)

    if kind == "data":
        generated = await generate_sql(question)
        columns, rows = await run_select(db, generated.sql)
        answer = await answer_from_rows(
            question=question, sql=generated.sql, columns=columns, rows=rows
        )
        return ChatTurn(
            reply=answer or "The query ran; the rows are below.",
            kind=kind,
            sql=generated.sql,
            columns=columns,
            rows=rows,
            notes=generated.notes,
            model=generated.model,
        )

    if kind == "howto":
        return ChatTurn(reply=await _answer_howto(question, messages), kind=kind)

    cfg = require_provider()
    client = _client(cfg, _NARRATION_TIMEOUT_S)
    try:
        message = await client.messages.create(
            model=cfg.model,
            max_tokens=1000,
            system=(
                "You are the assistant inside a jewellery shop's ERP. Be brief and "
                "practical. You can answer questions about the shop's own records "
                "and explain how to use the system — say so if it helps. Reply in "
                "the language the person used."
            ),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": _history_text(messages)}],
        )
    except Exception as exc:
        raise _provider_failure(exc, "chat") from None
    return ChatTurn(reply=_text_of(message) or "…", kind=kind)
