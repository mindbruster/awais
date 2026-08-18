/**
 * The customer's copy, in the form this shop issues it.
 *
 * A reproduction of the jeweller's own bill, not a house style: light grey-black
 * type on white, the mark top-left and the business name set large on the right,
 * one ruled table, and a photograph of the piece on every line. Their customers
 * have been handed this document for years and recognise it. A bill that arrives
 * looking like software output reads as a different business.
 *
 * The trade convention it encodes is the important part. A piece here is two
 * purchases on one line: so many grams of gold at the day's rate, and so many
 * carats of diamond at the agreed rate. Each gets its own weight and its own
 * rate column, and each is totalled separately at the foot, because metal and
 * stones settle separately and a combined figure would answer neither
 * question.
 *
 * Every figure is read off the invoice as billed. Nothing here recomputes a
 * total from a rate — a printed document that disagrees with the ledger by a
 * rounding step is worse than no document.
 */
import { Invoice, InvoiceItem } from "./parts";
import { Img } from "@/components/Img";

/**
 * How this shop writes currency on a bill: `Rs. 355,600.00`, `US$ 187.00`.
 *
 * Deliberately not `currencySymbol` from the money helper, which gives the
 * typographic ₨ and $ the screens use. On paper the shop writes it out, and
 * ₨ is a glyph half the printers in the market render as a box.
 */
const PRINTED_CURRENCY: Record<string, string> = { PKR: "Rs.", USD: "US$" };

/** `24/04/2026` — how the shop writes a date, and unambiguous on paper. */
function printDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
}

/** Plain grouped number. The grid carries the meaning; a currency symbol in
 *  every cell only makes the columns harder to read down. */
function num(value: string | number | null | undefined, dp: number): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "";
  return n.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

/**
 * Weights are held per unit; money is held for the whole line.
 *
 * `billable_gold_weight_g` and `stone_weight_ct` describe one piece, while
 * `gold_amount` and `line_total` are already multiplied by quantity — that is
 * how pricing, stock deduction and costing all work. Printing the per-unit
 * weight beside the line's money would understate a multi-piece line.
 */
function perLine(
  it: InvoiceItem,
  field: "charged_gold_weight_g" | "billable_gold_weight_g" | "stone_weight_ct",
): number {
  return Number(it[field] || 0) * (it.quantity || 1);
}

/** `SR NO 720 (G.W=2.800 , D.W=0.34)` — the shop's own way of naming a piece:
 *  what it is, then the two weights that describe it. */
function productName(it: InvoiceItem): string {
  // The charged weight, matching the Gold Weight column beside it. Showing the
  // post-discount figure here while the column shows the pre-discount one puts
  // two different gold weights on the same row, which reads as an error.
  const gw = perLine(it, "charged_gold_weight_g");
  const dw = perLine(it, "stone_weight_ct");
  const parts: string[] = [];
  if (gw > 0) parts.push(`G.W=${num(gw, 3)}`);
  if (dw > 0) parts.push(`D.W=${num(dw, 2)}`);
  const base = it.product_name || it.description;
  return parts.length ? `${base} (${parts.join(" , ")})` : base;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="font-semibold">{label}</span> {children}
    </div>
  );
}

/**
 * A ruled two-cell box: the unit, then the figure.
 *
 * Printed even when the figure is zero. A bill with no diamonds on it still
 * says so — a missing box reads as an omission, and the customer cannot tell
 * "none" from "we forgot to weigh them".
 */
function WeightTotal({ label, unit, value }: { label: string; unit: string; value: string }) {
  return (
    <div>
      <div className="font-semibold">{label}</div>
      <div className="mt-1 flex w-56 border border-neutral-400">
        <div className="w-1/2 border-r border-neutral-400 px-2 py-1">{unit}</div>
        <div className="w-1/2 px-2 py-1 text-right tabular-nums">{value}</div>
      </div>
    </div>
  );
}

export function PrintableInvoice({ invoice, customerName, accountNo }: {
  invoice: Invoice;
  customerName: string;
  accountNo?: string | null;
}) {
  const shop = invoice.letterhead;
  const items = invoice.items;
  // Which of the shop's two bills this is. The two are not one document with
  // some columns blank: a parcel of stones has no gold to weigh, no wastage,
  // and its discount is argued against the stone price rather than in ratti
  // against the metal. Printing one layout for both would put a Gold Weight
  // column on a bill that has no gold on it.
  const loose = invoice.kind === "loose_material";
  const symbol = PRINTED_CURRENCY[invoice.currency] ?? invoice.currency;

  // Both weights are totalled. Metal and stones settle differently in this
  // trade and the shop reads them as two separate running figures, so one
  // combined number at the foot of a bill would answer neither question.
  const goldWeight = items.reduce((t, it) => t + perLine(it, "billable_gold_weight_g"), 0);
  const carats = items.reduce((t, it) => t + perLine(it, "stone_weight_ct"), 0);
  // A trade bill settles its gold in gold. Nothing in the money column prices
  // metal, so the money column has to say so — otherwise "Total" reads as the
  // whole cost of the piece when it is only the stones and the making.
  const inMetal = invoice.gold_charged_in === "grams";
  const received = Number(invoice.amount_paid || 0);
  const discount = Number(invoice.discount_amount || 0);
  const balance = Number(invoice.balance_due || 0);

  const cell = "border border-neutral-400 px-2 py-1 align-top";
  const head = `${cell} text-left font-semibold`;

  return (
    <div className="print-doc mx-auto w-full max-w-[820px] bg-white p-8 font-sans text-[13px] text-neutral-900 print:max-w-none print:p-0">
      {/* --- letterhead: mark left, name right --- */}
      <header className="flex items-start justify-between gap-6">
        {shop?.logo_url ? (
          /* On paper a missing logo leaves the space blank rather than
             printing the word "missing" across the top of a customer's bill. */
          <Img
            src={shop.logo_url}
            alt=""
            loading="eager"
            className="h-28 w-28 flex-none object-contain"
            fallbackClassName="h-28 w-28 flex-none"
          />
        ) : (
          <div className="h-28 w-28 flex-none" />
        )}
        <div className="text-right">
          <div className="text-4xl font-light leading-tight tracking-tight">
            {shop?.print_name ?? "—"}
          </div>
          {shop?.tagline && (
            <div className="text-3xl font-light leading-tight">{shop.tagline}</div>
          )}
          {(shop?.address || shop?.city_name || shop?.phone) && (
            <div className="mt-1 text-[0.85em] text-neutral-600">
              {[shop?.address, shop?.city_name, shop?.phone].filter(Boolean).join(" · ")}
            </div>
          )}
        </div>
      </header>

      <h1 className="mt-6 text-3xl font-light">Invoice</h1>

      {/* --- who, and on what terms --- */}
      <div className="mt-1 flex items-start justify-between gap-6">
        <div className="font-semibold uppercase">{customerName}</div>
        <div className="space-y-0.5 text-right">
          <Field label="Inv No.">{invoice.invoice_no}</Field>
          <Field label="Date">{printDate(invoice.issued_at ?? invoice.created_at)}</Field>
          <Field label="Term Days">{invoice.term_days ?? 0}</Field>
          {/* Blank until the bill is issued: a draft has no date to count from,
              and printing today's would promise a deadline nobody agreed. */}
          <Field label="Due Date">
            {invoice.due_date ? printDate(invoice.due_date) : "—"}
          </Field>
          {accountNo && <Field label="Account No">{accountNo}</Field>}
        </div>
      </div>

      {/* --- the goods --- */}
      <table className="mt-5 w-full table-fixed border-collapse tabular-nums">
        {/* Metal and stones get a weight and a rate each. A piece in this trade
            is two purchases in one line — so many grams of gold at today's
            rate, and so many carats at the agreed rate — and a customer
            checking the bill wants to see the two settled separately. */}
        {loose ? (
          /* No gold column and no photograph. A parcel of stones is not a
             piece: there is nothing to weigh in grams and nothing to show a
             picture of, and leaving both in blank would print a form that
             looks half filled in rather than one that fits what was sold. */
          <colgroup>
            <col className="w-[6%]" />
            <col className="w-[40%]" />
            <col className="w-[12%]" />
            <col className="w-[14%]" />
            <col className="w-[12%]" />
            <col className="w-[16%]" />
          </colgroup>
        ) : (
          <colgroup>
            <col className="w-[5%]" />
            <col className="w-[29%]" />
            <col className="w-[12%]" />
            <col className="w-[12%]" />
            <col className="w-[9%]" />
            <col className="w-[12%]" />
            <col className="w-[21%]" />
          </colgroup>
        )}
        <thead>
          {loose ? (
            /* The discount sits *after* the stone price here, and that is the
               point of having two layouts rather than one with blanks. On a
               finished piece the discount is argued in ratti against the gold;
               on a parcel there is no gold to argue against, so it comes off
               the stone price. The column order says which conversation this
               bill was. */
            <tr>
              <th className={head}>Sr</th>
              <th className={head}>Product Details</th>
              <th className={`${head} text-right`}>
                Diamond
                <br />
                CT
              </th>
              <th className={`${head} text-right`}>
                Diamond
                <br />
                Price
              </th>
              <th className={`${head} text-right`}>Discount</th>
              <th className={`${head} text-right`}>Amount</th>
            </tr>
          ) : (
          <tr>
            <th className={head}>Sr</th>
            <th className={head}>Product Details</th>
            <th className={`${head} text-right`}>
              Gold
              <br />
              Weight
            </th>
            {/* Negotiated in ratti, against a base of 96 — the lever the counter
                actually argues in. It comes off the metal, not the money, which
                is why it sits in the gold half of the table and not beside the
                diamond price. */}
            <th className={`${head} text-right`}>Discount</th>
            <th className={`${head} text-right`}>
              Diamond
              <br />
              CT
            </th>
            <th className={`${head} text-right`}>
              Diamond
              <br />
              Price
            </th>
            <th className={`${head} text-center`}>Image</th>
          </tr>
          )}
        </thead>
        <tbody>
          {items.map((it, i) => {
            const ct = perLine(it, "stone_weight_ct");
            // The weight before the ratti discount comes off. The discount
            // column takes it from here and the foot of the bill shows what is
            // left, so the three figures read across as one sum the customer
            // can check: weight, less discount, equals what he hands over.
            const weight = perLine(it, "charged_gold_weight_g");
            const ratti = Number(it.discount_ratti || 0);
            // Grams the discount actually removed, taken as the difference
            // between the two server-derived weights rather than recomputed
            // from the ratti — the bill must never do its own arithmetic.
            const rattiGrams = weight - perLine(it, "billable_gold_weight_g");
            return (
              <tr key={it.id}>
                <td className={cell}>{i + 1}</td>
                {/* Serial, name and the two weights in one cell. They were
                    separate columns when the bill had nine of them; at seven
                    the piece is described in one place and the numbers that
                    settle get the width instead. */}
                <td className={cell}>
                  {it.product_serial_no && (
                    <div className="break-all font-semibold">{it.product_serial_no}</div>
                  )}
                  {productName(it)}
                  {/* The quality of the metal, and nothing else. The weights
                      have columns of their own, and repeating the arithmetic
                      underneath the name only gave the customer two places to
                      check the same figure. */}
                  {(it.gold_purity || (it.quantity || 1) > 1) && (
                    <div className="mt-0.5 text-[0.85em] text-neutral-600">
                      {it.gold_purity ? `${it.gold_purity}k` : ""}
                      {it.gold_purity && (it.quantity || 1) > 1 ? " · " : ""}
                      {(it.quantity || 1) > 1 ? `× ${it.quantity}` : ""}
                    </div>
                  )}
                </td>
                {/* Gold only on a finished piece. */}
                {!loose && (
                  <td className={`${cell} text-right`}>{weight ? num(weight, 3) : ""}</td>
                )}
                {/* Blank when nothing was given away. A nought here would read
                    as a discount of zero that somebody negotiated, which is a
                    different conversation from one that never happened. */}
                {/* Ratti off the metal on a finished piece; on a parcel the
                    discount is money off the stone price and moves after it. */}
                {!loose && (
                  <td className={`${cell} text-right`}>
                    {ratti > 0 ? (
                      <>
                        <div>
                          {num(ratti, ratti % 1 ? 2 : 0)}/{it.ratti_base || 96}
                        </div>
                        {rattiGrams > 0 && (
                          <div className="text-[0.85em] text-neutral-600">
                            −{num(rattiGrams, 3)} g
                          </div>
                        )}
                      </>
                    ) : (
                      ""
                    )}
                  </td>
                )}
                <td className={`${cell} text-right`}>{ct ? num(ct, 2) : ""}</td>
                <td className={`${cell} text-right`}>
                  {ct ? num(it.stone_rate_per_ct, 0) : ""}
                </td>
                {loose && (
                  <>
                    {/* Blank when nothing was given away. A nought would read as
                        a discount somebody negotiated down to zero, which is a
                        different conversation from one that never happened. */}
                    <td className={`${cell} text-right`}>
                      {Number(it.line_discount || 0) > 0 ? num(it.line_discount, 0) : ""}
                    </td>
                    <td className={`${cell} text-right`}>{num(it.line_total, 0)}</td>
                  </>
                )}
                {/* A fixed height, not one that follows the photograph: rows of
                    equal height are what makes the grid readable across a bill
                    of ten pieces, and a portrait shot next to a landscape one
                    would otherwise stagger every row. The column is always
                    here, empty or not — it is part of the form. */}
                {/* No photograph on a parcel of stones — there is no piece to
                    show, and an empty frame prints as a form half filled in. */}
                {!loose && (
                  <td className={`${cell} h-40 text-center`}>
                    {it.product_image_url ? (
                      /* On paper a missing photograph leaves the cell empty
                         rather than printing a placeholder across a customer's
                         bill. The row keeps its fixed height either way, so a
                         bill of ten pieces stays on its grid. */
                      <Img
                        src={it.product_image_url}
                        alt=""
                        loading="eager"
                        className="mx-auto max-h-36 object-contain"
                        fallbackClassName=""
                      />
                    ) : null}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* --- the two totals that matter: the stones, and the money --- */}
      <div className="mt-5 flex flex-wrap items-start justify-between gap-8">
        <div className="space-y-3">
          {/* On a trade bill this is the obligation itself — the fine weight
              the buyer hands over, and the same figure the ledger posted — so
              it is named as the instruction it is. On a counter bill the metal
              was paid for in money and there is nothing to hand over, so the
              box goes back to describing the pieces. */}
          {inMetal ? (
            <WeightTotal
              label="GOLD WEIGHT TO TAKE"
              unit="FINE G"
              value={num(invoice.metal_due_fine_g, 3)}
            />
          ) : (
            <WeightTotal label="TOTAL GOLD WEIGHT" unit="G" value={num(goldWeight, 3)} />
          )}
          <WeightTotal label="TOTAL DIAMOND WEIGHT" unit="CT" value={num(carats, 2)} />
        </div>

        <div className="w-72 tabular-nums">
          <div className="flex justify-between border-b border-neutral-300 py-1">
            <span>Sub Total:</span>
            <span>{num(invoice.subtotal, 2)}</span>
          </div>
          {/* Always printed, even at nil. A customer who negotiated nothing off
              should be able to see that on the bill rather than infer it from
              a row that is not there. */}
          <div className="flex justify-between border-b border-neutral-300 py-1">
            <span>Discount:</span>
            <span>{discount > 0 ? `−${num(discount, 2)}` : num(0, 2)}</span>
          </div>
          {Number(invoice.tax_amount) > 0 && (
            <div className="flex justify-between border-b border-neutral-300 py-1">
              <span>Tax:</span>
              <span>{num(invoice.tax_amount, 2)}</span>
            </div>
          )}
          <div className="flex items-baseline justify-between border-b border-neutral-400 py-1">
            <span className="text-xl font-bold">{inMetal ? "Cash Total:" : "Total:"}</span>
            <span className="text-xl font-bold">
              {symbol} {num(invoice.total, 2)}
            </span>
          </div>
          {/* Said outright rather than left to be inferred from a missing rate
              column. The buyer owes two things in two units, and a bill that
              shows only the money invites him to think that is all of it. */}
          {inMetal && (
            <div className="mt-1 text-[0.9em] leading-snug">
              Payable in cash for stones and making. The gold is settled
              separately, in metal — see <span className="font-semibold">gold weight to take</span>.
            </div>
          )}
          {/* Only once money has moved. On an unpaid bill these two lines would
              just repeat the total twice and say nothing. */}
          {received !== 0 && (
            <>
              <div className="flex justify-between border-b border-neutral-300 py-1">
                <span>Received:</span>
                <span>{num(received, 2)}</span>
              </div>
              <div className="flex justify-between border-b border-neutral-400 py-1 font-bold">
                <span>Balance Due:</span>
                <span>
                  {symbol} {num(balance, 2)}
                </span>
              </div>
            </>
          )}
        </div>
      </div>

      {/* --- notes --- */}
      <div className="mt-6">
        <div className="font-semibold">Notes</div>
        <div className="mt-1 border-t border-neutral-400 pt-2 text-center text-[0.9em]">
          {invoice.notes ? (
            <p className="whitespace-pre-line text-left">{invoice.notes}</p>
          ) : null}
          <p className={invoice.notes ? "mt-2" : ""}>
            This is a system generated invoice and does not require any signatures.
          </p>
        </div>
      </div>

      {/* Screen only: on paper the document speaks for itself, and a bill headed
          with a draft warning is not a bill. */}
      {invoice.status === "draft" && (
        <div className="no-print mt-4 border border-amber-400 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
          This is a draft. It has not been issued, nothing has been posted to the books, and the
          totals can still change.
        </div>
      )}
      {invoice.status === "void" && (
        <div className="mt-4 border-2 border-red-600 px-3 py-2 text-center text-lg font-bold text-red-600">
          VOID
        </div>
      )}
    </div>
  );
}
