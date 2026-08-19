/**
 * The frame everything is seen through.
 *
 * The sidebar collapses to eight headings and opens the one you are standing
 * in. That is the whole idea: the list used to be thirty-eight links deep and
 * scrolled on any normal laptop, so finding a screen meant reading the entire
 * application every time. Collapsed, a person reads eight words, and the two
 * or three links they need are already open in front of them.
 *
 * A group you open by hand stays open, and a group you close stays closed —
 * until you navigate into it, which always wins. Someone who has just landed
 * on Designs must see Designs highlighted, whatever they last did to the
 * Workshop group; a remembered preference that hides where you currently are
 * is worse than no memory at all.
 *
 * ⌘K is offered in the sidebar rather than left as folklore. A shortcut nobody
 * is told about is a shortcut for the person who wrote it.
 *
 * The map itself lives in `nav.ts`; this file only draws it.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { ChangePassword } from "@/components/ChangePassword";
import { CommandPalette } from "@/components/CommandPalette";
import { NavSection, sectionForPath, visibleSections } from "@/components/nav";

const OPEN_KEY = "nav.open.v1";

/**
 * Which groups the user last left open.
 *
 * Wrapped because a locked-down browser throws on `localStorage` rather than
 * returning null, and a navigation sidebar that cannot render is a much worse
 * outcome than one that forgets.
 */
function loadOpen(): string[] | null {
  try {
    const raw = localStorage.getItem(OPEN_KEY);
    return raw ? (JSON.parse(raw) as string[]) : null;
  } catch {
    return null;
  }
}

function saveOpen(ids: string[]) {
  try {
    localStorage.setItem(OPEN_KEY, JSON.stringify(ids));
  } catch {
    /* preference only — never worth failing a render over */
  }
}

/**
 * Section icons.
 *
 * Shapes, not ornament: at a glance the eye finds "the cart" faster than it
 * reads "Buy", and on the second day of use that is most of the navigating a
 * person does. Drawn inline as paths rather than pulled from an icon package —
 * eight shapes do not justify a dependency, and these render at any size
 * without a font loading first.
 */
function SectionIcon({ name, className = "" }: { name: string; className?: string }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    "aria-hidden": true,
  };
  switch (name) {
    case "home":
      return (
        <svg {...common}>
          <path d="M3 10.5 12 3l9 7.5" />
          <path d="M5 9.5V21h14V9.5" />
        </svg>
      );
    case "tag":
      return (
        <svg {...common}>
          <path d="M3 12V4h8l10 10-8 8L3 12Z" />
          <circle cx="7.5" cy="7.5" r="1.4" />
        </svg>
      );
    case "hammer":
      return (
        <svg {...common}>
          <path d="M14 3l7 7-3 3-7-7 3-3Z" />
          <path d="M11 6 3 14v7h7l8-8" />
        </svg>
      );
    case "box":
      return (
        <svg {...common}>
          <path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5v-9Z" />
          <path d="M3 7.5 12 12l9-4.5M12 12v9" />
        </svg>
      );
    case "cart":
      return (
        <svg {...common}>
          <path d="M3 4h2l2.5 11h10L20 7H6" />
          <circle cx="9" cy="19" r="1.5" />
          <circle cx="17" cy="19" r="1.5" />
        </svg>
      );
    case "coins":
      return (
        <svg {...common}>
          <ellipse cx="12" cy="6.5" rx="8" ry="3.5" />
          <path d="M4 6.5v5c0 1.9 3.6 3.5 8 3.5s8-1.6 8-3.5v-5" />
          <path d="M4 11.5v5c0 1.9 3.6 3.5 8 3.5s8-1.6 8-3.5v-5" />
        </svg>
      );
    case "chart":
      return (
        <svg {...common}>
          <path d="M4 20V4" />
          <path d="M4 20h16" />
          <path d="M8 16v-4M12 16V8M16 16v-6" />
        </svg>
      );
    case "users":
      return (
        <svg {...common}>
          <circle cx="9" cy="8" r="3.2" />
          <path d="M3 20c0-3.3 2.7-5 6-5s6 1.7 6 5" />
          <path d="M16 5.3a3.2 3.2 0 0 1 0 6M18 20c0-2.5-.9-4.2-2.5-5.2" />
        </svg>
      );
    case "trend":
      return (
        <svg {...common}>
          <path d="m3 16 5-5 4 4 8-8" />
          <path d="M15 7h5v5" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3.2" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1" />
        </svg>
      );
  }
}

export function DashboardLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [changingPassword, setChangingPassword] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const role = user?.role.name ?? "";

  // Which modules this shop uses. Fetched once; a failure leaves every section
  // showing, which is the safe direction — a sidebar that hides itself because
  // a request failed is indistinguishable from a shop that switched everything
  // off, and the server refuses what it must regardless.
  const [enabled, setEnabled] = useState<string[] | null>(null);
  useEffect(() => {
    api
      .get<{ key: string; enabled: boolean }[]>("/modules")
      .then((r) => setEnabled(r.data.filter((m) => m.enabled).map((m) => m.key)))
      .catch(() => setEnabled(null));
  }, []);

  const sections = useMemo(
    () =>
      visibleSections(role).filter(
        (s) => enabled === null || enabled.includes(s.id) || s.id === "settings",
      ),
    [role, enabled],
  );
  const active = useMemo(
    () => sectionForPath(location.pathname, role),
    [location.pathname, role],
  );

  // Starts from what the user last left open, falling back to just the section
  // they are standing in — a first visit should show the shape of the app, not
  // all eight groups expanded at once, which is the flat list again.
  const [open, setOpen] = useState<string[]>(() => {
    const saved = loadOpen();
    if (saved) return saved;
    const here = sectionForPath(window.location.pathname, role);
    return here ? [here] : ["today"];
  });

  // Navigation wins over preference. Landing on a page inside a collapsed
  // group and seeing nothing highlighted reads as "this link did nothing".
  useEffect(() => {
    if (active && !open.includes(active)) {
      setOpen((prev) => {
        const next = [...prev, active];
        saveOpen(next);
        return next;
      });
    }
    // `open` is deliberately not a dependency: this reacts to *moving*, and
    // including it would re-add a group the instant the user closed it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  const toggle = useCallback((id: string) => {
    setOpen((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      saveOpen(next);
      return next;
    });
  }, []);

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center rounded-lg py-1.5 pl-9 pr-3 text-sm transition ${
      isActive
        ? "bg-brand-50 font-medium text-brand-700"
        : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
    }`;

  const navContent = (
    <>
      <div className="px-5 pb-3 pt-5">
        <div className="text-base font-semibold text-brand-700">Jewelry ERP</div>
        <div className="text-[11px] text-slate-400">v0.5.0</div>
      </div>

      {/* The shortcut, said out loud. */}
      <button
        onClick={() =>
          window.dispatchEvent(
            new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
          )
        }
        className="mx-3 mb-2 flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5 text-left text-sm text-slate-400 transition hover:border-slate-300 hover:text-slate-600"
      >
        <svg
          width="14" height="14" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2" aria-hidden="true"
        >
          <circle cx="11" cy="11" r="7" />
          <line x1="16.5" y1="16.5" x2="21" y2="21" />
        </svg>
        <span className="flex-1">Go to…</span>
        <kbd className="rounded border border-slate-200 px-1 text-[10px]">⌘K</kbd>
      </button>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-4">
        {sections.map((s) => (
          <Group
            key={s.id}
            section={s}
            open={open.includes(s.id)}
            here={active === s.id}
            onToggle={() => toggle(s.id)}
            linkClass={linkClass}
          />
        ))}
      </nav>

      <div className="border-t border-slate-200 px-4 py-3">
        <div className="text-sm font-medium text-slate-800">{user?.full_name}</div>
        <div className="text-xs capitalize text-slate-500">{role}</div>
        {/* Here rather than under Settings: every role needs it, and most roles
            cannot open Settings at all. */}
        <button onClick={() => setChangingPassword(true)} className="btn-ghost mt-2 w-full">
          Change password
        </button>
        <button onClick={handleLogout} className="btn-ghost mt-1 w-full">
          Sign out
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-slate-50">
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

      <aside className="no-print fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-slate-200 bg-white md:flex">
        {navContent}
      </aside>

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

      <CommandPalette role={role} />

      <main className="md:pl-60">
        <div className="mx-auto max-w-6xl px-4 py-6 md:px-6 md:py-8">
          <Outlet />
        </div>
      </main>

      <ChangePassword
        open={changingPassword}
        onClose={() => setChangingPassword(false)}
      />
    </div>
  );
}

function Group({
  section,
  open,
  here,
  onToggle,
  linkClass,
}: {
  section: NavSection;
  open: boolean;
  here: boolean;
  onToggle: () => void;
  linkClass: (p: { isActive: boolean }) => string;
}) {
  return (
    <div>
      <button
        onClick={onToggle}
        aria-expanded={open}
        className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition ${
          here ? "text-brand-700" : "text-slate-700 hover:bg-slate-100"
        }`}
      >
        <SectionIcon name={section.icon} className="flex-none" />
        <span className="flex-1 text-left font-medium">{section.label}</span>
        {/* A closed group holding the current page keeps a dot, so the sidebar
            never loses track of where you are even when you collapse it. */}
        {here && !open && <span className="h-1.5 w-1.5 flex-none rounded-full bg-brand-500" />}
        <svg
          width="14" height="14" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2" aria-hidden="true"
          className={`flex-none text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}
        >
          <path d="m9 6 6 6-6 6" />
        </svg>
      </button>
      {open && (
        <div className="space-y-0.5 pb-1">
          {section.items.map((i) => (
            <NavLink key={i.to} to={i.to} end={i.end} className={linkClass} title={i.hint}>
              {i.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}
