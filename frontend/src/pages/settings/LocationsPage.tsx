import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { MasterTable } from "@/components/MasterTable";

interface Country {
  id: number;
  name: string;
}

/**
 * Countries and cities on one screen — cities are meaningless without their
 * country, and the shop sets both up in a single sitting.
 */
export function LocationsPage() {
  const [countries, setCountries] = useState<Country[]>([]);
  const [tab, setTab] = useState<"countries" | "cities">("countries");
  const [refresh, setRefresh] = useState(0);

  const loadCountries = () => {
    api
      .get<Country[]>("/countries", { params: { limit: "500" } })
      .then((res) => setCountries(res.data))
      .catch(() => setCountries([]));
  };

  useEffect(loadCountries, [refresh]);

  return (
    <div>
      <div className="mb-5 flex gap-1 border-b border-slate-200">
        {(["countries", "cities"] as const).map((t) => (
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

      {tab === "countries" ? (
        <MasterTable
          title="Countries"
          description="Countries customers are billed from. Overseas buyers are common enough here that country is a reporting dimension, not just an address line."
          endpoint="/countries"
          noun="country"
          searchPlaceholder="Search countries…"
          onChanged={() => setRefresh((n) => n + 1)}
          fields={[
            { key: "name", label: "Name", required: true, half: true },
            { key: "iso_code", label: "ISO code", half: true, placeholder: "PK" },
            { key: "is_active", label: "Active", type: "checkbox" },
          ]}
        />
      ) : (
        <MasterTable
          title="Cities"
          description="Cities within a country. The same name can exist under two countries — Hyderabad is both Pakistani and Indian — so each is recorded against its own."
          endpoint="/cities"
          noun="city"
          searchPlaceholder="Search cities…"
          refreshKey={refresh}
          fields={[
            { key: "name", label: "Name", required: true, half: true },
            {
              key: "country_id",
              label: "Country",
              type: "select",
              required: true,
              half: true,
              options: countries.map((c) => ({ value: c.id, label: c.name })),
              hideInTable: true,
            },
            { key: "country_name", label: "Country", hideInForm: true },
            { key: "is_active", label: "Active", type: "checkbox" },
          ]}
        />
      )}
    </div>
  );
}
