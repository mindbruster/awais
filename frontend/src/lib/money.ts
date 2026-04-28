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
