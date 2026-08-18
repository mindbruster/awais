/**
 * The pieces, as pictures.
 *
 * A jeweller recognises stock by looking at it. Everywhere else in this system
 * a product is a row — serial, weight, price — which is the right shape for
 * counting and the wrong one for choosing what to show a customer or send to a
 * wholesaler.
 *
 * Each tile carries what the piece is *made of* rather than what it costs:
 * gold weight, purity, carats. That is the marketing question — "how much gold
 * and how much diamond" — and it is also the one figure a photograph cannot
 * convey on its own. Price is deliberately not on the tile: a picture wall is
 * shown to people who should be told a price by a person.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Img } from "@/components/Img";
import { SearchBox, Toolbar } from "@/components/Toolbar";
import { apiError } from "@/lib/api-error";

interface Product {
  id: number;
  serial_no: string | null;
  name: string;
  gold_weight_g: string;
  gold_purity: number | null;
  stone_weight_ct: string;
  image_url: string | null;
  status: string;
}

const wt = (v: string, unit: string) =>
  `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit}`;

export function GalleryPage() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  // Pieces without a photograph are the point of the toggle: the gallery is
  // also the list of what still needs shooting, and hiding them would hide the
  // work.
  const [onlyPhotographed, setOnlyPhotographed] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params: Record<string, string | number> = { limit: 200 };
    if (q) params.q = q;
    api
      .get<Product[]>("/products", { params })
      .then((r) => setItems(r.data))
      .catch((e) => setError(apiError(e, "Could not load the gallery")))
      .finally(() => setLoading(false));
  }, [q]);

  const shown = onlyPhotographed ? items.filter((p) => p.image_url) : items;
  const missing = items.length - items.filter((p) => p.image_url).length;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Gallery</h1>
        <span className="text-xs text-slate-500">{shown.length} shown</span>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Every piece as a picture, with what it is made of. Click one to open it.
      </p>

      <Toolbar>
        <SearchBox value={q} onChange={setQ} placeholder="Search name or serial…" className="w-72" />
        <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={onlyPhotographed}
            onChange={(e) => setOnlyPhotographed(e.target.checked)}
          />
          Only pieces with a photograph
        </label>
        {missing > 0 && (
          <span className="ml-auto text-xs text-amber-700">
            {missing} piece{missing === 1 ? "" : "s"} with no photograph
          </span>
        )}
      </Toolbar>

      {loading && <p className="mt-6 text-sm text-slate-500">Loading…</p>}
      {error && <p className="mt-6 text-sm text-red-600">{error}</p>}
      {!loading && !error && shown.length === 0 && (
        <p className="mt-6 text-sm text-slate-500">
          {onlyPhotographed
            ? "No pieces have a photograph yet. Upload one from a product's page."
            : "No pieces match."}
        </p>
      )}

      <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {shown.map((p) => (
          <Link
            key={p.id}
            to={`/products/${p.id}`}
            className="group overflow-hidden rounded-xl border border-slate-200 bg-white transition hover:shadow-md"
          >
            <div className="aspect-square w-full overflow-hidden bg-slate-100">
              {p.image_url ? (
                <Img
                  src={p.image_url}
                  alt={p.name}
                  className="h-full w-full object-cover transition group-hover:scale-105"
                  fallbackClassName="flex h-full w-full items-center justify-center bg-slate-100 text-xs text-slate-400"
                  fallback="photograph missing"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">
                  no photograph
                </div>
              )}
            </div>
            <div className="p-3">
              <p className="truncate text-sm font-medium text-slate-900">{p.name}</p>
              {p.serial_no && (
                <p className="num truncate text-[11px] text-slate-500">{p.serial_no}</p>
              )}
              {/* What it is made of, which is the marketing question and the one
                  thing the photograph cannot say. */}
              <p className="num mt-1.5 text-[11px] leading-snug text-slate-600">
                {Number(p.gold_weight_g) > 0 && (
                  <>
                    {wt(p.gold_weight_g, "g")}
                    {p.gold_purity ? ` · ${p.gold_purity}k` : ""}
                  </>
                )}
                {Number(p.gold_weight_g) > 0 && Number(p.stone_weight_ct) > 0 && " · "}
                {Number(p.stone_weight_ct) > 0 && wt(p.stone_weight_ct, "ct")}
                {!Number(p.gold_weight_g) && !Number(p.stone_weight_ct) && "no weights recorded"}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
