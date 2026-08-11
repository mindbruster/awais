# Turning the AI features on

Everything in this system works with no model configured. The insight reports
compute their figures in SQL and simply omit the written explanation; only
**Ask the books** needs a model, and it returns a clear 503 saying so.

So treat this as optional, and switch it on when you want the narration.

## Option A — OpenRouter (recommended, cheapest)

One key, one gateway, hundreds of models including Z.AI's GLM family. No extra
Python package is needed — the app talks to it over plain HTTP.

1. Create a key at <https://openrouter.ai/keys>.
2. Put this in `backend/.env` (or the service variables on Railway):

```bash
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
AI_MODEL=z-ai/glm-4.7-flash
```

3. Restart the API. `GET /api/v1/insights/wastage-anomalies` will start
   returning `narrative` alongside the numbers, and `/api/v1/insights/ask`
   will answer instead of 503-ing.

### About "free GLM"

**There is currently no GLM model on OpenRouter's free tier.** The `:free`
catalogue rotates and today carries Nvidia Nemotron, Google Gemma and
`openai/gpt-oss-20b`, but no Z.AI models. Verify for yourself at any time:

```bash
curl -s https://openrouter.ai/api/v1/models \
  | python3 -c "import sys,json;[print(m['id']) for m in json.load(sys.stdin)['data'] if m['id'].endswith(':free')]"
```

What GLM *is*, is extremely cheap. `z-ai/glm-4.7-flash` costs about **$0.06 per
million input tokens**. This system sends a model a few dozen rows of already
computed figures and asks for one sentence, so realistic monthly usage is
fractions of a cent. That is the sensible default and what `AI_MODEL` is set to
above.

If you want a hard zero, use a genuinely free model instead — same key, same
setup, just a different `AI_MODEL`:

```bash
AI_MODEL=openai/gpt-oss-20b:free      # or google/gemma-4-31b-it:free
```

Free models are rate-limited and can be withdrawn without notice. Since nothing
here is load-bearing, the worst case is that the prose stops appearing and the
numbers carry on — but be aware of the trade.

### Which GLM to pick

| Model | Input $/M | Notes |
|---|---|---|
| `z-ai/glm-4.7-flash` | 0.06 | Default. Ample for narration. |
| `z-ai/glm-4.6` | 0.55 | Better at Urdu/Roman-Urdu SQL questions. |
| `z-ai/glm-5.2` | 0.76 | 1M context; only worth it for very large results. |

If **Ask the books** starts producing SQL that gets rejected by the guard, move
up to `glm-4.6` — writing correct SQL from a schema description is the hardest
thing asked of the model here.

## Option B — Claude directly

```bash
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
AI_MODEL=claude-opus-5
pip install anthropic     # this route needs the SDK
```

Better quality, materially more expensive. Worth it if the Ask feature becomes
something the owner uses daily.

## Optional attribution

Only affects how usage appears in OpenRouter's dashboard:

```bash
AI_APP_URL=https://app.your-domain.com
AI_APP_NAME=Jewelry ERP
```

## What each feature does without a model

| Endpoint | No model configured |
|---|---|
| `/insights/wastage-anomalies` | Full figures and flags; `narrative` omitted |
| `/insights/margin-watch` | Full figures and flags; `narrative` omitted |
| `/insights/ask` | 503 with these setup instructions |

The Insights screen shows a calm "not configured" panel naming the variables
rather than an error.

## Safety notes worth knowing

- **Ask the books runs read-only.** The generated SQL executes in a read-only
  transaction with a statement timeout and a row cap, and before it runs,
  Postgres itself is asked (via `EXPLAIN`) which tables it would touch. Anything
  outside the curated allowlist is refused without executing — this is what
  stops a cleverly-worded question from reaching the `users` table.
- **The model never invents a number.** Every figure in a narrated report is
  computed in SQL and passed to the model, which is asked only to explain it.
- **The generated SQL is returned with the answer** so it can be checked.
- Ask is gated on the money permission, so counter staff cannot reach it.
