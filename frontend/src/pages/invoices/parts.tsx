/**
 * The shapes an invoice screen and an invoice document both read.
 *
 * Shared rather than declared twice: the printable copy and the working screen
 * describe the same bill, and two drifting copies of these fields is how a
 * document ends up showing a figure the screen never had.
 */
import { Currency } from "@/lib/money";

export interface InvoiceItem {
  id: number;
  description: string;
  quantity: number;
  gold_weight_g: string;
  gold_purity: number | null;
  gold_rate_per_g: string;
  gold_amount: string;
  stone_weight_ct: string;
  stone_rate_per_ct: string;
  stone_amount: string;
  labor_amount: string;
  line_discount: string;
  discount_ratti: string;
  ratti_base: number;
  sale_wastage_pct: string;
  sale_wastage_g: string;
  // Both server-derived: charged = net + wastage, billable = charged less the
  // ratti discount. Never recomputed here, so the printed document can only
  // ever agree with what was billed.
  charged_gold_weight_g: string;
  billable_gold_weight_g: string;
  line_total: string;
  // The piece itself. `description` is typed at the counter and is often just
  // "ring"; these identify the physical object the customer is holding.
  product_id: number | null;
  product_name: string | null;
  product_serial_no: string | null;
  product_image_url: string | null;
}

export interface Payment {
  id: number;
  payment_no: string;
  invoice_id: number | null;
  customer_id: number;
  method: string;
  direction: string;
  amount: string;
  gold_weight_g: string | null;
  gold_purity: number | null;
  gold_rate_per_g: string | null;
  gold_fine_g: string | null;
  bank_account_label: string | null;
  paid_at: string;
  reference: string | null;
  notes: string | null;
  entry_no: string | null;
  is_reversed: boolean;
}

/** Who the shop is, at the top of the customer's copy. */
export interface Letterhead {
  print_name: string;
  tagline: string | null;
  logo_url: string | null;
  phone: string | null;
  address: string | null;
  city_name: string | null;
}

export interface Invoice {
  id: number;
  created_at: string;
  invoice_no: string;
  sale_type: string;
  status: string;
  customer_id: number;
  branch_id: number | null;
  letterhead: Letterhead | null;
  currency: Currency;
  fx_rate_to_pkr: string | null;
  gold_rate_per_g: string;
  // Whether this bill charges its gold in money or in metal, snapshotted from
  // the customer when it was raised. On a `grams` bill the metal is not priced
  // anywhere: `total` carries only stones and making, and `metal_due_fine_g` is
  // the fine weight the buyer hands over instead.
  gold_charged_in: "rupees" | "grams";
  metal_due_fine_g: string;
  subtotal: string;
  discount_amount: string;
  discount_weight_g: string;
  tax_amount: string;
  round_off: string;
  total: string;
  bill_book_no: string | null;
  // Credit terms, and the date they land on. `due_date` is derived server-side
  // from issued_at + term_days, and is null until the bill is issued.
  term_days: number;
  due_date: string | null;
  issued_at: string | null;
  paid_at: string | null;
  notes: string | null;
  items: InvoiceItem[];
  // Summed from the payment rows on the server every read — never stored, so
  // it cannot drift from the money that was actually taken.
  amount_paid: string;
  balance_due: string;
  customer_balance: string;
  payments: Payment[];
}
