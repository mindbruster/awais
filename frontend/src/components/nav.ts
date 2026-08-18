/**
 * Where everything lives, and what to call it.
 *
 * This file is the shop's map. It was extracted from `DashboardLayout` when
 * that layout had thirty-eight destinations in it, twenty-two of them in a
 * single ungrouped column before the first heading — so the part of the list a
 * new user met first was the part with no structure at all.
 *
 * The section list and its order come from **§22 of the UI/UX specification**.
 * Following the written spec matters more here than any grouping I would
 * prefer: an application whose sidebar disagrees with its own design document
 * is one nobody can check against anything.
 *
 * Three rules hold the rest together.
 *
 * **A label says what the screen answers.** Six links used to say some version
 * of "your stuff is here" — Stock, Inventory, Stones, Stone stock, Stock
 * ledger, Products — and nothing in the words told them apart. `Stones` was the
 * worst: a *catalogue* of grades with no quantity on it, filed between two
 * holdings screens, so it read as stones the shop owned. It is now "Stone
 * list", under Settings, where reference data belongs.
 *
 * **The two rate screens say which one bills.** "Gold rates" and "Live rates"
 * were indistinguishable by name though one is the rate the shop prices at and
 * the other is untouchable spot. They are now "Rates you set" and "Live gold &
 * silver", under Market rates, as §16 asks.
 *
 * **Every entry carries the words a person would actually search.** `keywords`
 * is not SEO; it is the vocabulary gap. A jeweller looks for "karigar", not
 * "workers"; for "bill", not "invoice"; for "tunch", "memo", "udhaar",
 * "chandi", "bhao". The command palette matches on these and never shows them,
 * so the shop's own words find the screen without the label having to be
 * bilingual.
 */

export interface NavItem {
  to: string;
  label: string;
  /** One line, shown in the command palette under the label. */
  hint: string;
  end?: boolean;
  /** If set, only these roles see the entry. Mirrors app/core/permissions.py. */
  roles?: string[];
  /** What a person might type looking for this. Never shown. */
  keywords?: string[];
}

export interface NavSection {
  /**
   * Also the module key. The sidebar hides a section whose module is switched
   * off — and the server refuses its endpoints regardless, because a control
   * that lives only in the sidebar is not a control.
   */
  id: string;
  label: string;
  /** Shown beside the heading; a shape, not decoration — see `SectionIcon`. */
  icon: string;
  /** Applied to every item in the section, on top of each item's own roles. */
  roles?: string[];
  items: NavItem[];
}

/**
 * The sections, in the order §22 of the UI/UX specification recommends.
 *
 * That ordering is followed rather than improved on. It is close to how the
 * shop already describes itself, and where it differs from what I would have
 * chosen the difference is not worth a system that disagrees with its own
 * written spec.
 *
 * Four of §22's fourteen headings are folded in rather than given a section of
 * their own, on the authority of the spec's own §15 — *do not put dozens of
 * entries in the sidebar*. Each of these would have been a heading holding one
 * link, which costs a person a click to learn nothing:
 *
 * - **Alerts** → the Dashboard. Every alert §22 wants a section for — customer
 *   due, vendor due, maker settlement, setter shortage — is already on the
 *   dashboard, which is where §3.3 puts it. A second screen listing the same
 *   rows would duplicate the first thing you see when you log in.
 * - **Targets** → Sales, beside the salesmen whose targets they are.
 * - **Product Gallery** → Sales. It is a selling tool: you open it to show a
 *   customer a piece, not to count stock.
 * - **Audit Logs** → Settings, and admin-only, as it already was.
 *
 * Everything else follows §22 in its order and its names.
 */
export const SECTIONS: NavSection[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: "home",
    items: [
      {
        to: "/",
        label: "Business overview",
        hint: "Alerts, material outside, and the day's figures",
        end: true,
        keywords: ["home", "dashboard", "overview", "alert", "due", "start", "kpi"],
      },
    ],
  },
  {
    id: "inventory",
    label: "Inventory",
    icon: "box",
    items: [
      {
        to: "/stock",
        label: "What we hold",
        hint: "Gold, silver and stones, each in its own unit",
        keywords: ["stock", "holding", "position", "summary", "total", "safe", "gold", "silver"],
      },
      {
        to: "/inventory",
        label: "Raw materials",
        hint: "Melt pots by purity — gold, silver and stone lots",
        keywords: ["inventory", "raw", "bullion", "melt", "pot", "material", "scrap", "999"],
      },
      {
        to: "/purchasing/stone-stock",
        label: "Diamonds & stones",
        hint: "Parcels by grade, in carats",
        keywords: ["diamond", "stone", "parcel", "carat", "ct", "packet", "grade", "ruby"],
      },
      {
        to: "/products",
        label: "Finished products",
        hint: "Made-up stock, by serial number",
        keywords: ["product", "item", "piece", "jewellery", "serial", "tag", "finished"],
      },
      {
        to: "/reconciliation",
        label: "Reconciliation",
        hint: "What the books say against what is on the scale",
        keywords: [
          "reconcile", "reconciliation", "count", "stock take", "stocktake",
          "physical", "weigh", "variance", "shortage", "difference", "audit",
          "adjustment", "shrinkage",
        ],
      },
      {
        to: "/stock-movements",
        label: "Stock movements",
        hint: "Every in and out, and what caused it",
        keywords: ["movement", "history", "in out", "transaction", "trace", "ledger"],
      },
      {
        to: "/transfers",
        label: "Branch transfers",
        hint: "Stock moving between shops",
        keywords: ["transfer", "branch", "shop", "send", "shift"],
      },
    ],
  },
  {
    id: "manufacturing",
    label: "Manufacturing",
    icon: "hammer",
    items: [
      {
        to: "/designs",
        label: "Jobs",
        hint: "Metal out to the karigar, and what came back",
        keywords: [
          "design", "job", "karigar", "maker", "setter", "stone fixer", "wastage",
          "ratti", "polish", "leg", "issue", "manufacturing",
        ],
      },
      {
        to: "/vendors",
        label: "Makers & stone setters",
        hint: "Who does the work, and on what terms",
        keywords: ["worker", "vendor", "karigar", "maker", "setter", "department", "wastage", "terms"],
      },
      {
        to: "/material-outside",
        label: "Material with others",
        hint: "Everything of ours in somebody else's hands, right now",
        keywords: [
          "outside", "with workers", "with maker", "with setter", "out", "issued",
          "receivable", "shortage", "exposure", "unreturned",
        ],
      },
      {
        to: "/orders",
        label: "Orders & repairs",
        hint: "What a customer has asked for and not yet collected",
        keywords: ["order", "repair", "custom", "farmaish", "job card"],
      },
    ],
  },
  {
    id: "sales",
    label: "Sales",
    icon: "tag",
    items: [
      {
        to: "/invoices",
        label: "Invoices",
        hint: "Finished product and loose material bills",
        keywords: ["bill", "invoice", "sale", "receipt", "cash memo", "loose", "finished"],
      },
      {
        to: "/approvals",
        label: "On approval",
        hint: "Pieces out of the building, and with whom",
        keywords: ["memo", "approval", "on trial", "sale or return", "issued out"],
      },
      {
        to: "/sales",
        label: "Salesmen, brokers & targets",
        hint: "Who sold what, and how the period is tracking",
        keywords: [
          "seller", "salesman", "broker", "commission", "target", "staff",
          "achievement", "progress",
        ],
      },
      {
        to: "/gallery",
        label: "Product gallery",
        hint: "The pieces as photographs, for showing and sending",
        keywords: ["gallery", "photo", "image", "picture", "catalogue", "marketing", "show"],
      },
    ],
  },
  {
    id: "customers",
    label: "Customers",
    icon: "users",
    items: [
      {
        to: "/customers",
        label: "Customers",
        hint: "Profiles, balances and history",
        keywords: ["client", "party", "buyer", "customer", "khata", "profile"],
      },
      {
        to: "/ledger/statement",
        label: "Ledgers & statements",
        hint: "One account, line by line, ready to print",
        keywords: ["statement", "ledger", "account", "history", "udhaar", "balance", "print"],
      },
      {
        to: "/messages",
        label: "Messages",
        hint: "What the shop has told customers, and who is worth telling",
        keywords: ["whatsapp", "sms", "birthday", "anniversary", "greeting", "occasion"],
      },
    ],
  },
  {
    id: "vendors",
    label: "Vendors",
    icon: "cart",
    items: [
      {
        to: "/purchasing/suppliers",
        label: "Suppliers",
        hint: "Dealers you buy from, their bills and what is owed",
        keywords: ["vendor", "dealer", "supplier", "party", "payable", "bill", "due"],
      },
      {
        to: "/purchasing/bills",
        label: "Bills & due dates",
        hint: "What is owed, when it falls due, and paying it",
        keywords: [
          "bill", "due", "due date", "overdue", "payable", "owed", "ageing",
          "aging", "pay", "payment", "outstanding", "credit", "udhaar",
        ],
      },
      {
        to: "/purchasing/gold",
        label: "Gold purchases",
        hint: "A bullion dealer's gold bill",
        keywords: ["bullion", "bar", "tt bar", "biscuit", "24k", "buy gold", "dealer"],
      },
      {
        to: "/purchasing/silver",
        label: "Silver purchases",
        hint: "A dealer's silver bill, by fineness",
        keywords: ["silver", "999", "sterling", "925", "chandi", "fineness", "tunch"],
      },
      {
        to: "/purchasing/old-gold",
        label: "Old gold",
        hint: "Metal bought back over the counter",
        keywords: ["buy back", "scrap", "exchange", "purana", "used", "customer gold"],
      },
      {
        to: "/purchasing/stones",
        label: "Stone purchases",
        hint: "Diamond and colour parcels from a supplier",
        keywords: ["diamond", "stone", "parcel", "buy stones", "import"],
      },
    ],
  },
  {
    id: "finance",
    label: "Finance",
    icon: "coins",
    // The books are owner information — worker metal liabilities and cash
    // positions both. Staff post into the ledger by doing their job; they do
    // not get to read it.
    roles: ["admin", "accountant"],
    items: [
      {
        to: "/overview",
        label: "Business overview",
        hint: "What the shop is worth, and how it is trading",
        keywords: [
          "overview", "net worth", "summary", "owner", "how are we doing",
          "balance sheet", "capital", "worth", "month", "print", "report",
        ],
      },
      {
        to: "/cash",
        label: "Cash & expenses",
        hint: "Money in and out, and where it went",
        keywords: ["cash", "bank", "expense", "petty", "receipt", "payment", "kharcha", "daily"],
      },
      {
        to: "/ledger/position",
        label: "Receivables & payables",
        hint: "Cash, metal, what is owed to you and by you",
        keywords: ["position", "receivable", "payable", "balance sheet", "capital", "owed"],
      },
      {
        to: "/reports/profit",
        label: "Profit & gold capital",
        hint: "Earned by trading, gained or lost by holding",
        keywords: ["profit", "margin", "revaluation", "gold capital", "gain", "loss", "market"],
      },
      {
        to: "/ledger/trade-account",
        label: "Trade accounts",
        hint: "A party's position in metal and money at once",
        keywords: ["party", "account", "worker", "supplier", "khata", "balance"],
      },
      {
        to: "/ledger/journal",
        label: "Journal",
        hint: "Every entry the books have taken",
        keywords: ["journal", "voucher", "entry", "double entry", "posting"],
      },
      {
        to: "/ledger/accounts",
        label: "Chart of accounts",
        hint: "The account tree everything posts into",
        keywords: ["chart", "accounts", "coa", "head", "1130", "account code"],
      },
    ],
  },
  {
    id: "reports",
    label: "Reports",
    icon: "chart",
    items: [
      {
        to: "/reports",
        label: "Reports",
        hint: "Margin, customers, workers, operations",
        keywords: [
          "report", "margin", "profit", "worker", "loss", "export", "csv",
          // The tabs, so the palette finds a report by its own name rather
          // than only by the hub's. Someone looking for "top customers" is
          // not looking for the word "reports".
          "customers", "top spend", "best customer", "operations", "karigar",
          "profitability", "ranking",
        ],
      },
      {
        to: "/insights",
        label: "Insights",
        hint: "Where the money is leaking",
        keywords: ["insight", "analysis", "risk", "karigar risk", "trend"],
      },
      {
        to: "/assistant",
        label: "Assistant",
        hint: "Ask a question of your own data",
        keywords: ["ai", "ask", "chat", "question", "assistant"],
      },
    ],
  },
  {
    id: "rates",
    label: "Market rates",
    icon: "trend",
    items: [
      {
        to: "/live-rates",
        label: "Live gold & silver",
        hint: "Spot, beside the rate you set. Changes nothing on its own.",
        keywords: ["live", "spot", "market", "gold price", "silver price", "goldpricez", "bhao"],
      },
      {
        to: "/gold-rates",
        label: "Rates you set",
        hint: "The rate the shop prices at — this is the one that bills",
        keywords: ["gold rate", "silver rate", "set rate", "daily rate", "bhao", "24k", "22k"],
      },
    ],
  },
  {
    id: "settings",
    label: "Settings",
    icon: "cog",
    // Staff may read these but not change them, so the section is hidden from
    // them rather than showing screens they cannot act on.
    roles: ["admin", "accountant"],
    items: [
      {
        to: "/settings/items",
        label: "Item types",
        hint: "Ring, bangle, taka — what a design can be",
        keywords: ["item", "type", "category", "product type", "bangle", "ring"],
      },
      // Two screens, and the difference matters. `/stones` is the list of
      // stones the shop deals in — "12 PTR", a ruby — each with a default
      // rate. `/settings/stone-attributes` is the option lists those are
      // described *with*: cuts, colours, clarities. Neither holds a quantity,
      // which is why both sit here and not under Inventory, where the first
      // one used to and read as stones the shop owned.
      {
        to: "/stones",
        label: "Stone list",
        hint: "The stones you deal in, and what each is worth per carat",
        keywords: ["stone", "diamond", "ruby", "emerald", "pearl", "rate", "catalogue", "ptr"],
      },
      {
        to: "/settings/stone-attributes",
        label: "Stone grades",
        hint: "The cuts, colours and clarities stones are graded on",
        keywords: ["cut", "colour", "color", "clarity", "grade", "quality", "attribute", "vs1"],
      },
      {
        to: "/settings/branches",
        label: "Branches",
        hint: "The shops, and which is the default",
        keywords: ["branch", "shop", "location", "outlet"],
      },
      {
        to: "/settings/banks",
        label: "Banks",
        hint: "Accounts money moves through",
        keywords: ["bank", "account", "cheque", "transfer"],
      },
      {
        to: "/settings/locations",
        label: "Countries & cities",
        hint: "Address options",
        keywords: ["country", "city", "location", "address"],
      },
      {
        to: "/settings/modules",
        label: "Modules & roles",
        hint: "What this shop uses, and what each role may do",
        // Super admin only. Offering a link that answers 403 is worse than not
        // offering it — but the page itself explains rather than 404s, because
        // an admin who lands here deserves to know the tier exists and why.
        roles: ["superadmin"],
        keywords: [
          "module", "feature", "flag", "enable", "disable", "switch off",
          "rbac", "role", "permission", "access", "who can", "superadmin",
        ],
      },
      {
        to: "/settings/audit-log",
        label: "Audit log",
        hint: "Who did what, and when",
        // A record of colleagues, which answers an owner's question and not a
        // bookkeeper's. Offering a link that returns 403 is worse than not
        // offering it at all.
        roles: ["admin"],
        keywords: ["audit", "log", "history", "who", "trail", "security", "change"],
      },
    ],
  },
];

/**
 * The sections and items this role may actually reach.
 *
 * The super admin is exempt from every gate below, and has to be: it holds the
 * whole permission catalogue, so there is no link here it would be refused on.
 * Without this it fell through the `["admin", "accountant"]` gates on Finance
 * and Settings and lost the sidebar entry for `Modules & roles` — the one
 * screen only it may open. A role that cannot navigate to its own panel is
 * indistinguishable from a role that does not exist.
 */
export function visibleSections(role: string): NavSection[] {
  if (role === "superadmin") return SECTIONS;
  return SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((i) => !i.roles || i.roles.includes(role)),
  })).filter((s) => (!s.roles || s.roles.includes(role)) && s.items.length > 0);
}

/** Flattened, for the command palette. */
export function allItems(role: string): (NavItem & { section: string })[] {
  return visibleSections(role).flatMap((s) =>
    s.items.map((i) => ({ ...i, section: s.label })),
  );
}

/**
 * Which section a path belongs to, so the sidebar can open itself there.
 *
 * Longest match wins. `/purchasing/stone-stock` lives under Stock while
 * `/purchasing/stones` lives under Buy, and a first-prefix-wins scan would put
 * one of them in the wrong group depending only on declaration order.
 */
export function sectionForPath(path: string, role: string): string | null {
  let best: { id: string; len: number } | null = null;
  for (const s of visibleSections(role)) {
    for (const i of s.items) {
      const hit = i.end ? path === i.to : path === i.to || path.startsWith(i.to + "/");
      if (hit && (!best || i.to.length > best.len)) best = { id: s.id, len: i.to.length };
    }
  }
  return best?.id ?? null;
}
