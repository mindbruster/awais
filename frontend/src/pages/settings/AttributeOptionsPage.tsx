import { useState } from "react";
import { MasterTable } from "@/components/MasterTable";
import { FilterSelect } from "@/components/Toolbar";

const KINDS = [
  { value: "cut", label: "Cut" },
  { value: "color", label: "Colour" },
  { value: "clarity", label: "Clarity" },
  { value: "quality", label: "Quality" },
];

export function AttributeOptionsPage() {
  const [kind, setKind] = useState("");

  return (
    <MasterTable
      title="Stone attributes"
      description="The cut, colour, clarity and quality grades offered when recording a stone. Holding them as a list keeps entry consistent — otherwise VS1, vs1 and “VS 1” all end up in the books and nothing groups cleanly."
      endpoint="/attribute-options"
      noun="option"
      labelKey="value"
      searchPlaceholder="Search values…"
      params={kind ? { kind } : undefined}
      toolbarExtra={
        <FilterSelect value={kind} onChange={setKind} options={KINDS} allLabel="All kinds" />
      }
      fields={[
        {
          key: "kind",
          label: "Kind",
          type: "select",
          required: true,
          half: true,
          options: KINDS,
          render: (r) => (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs capitalize">
              {r.kind}
            </span>
          ),
        },
        { key: "value", label: "Value", required: true, half: true },
        {
          key: "sort_order",
          label: "Order",
          type: "number",
          half: true,
          hint: "Controls dropdown order",
        },
        { key: "is_active", label: "Active", type: "checkbox", half: true },
      ]}
    />
  );
}
