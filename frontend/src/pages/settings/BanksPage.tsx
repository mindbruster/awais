import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { MasterTable } from "@/components/MasterTable";
import { fmtMoney } from "@/lib/money";

interface Bank {
  id: number;
  name: string;
}

const CURRENCIES = [
  { value: "PKR", label: "PKR" },
  { value: "USD", label: "USD" },
];

export function BanksPage() {
  const [banks, setBanks] = useState<Bank[]>([]);
  const [tab, setTab] = useState<"banks" | "accounts">("banks");
  const [refresh, setRefresh] = useState(0);

  const loadBanks = () => {
    api
      .get<Bank[]>("/banks", { params: { limit: "500" } })
      .then((res) => setBanks(res.data))
      .catch(() => setBanks([]));
  };

  useEffect(loadBanks, [refresh]);

  return (
    <div>
      <div className="mb-5 flex gap-1 border-b border-slate-200">
        {(["banks", "accounts"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium capitalize transition ${
              tab === t
                ? "border-brand-600 text-brand-700"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "banks" ? (
        <MasterTable
          title="Banks"
          description="Banks the shop holds accounts with. The deduction rate is what that bank takes on a transaction — it is why the invoice total and the amount that actually lands are different numbers."
          endpoint="/banks"
          noun="bank"
          searchPlaceholder="Search banks…"
          onChanged={() => setRefresh((n) => n + 1)}
          fields={[
            { key: "name", label: "Name", required: true, half: true },
            {
              key: "deduction_rate",
              label: "Deduction %",
              type: "number",
              step: "0.001",
              half: true,
              hint: "Charge taken by the bank per transaction",
              render: (r) => `${Number(r.deduction_rate)}%`,
            },
            { key: "is_active", label: "Active", type: "checkbox" },
            { key: "notes", label: "Notes", type: "textarea", hideInTable: true },
          ]}
        />
      ) : (
        <MasterTable
          title="Bank accounts"
          description="Accounts held at those banks. The opening balance is the cash already in the account the day the shop starts using this system."
          endpoint="/bank-accounts"
          noun="bank account"
          labelKey="account_no"
          searchPlaceholder="Search account number or title…"
          refreshKey={refresh}
          fields={[
            {
              key: "bank_id",
              label: "Bank",
              type: "select",
              required: true,
              half: true,
              options: banks.map((b) => ({ value: b.id, label: b.name })),
              hideInTable: true,
            },
            { key: "bank_name", label: "Bank", hideInForm: true },
            { key: "account_no", label: "Account no.", required: true, half: true },
            { key: "title", label: "Title", half: true },
            {
              key: "currency",
              label: "Currency",
              type: "select",
              half: true,
              options: CURRENCIES,
              initial: "PKR",
            },
            {
              key: "opening_balance",
              label: "Opening balance",
              type: "number",
              step: "0.01",
              half: true,
              render: (r) => fmtMoney(r.opening_balance, r.currency),
            },
            { key: "is_active", label: "Active", type: "checkbox", half: true },
          ]}
        />
      )}
    </div>
  );
}
