import { Link } from "react-router-dom";

import { useAuthStore } from "@/store/auth";

/**
 * Grouped the way the shop's day is: metal comes in, work happens on it, it
 * gets sold, and then somebody asks what it all came to. The flat list this
 * replaced stopped at the manufacturing modules, so the reports, the buying
 * side and the books — everything that answers "what did I make on it" — were
 * reachable only from the sidebar.
 */
const GROUPS = [
  {
    title: "On the floor",
    tiles: [
      { label: "Designs", to: "/designs", hint: "Casting → setting → polish → finish, and who holds it" },
      { label: "Products", to: "/products", hint: "Finished pieces: catalogue, serials, images" },
      { label: "Workers", to: "/vendors", hint: "Karigars and their agreed wastage" },
    ],
  },
  {
    title: "Buying and stock",
    tiles: [
      { label: "Old gold", to: "/purchasing/old-gold", hint: "Metal bought back over the counter" },
      { label: "Stone purchases", to: "/purchasing/stones", hint: "Supplier bills, by graded lot" },
      { label: "Inventory", to: "/inventory", hint: "Raw metal, stones and finished stock" },
    ],
  },
  {
    title: "Selling",
    tiles: [
      { label: "Invoices", to: "/invoices", hint: "Sales, on-approval and payments" },
      { label: "Customers", to: "/customers", hint: "Buyers, balances and statements" },
      { label: "Gold rates", to: "/gold-rates", hint: "Today's rate, and the dollar" },
    ],
  },
  {
    title: "What it came to",
    tiles: [
      { label: "Reports", to: "/reports", hint: "Margin, wastage and what the floor produced" },
      { label: "Insights", to: "/insights", hint: "Where the metal and the margin are going" },
      { label: "Position", to: "/ledger/position", hint: "Cash, metal, and who owes whom" },
    ],
  },
];

export function DashboardHome() {
  const user = useAuthStore((s) => s.user);
  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">
        Welcome, {user?.full_name}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        Metal in, work on it, sold, counted. Pick where you are.
      </p>
      <div className="mt-8 flex flex-col gap-8">
        {GROUPS.map((g) => (
          <section key={g.title}>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              {g.title}
            </h2>
            <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {g.tiles.map((t) => (
                // Link, not a bare anchor: an <a href> tears the whole app down
                // and rebuilds it, which on a tile grid reads as the software
                // being slow.
                <Link key={t.to} to={t.to} className="card transition hover:shadow-md">
                  <div className="text-base font-semibold text-slate-900">{t.label}</div>
                  <div className="mt-1 text-sm text-slate-500">{t.hint}</div>
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
