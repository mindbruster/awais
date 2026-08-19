import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { TextField } from "@/components/Field";
import { toast } from "@/components/Toast";
import { fmtMoney } from "@/lib/money";
import { wt } from "@/pages/designs/parts";

/**
 * The shop's position on the day it starts using this system.
 *
 * Until this screen existed the only way in was an API call with a token, so a
 * shop went live either with an empty safe or with someone reading curl output
 * over the phone. Both of those produce the same thing: a set of books whose
 * every later figure is measured from a starting point nobody wrote down.
 *
 * It is laid out as a checklist rather than a form because that is what the
 * work is — somebody walks the safe with a scale, pot by pot, and needs to see
 * at a glance which trays are done. The order of the sections is the order the
 * server enforces: a rate, then the pots, then the money owed either way.
 */

type PotStatus = {
  id: number;
  label: string;
  type: string;
  location: string | null;
  purity: number | null;
  tunch_pct: string | null;
  weighs_metal: boolean;
  has_opening: boolean;
};

type Status = {
  pots: PotStatus[];
  done: number;
  pending: number;
  gold_rate_set: boolean;
};

type Posted = { party_type: string; party_name: string; entry_no: string };
type Skipped = { party_type: string; party_name: string; reason: string };
type BalanceResult = {
  gold_rate_per_g: string;
  posted: Posted[];
  skipped: Skipped[];
};

const TYPE_LABEL: Record<string, string> = {
  raw_gold: "Gold",
  raw_silver: "Silver",
  raw_stone: "Stones",
  broken_stone: "Broken stones",
  finished_product: "Finished pieces",
};

// The order somebody actually walks the safe in: metal first, because it is
// the bulk of the value and the part a scale settles, then the parcels, then
// the shelf.
const TYPE_ORDER = ["raw_gold", "raw_silver", "raw_stone", "broken_stone", "finished_product"];

export function OpeningPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pot, setPot] = useState<PotStatus | null>(null);
  const [result, setResult] = useState<BalanceResult | null>(null);
  const [postingBalances, setPostingBalances] = useState(false);

  // The declaration being made about the pot in `pot`. Held here rather than
  // in the dialog because `PasswordConfirm` owns only the password — the
  // caller owns its own fields and reads them when the password comes back.
  const [weight, setWeight] = useState("");
  const [carats, setCarats] = useState("");
  const [quantity, setQuantity] = useState("");
  const [rate, setRate] = useState("");
  const [value, setValue] = useState("");
  const [asOf, setAsOf] = useState("");
  const [notes, setNotes] = useState("");

  const load = useCallback(() => {
    api
      .get<Status>("/inventory/opening-status")
      .then((r) => setStatus(r.data))
      .catch((e) => setError(apiError(e, "Could not load the opening position")));
  }, []);

  useEffect(load, [load]);

  const openFor = (p: PotStatus) => {
    setWeight("");
    setCarats("");
    setQuantity("");
    setRate("");
    setValue("");
    setAsOf("");
    setNotes("");
    setPot(p);
  };

  const record = async (password: string) => {
    if (!pot) return;
    try {
      await api.post(
        `/inventory/${pot.id}/opening`,
        {
          weight_g: weight || "0",
          weight_ct: carats || "0",
          quantity: quantity ? Number(quantity) : 0,
          rate_per_g: rate || null,
          value: value || null,
          as_of: asOf || null,
          notes: notes || null,
        },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${pot.label} recorded`);
      setPot(null);
      load();
    } catch (e) {
      // Rethrown so the dialog stays open with what was typed still in it — a
      // refusal here is usually a missing value or a purity that needs setting,
      // and closing the form would make the person type it all again.
      toast("error", apiError(e, "Could not record this pot"));
      throw e;
    }
  };

  const postBalances = async (password: string) => {
    try {
      const r = await api.post<BalanceResult>(
        "/ledger/opening-balances",
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      setResult(r.data);
      setPostingBalances(false);
      toast(
        "success",
        r.data.posted.length
          ? `Posted ${r.data.posted.length} opening balance${r.data.posted.length === 1 ? "" : "s"}`
          : "Nothing left to post",
      );
    } catch (e) {
      toast("error", apiError(e, "Could not post opening balances"));
      throw e;
    }
  };

  if (error) return <div className="card text-sm text-red-600">{error}</div>;
  if (!status) return <div className="card text-sm text-slate-500">Loading…</div>;

  const groups = TYPE_ORDER.map((t) => ({
    type: t,
    pots: status.pots.filter((p) => p.type === t),
  })).filter((g) => g.pots.length > 0);

  const metalPot = pot?.weighs_metal ?? false;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Opening position</h1>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-500">
          What the shop already had on the day it started using this system. Every
          later figure is measured from here, so it is worth an afternoon with a
          scale — an old system's stock figure is a claim, and weighing is what
          makes it a fact.
        </p>
      </div>

      {/* Step 1 — the rate everything else needs. */}
      {!status.gold_rate_set && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <h2 className="text-sm font-semibold text-amber-900">
            Set today's gold rate first
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-amber-800">
            Metal has to be valued for these entries to balance, and posting
            opening balances is refused outright without a 24k PKR rate on record.
          </p>
          <Link
            to="/gold-rates"
            className="mt-2 inline-flex text-sm font-medium text-amber-900 underline"
          >
            Go to gold rates
          </Link>
        </div>
      )}

      {/* Step 2 — the pots, which is the bulk of the work. */}
      <section className="card">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold text-slate-900">Stock on hand</h2>
          <p className="num text-sm text-slate-500">
            {status.done} of {status.done + status.pending} pots recorded
          </p>
        </div>
        <p className="mt-1 text-sm leading-relaxed text-slate-500">
          Once per pot. A second declaration would double the shop's capital, so
          the server refuses it — to correct a pot after this, count it under{" "}
          <Link to="/reconciliation" className="underline">
            Reconciliation
          </Link>
          .
        </p>

        {groups.length === 0 && (
          <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
            No pots exist yet. Create the trays, safes and parcels the shop keeps
            material in first — at the purity each one actually holds — under{" "}
            <Link to="/inventory" className="underline">
              Inventory
            </Link>
            .
          </p>
        )}

        <div className="mt-4 space-y-5">
          {groups.map((g) => (
            <div key={g.type}>
              <p className="eyebrow">{TYPE_LABEL[g.type] ?? g.type}</p>
              <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
                {g.pots.map((p) => (
                  <li
                    key={p.id}
                    className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-900">
                        {p.label}
                      </p>
                      <p className="text-xs text-slate-500">
                        {[
                          p.purity ? `${p.purity}k` : null,
                          p.tunch_pct ? `${Number(p.tunch_pct)}% tunch` : null,
                          p.location,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "no purity set"}
                      </p>
                    </div>
                    {p.has_opening ? (
                      <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                        Recorded
                      </span>
                    ) : (
                      <button className="btn-outline" onClick={() => openFor(p)}>
                        Record
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Step 3 — the money, once the metal is in. */}
      <section className="card">
        <h2 className="text-base font-semibold text-slate-900">Balances owed</h2>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-500">
          Type each opening balance on the customer, worker or bank account
          itself, then post them here in one go. Safe to run more than once — a
          party already posted is skipped rather than doubled — but there is no
          reason to test that on day one.
        </p>
        <button
          className="btn-primary mt-3"
          onClick={() => setPostingBalances(true)}
          disabled={!status.gold_rate_set}
        >
          Post opening balances
        </button>
        {!status.gold_rate_set && (
          <p className="mt-2 text-xs text-slate-500">
            Needs today's gold rate — worker metal has to be valued to balance the
            entry.
          </p>
        )}

        {result && (
          <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
            <p className="text-sm text-slate-600">
              Valued at {fmtMoney(result.gold_rate_per_g)} per fine gram.
            </p>
            {result.posted.length > 0 && (
              <div>
                <p className="eyebrow">Posted</p>
                <ul className="mt-1 space-y-1">
                  {result.posted.map((p) => (
                    <li key={`${p.party_type}-${p.entry_no}`} className="text-sm text-slate-700">
                      {p.party_name}{" "}
                      <span className="num text-xs text-slate-400">{p.entry_no}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.skipped.length > 0 && (
              <div>
                <p className="eyebrow">Skipped</p>
                <ul className="mt-1 space-y-1">
                  {result.skipped.map((s) => (
                    <li key={`${s.party_type}-${s.party_name}`} className="text-sm text-slate-600">
                      {s.party_name} — {s.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Step 4 — the part people skip, said out loud. */}
      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <h2 className="text-sm font-semibold text-slate-900">
          Before the first bill
        </h2>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-600">
          When every pot reads <em>Recorded</em> and the balances are posted, check
          that the shelves and the books agree before anybody sells anything. This
          is the only moment where the database is a clean statement of the shop's
          position with nothing posted against it — take a backup and label it.
        </p>
      </section>

      <PasswordConfirm
        open={!!pot}
        onClose={() => setPot(null)}
        title={`Opening balance for ${pot?.label ?? ""}`}
        description={
          metalPot
            ? "Weigh the pot and say what the metal was worth when the books opened. Booked at nothing it would be free gold on the balance sheet."
            : "Say what this held and what it was worth when the books opened. Stones and finished pieces have no market rate to fall back on, so a value left blank cannot be recovered later."
        }
        confirmLabel="Record opening balance"
        destructive={false}
        extraValid={
          metalPot
            ? Number(weight) > 0 && (Number(rate) > 0 || Number(value) > 0)
            : (Number(carats) > 0 || Number(quantity) > 0) && Number(value) > 0
        }
        onConfirm={record}
        extra={
          <div className="space-y-3">
            {metalPot ? (
              <>
                <TextField
                  label="Weight on the scale (g)"
                  inputMode="decimal"
                  value={weight}
                  onChange={(e) => setWeight(e.target.value)}
                  hint={
                    pot?.purity
                      ? `Valued as fine at ${pot.purity}k`
                      : "This pot has no purity set — the server will refuse until it does"
                  }
                  required
                />
                <TextField
                  label="Rate per fine gram"
                  inputMode="decimal"
                  value={rate}
                  onChange={(e) => setRate(e.target.value)}
                  hint="Or give the total value below instead — either one, not both."
                />
                <TextField
                  label="Total value"
                  inputMode="decimal"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
              </>
            ) : (
              <>
                <TextField
                  label="Carats"
                  inputMode="decimal"
                  value={carats}
                  onChange={(e) => setCarats(e.target.value)}
                />
                <TextField
                  label="Pieces"
                  inputMode="numeric"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                />
                <TextField
                  label="Total value"
                  inputMode="decimal"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  hint="What it was worth when the books opened."
                  required
                />
              </>
            )}
            <TextField
              label="As of"
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              hint="The day the books opened. Today if left blank."
            />
            <TextField
              label="Note"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              hint="Who weighed it, and when — this entry cannot be repeated."
            />
            {metalPot && Number(weight) > 0 && Number(rate) > 0 && (
              <p className="num rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                {wt(weight)} at {pot?.purity ?? "?"}k, valued at{" "}
                {fmtMoney(rate)} per fine gram
              </p>
            )}
          </div>
        }
      />

      <PasswordConfirm
        open={postingBalances}
        onClose={() => setPostingBalances(false)}
        title="Post opening balances"
        description="Moves every opening balance typed on a customer, worker or bank account into the ledger, each against Opening Balance Equity. Parties already posted are skipped."
        confirmLabel="Post them"
        destructive={false}
        onConfirm={postBalances}
      />
    </div>
  );
}
