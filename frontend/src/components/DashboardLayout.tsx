import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/auth";
import { useEffect } from "react";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  /** If set, only roles in this list see the item. */
  roles?: string[];
}

// Mirrors backend permissions in app/core/permissions.py.
const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/designs", label: "Designs" },
  { to: "/manufacturing", label: "Manufacturing" },
  { to: "/invoices", label: "Invoices" },
  { to: "/products", label: "Products" },
  { to: "/inventory", label: "Inventory" },
  { to: "/stones", label: "Stones" },
  { to: "/stock-movements", label: "Stock ledger" },
  { to: "/customers", label: "Customers" },
  { to: "/vendors", label: "Workers" },
  { to: "/gold-rates", label: "Gold rates" },
  { to: "/reports", label: "Reports" },
  // Owner-level analysis; staff already cannot see the money reports it reads.
  { to: "/insights", label: "Insights", roles: ["admin", "accountant"] },
];

// The books. Worker gold liabilities and cash positions are owner information,
// so this whole section is hidden from staff — they post into the ledger by
// doing their job, but they don't get to read it.
const LEDGER_NAV: NavItem[] = [
  { to: "/ledger/position", label: "Position" },
  { to: "/ledger/statement", label: "Statements" },
  { to: "/ledger/journal", label: "Journal" },
  { to: "/ledger/accounts", label: "Chart of accounts" },
];

// Reference data, configured once and then selected from everywhere. Staff can
// read these but only admins and accountants may change them, so the section is
// hidden from staff rather than showing them screens they can't act on.
const SETTINGS_NAV: NavItem[] = [
  { to: "/settings/items", label: "Items" },
  { to: "/settings/departments", label: "Departments" },
  { to: "/settings/stone-attributes", label: "Stone attributes" },
  { to: "/settings/locations", label: "Countries & cities" },
  { to: "/settings/banks", label: "Banks" },
];

export function DashboardLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const role = user?.role.name ?? "";

  // Close drawer on route change
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const visibleNav = NAV.filter((n) => !n.roles || n.roles.includes(role));
  const canManageMasters = role === "admin" || role === "accountant";

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `block rounded-lg px-3 py-2 text-sm font-medium transition ${
      isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
    }`;

  const navContent = (
    <>
      <div className="px-6 py-5">
        <div className="text-lg font-semibold text-brand-700">Jewelry ERP</div>
        <div className="text-xs text-slate-500">v0.4.0</div>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 pb-4">
        {visibleNav.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
            {item.label}
          </NavLink>
        ))}
        {canManageMasters && (
          <>
            <div className="px-3 pb-1 pt-5 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Books
            </div>
            {LEDGER_NAV.map((item) => (
              <NavLink key={item.to} to={item.to} className={linkClass}>
                {item.label}
              </NavLink>
            ))}
            <div className="px-3 pb-1 pt-5 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Setup
            </div>
            {SETTINGS_NAV.map((item) => (
              <NavLink key={item.to} to={item.to} className={linkClass}>
                {item.label}
              </NavLink>
            ))}
          </>
        )}
      </nav>
      <div className="border-t border-slate-200 px-4 py-4">
        <div className="text-sm font-medium text-slate-800">{user?.full_name}</div>
        <div className="text-xs capitalize text-slate-500">{role}</div>
        <button onClick={handleLogout} className="btn-ghost mt-3 w-full">
          Sign out
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Mobile top bar */}
      <header className="no-print sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <button
          aria-label="Open navigation"
          onClick={() => setDrawerOpen(true)}
          className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100"
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <div className="text-base font-semibold text-brand-700">Jewelry ERP</div>
        <div className="w-7" />
      </header>

      {/* Persistent sidebar (desktop) */}
      <aside className="no-print fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-slate-200 bg-white md:flex">
        {navContent}
      </aside>

      {/* Drawer (mobile) */}
      {drawerOpen && (
        <div className="no-print fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <aside className="relative ml-0 flex h-full w-64 flex-col bg-white shadow-xl">
            <div className="flex justify-end px-3 pt-3">
              <button
                aria-label="Close navigation"
                onClick={() => setDrawerOpen(false)}
                className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            {navContent}
          </aside>
        </div>
      )}

      <main className="md:pl-60">
        <div className="mx-auto max-w-6xl px-4 py-6 md:px-6 md:py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
