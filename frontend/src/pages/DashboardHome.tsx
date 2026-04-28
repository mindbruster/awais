import { useAuthStore } from "@/store/auth";

const TILES = [
  { label: "Manufacturing", to: "/manufacturing", hint: "Karigar → stones → polish → finished" },
  { label: "Invoices", to: "/invoices", hint: "Sales (normal + on-approval)" },
  { label: "Products", to: "/products", hint: "Catalogue, serials, images" },
  { label: "Inventory", to: "/inventory", hint: "Raw + finished stock" },
  { label: "Stock ledger", to: "/stock-movements", hint: "Immutable movement audit" },
  { label: "Customers", to: "/customers", hint: "Buyers & contacts" },
  { label: "Vendors", to: "/vendors", hint: "Karigars, fixers, polishers" },
];

export function DashboardHome() {
  const user = useAuthStore((s) => s.user);
  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">
        Welcome, {user?.full_name}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        Phases 1–6 backend is live. Pick a module to start working.
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {TILES.map((t) => (
          <a key={t.to} href={t.to} className="card transition hover:shadow-md">
            <div className="text-base font-semibold text-slate-900">{t.label}</div>
            <div className="mt-1 text-sm text-slate-500">{t.hint}</div>
          </a>
        ))}
      </div>
    </div>
  );
}
