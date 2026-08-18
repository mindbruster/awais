/**
 * The shops the business trades from.
 *
 * Reference data in shape, but not in consequence: promoting a branch to
 * default changes where every unscoped row lands, and closing one is refused
 * while it still holds stock. Both are spelled out on screen rather than left
 * for the API to reject after the fact — and the holdings column is here so
 * that "close this branch" is never a decision made blind.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import { MasterTable, MasterRow } from "@/components/MasterTable";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtWeight } from "@/lib/money";
import { Img } from "@/components/Img";

interface BranchStock {
  branch_id: number;
  products_in_stock: number;
  gold_g: string;
  stone_ct: string;
}

interface Named {
  id: number;
  name: string;
}

interface BranchBrand {
  id: number;
  name: string;
  print_name: string;
  logo_url: string | null;
}

export function BranchesPage() {
  const [stock, setStock] = useState<Record<number, BranchStock>>({});
  const [cities, setCities] = useState<Named[]>([]);
  const [brands, setBrands] = useState<BranchBrand[]>([]);

  const loadStock = useCallback(() => {
    api
      .get<BranchStock[]>("/branches/stock")
      .then((r) =>
        setStock(Object.fromEntries(r.data.map((s) => [s.branch_id, s]))),
      )
      .catch(() => setStock({}));
  }, []);

  const loadBrands = useCallback(() => {
    api
      .get<BranchBrand[]>("/branches", { params: { limit: 200 } })
      .then((r) => setBrands(r.data))
      .catch(() => setBrands([]));
  }, []);

  const refresh = useCallback(() => {
    loadStock();
    loadBrands();
  }, [loadStock, loadBrands]);

  useEffect(() => {
    refresh();
    api
      .get<Named[]>("/cities", { params: { is_active: true, limit: 500 } })
      .then((r) => setCities(r.data))
      .catch(() => setCities([]));
  }, [refresh]);

  const holding = (row: MasterRow) => {
    const s = stock[row.id];
    if (!s) return <span className="text-slate-400">—</span>;
    const empty = !s.products_in_stock && Number(s.gold_g) === 0 && Number(s.stone_ct) === 0;
    if (empty) return <span className="text-xs text-slate-400">nothing</span>;
    return (
      <span className="num text-xs text-slate-600">
        {s.products_in_stock > 0 && <>{s.products_in_stock} pcs</>}
        {Number(s.gold_g) > 0 && (
          <>
            {s.products_in_stock > 0 ? " · " : ""}
            {fmtWeight(s.gold_g)} g
          </>
        )}
        {Number(s.stone_ct) > 0 && <> · {fmtWeight(s.stone_ct)} ct</>}
      </span>
    );
  };

  return (
    <div className="space-y-8">
    <MasterTable
      title="Branches"
      description="Every shop the business trades from. Stock, sales and staff all belong to one — the branch marked default is where anything recorded without a branch of its own will land, so there is always exactly one."
      endpoint="/branches"
      noun="branch"
      searchPlaceholder="Search by name or code…"
      fields={[
        {
          key: "code",
          label: "Code",
          required: true,
          half: true,
          placeholder: "MAIN",
          hint: "Short — it prints on labels and prefixes transfer numbers",
        },
        { key: "name", label: "Name", required: true, half: true },
        { key: "phone", label: "Phone", half: true },
        {
          key: "city_id",
          label: "City",
          type: "select",
          half: true,
          options: [
            { value: "", label: "—" },
            ...cities.map((c) => ({ value: c.id, label: c.name })),
          ],
          hideInTable: true,
        },
        {
          key: "holding",
          label: "Holding",
          hideInForm: true,
          render: holding,
        },
        {
          key: "is_default",
          label: "Default",
          type: "checkbox",
          half: true,
          initial: false,
          hint: "Where anything recorded without a branch lands",
          render: (row) =>
            row.is_default ? (
              <span className="chip-gold">Default</span>
            ) : (
              <span className="text-xs text-slate-400">—</span>
            ),
        },
        {
          key: "is_active",
          label: "Open",
          type: "checkbox",
          half: true,
          render: (row) =>
            row.is_active ? (
              <span className="chip-back">Open</span>
            ) : (
              <span className="chip-dead">Closed</span>
            ),
        },
        {
          key: "letterhead_name",
          label: "Name on printed bills",
          hideInTable: true,
          placeholder: "MARKAZ-E-HEERA",
          hint: "What the shop trades as. Blank prints the name above.",
        },
        {
          key: "tagline",
          label: "Line under the name",
          hideInTable: true,
          placeholder: "DIAMOND JEWELLERY & WATCHES",
        },
        { key: "address", label: "Address", type: "textarea", hideInTable: true },
        { key: "notes", label: "Notes", type: "textarea", hideInTable: true },
      ]}
      onChanged={refresh}
    />

      <section className="card">
        <h2 className="text-sm font-semibold uppercase text-slate-700">Letterhead</h2>
        <p className="mt-1 text-sm text-slate-500">
          The customer's copy of a bill is the only thing this system prints that leaves the shop.
          This is what goes at the top of it.
        </p>
        <div className="mt-3">
          {brands.map((b) => (
            <BranchLogo
              key={b.id}
              branch={{ id: b.id, name: b.print_name || b.name, logo_url: b.logo_url }}
              onChanged={loadBrands}
            />
          ))}
          {brands.length === 0 && (
            <p className="py-3 text-sm text-slate-400">No branches yet.</p>
          )}
        </div>
      </section>
    </div>
  );
}

/**
 * The mark at the top of the shop's bills.
 *
 * Separate from the branch form because it is a file, not a field, and because
 * it is worth seeing: a logo is judged by how it looks on the page, so the page
 * shows it at the size it will print.
 */
export function BranchLogo({
  branch,
  onChanged,
}: {
  branch: { id: number; name: string; logo_url: string | null };
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      await api.post(`/branches/${branch.id}/logo`, body);
      toast("success", "Logo updated");
      onChanged();
    } catch (err) {
      toast("error", apiError(err, "Could not upload the logo"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-4 border-b border-slate-100 py-3 last:border-0">
      <div className="flex h-16 w-16 flex-none items-center justify-center border border-slate-200 bg-white">
        {branch.logo_url ? (
          <Img
            src={branch.logo_url}
            alt=""
            className="max-h-14 max-w-14 object-contain"
            fallbackClassName="text-[10px] text-slate-400"
            fallback="logo missing"
          />
        ) : (
          <span className="text-[10px] text-slate-400">no logo</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-900">{branch.name}</div>
        <div className="text-xs text-slate-500">
          Prints at the top-left of every bill from this shop. PNG or JPG, square works best.
        </div>
      </div>
      <label className="btn-outline cursor-pointer whitespace-nowrap">
        {busy ? "Uploading…" : branch.logo_url ? "Replace" : "Upload"}
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            // Cleared so choosing the same file twice still fires a change.
            e.target.value = "";
            if (file) void upload(file);
          }}
        />
      </label>
    </div>
  );
}
