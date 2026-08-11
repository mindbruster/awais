export type Currency = "PKR" | "USD";

const SYMBOL: Record<Currency, string> = {
  PKR: "₨",
  USD: "$",
};

export function currencySymbol(c: Currency | string | undefined | null): string {
  if (!c) return "";
  return SYMBOL[c as Currency] ?? c;
}

/**
 * Format a numeric value as money for the given currency.
 * Accepts strings (Pydantic serialises Decimal as a string) or numbers.
 * Always shows two decimal places.
 */
export function fmtMoney(
  value: string | number | null | undefined,
  currency: Currency | string | undefined | null = "PKR",
): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(n)) return String(value);
  const formatted = n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${currencySymbol(currency)} ${formatted}`;
}

export const CURRENCY_OPTIONS = [
  { value: "PKR", label: "PKR (₨)" },
  { value: "USD", label: "USD ($)" },
];
/**
 * Render a weight (grams or carats) with a fixed decimal count. The backend
 * stores 4 decimals to keep precision, but UI surfaces should round to 2
 * for readability. Pass a Decimal-as-string straight in.
 */
export function fmtWeight(
  value: string | number | null | undefined,
  decimals: number = 2,
): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Plain 2-decimal string for binding into numeric inputs. Unlike `fmtWeight`,
 * this returns `"0.00"` (not `"—"`) for null/empty and has no thousands
 * separators — safe to use as the `value` of an `<input type="number">`.
 */
export function to2(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "0.00";
  const n = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(n)) return "0.00";
  return n.toFixed(2);
}
