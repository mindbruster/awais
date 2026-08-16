import { MasterTable } from "@/components/MasterTable";

// Setting agrees its allowance per hundred stones, everyone else as a
// percentage of the weight issued. The two are not interchangeable, so the
// stage says which one it works on rather than the job card guessing.
const WASTAGE_BASES = [
  { value: "percent_of_issued", label: "Percent of gold issued" },
  { value: "per_100_pieces", label: "Grams per 100 pieces" },
];

export function DepartmentsPage() {
  return (
    <MasterTable
      title="Stages and their terms"
      description="The stages a piece passes through, and the wastage and labour each one is agreed on. A worker inherits the terms of the stage he handles unless he has his own."
      endpoint="/departments"
      noun="stage"
      searchPlaceholder="Search by name or code…"
      fields={[
        { key: "name", label: "Name", required: true, half: true },
        {
          key: "code",
          label: "Code",
          required: true,
          half: true,
          hint: "Short label for job cards and reports",
        },
        {
          key: "sequence",
          label: "Order",
          type: "number",
          half: true,
          hint: "Lower runs earlier",
        },
        {
          key: "default_wastage_pct",
          label: "Default wastage %",
          type: "number",
          step: "0.001",
          half: true,
          hint: "Allowance for this stage; a worker's own rate overrides it",
          render: (r) =>
            r.default_wastage_pct === null ? "—" : `${Number(r.default_wastage_pct)}%`,
        },
        {
          key: "default_wastage_basis",
          label: "Wastage basis",
          type: "select",
          options: WASTAGE_BASES,
          hint: "The stone fixer works per 100 stones; the maker on a percentage",
          render: (r) =>
            WASTAGE_BASES.find((b) => b.value === r.default_wastage_basis)?.label ??
            String(r.default_wastage_basis ?? "—"),
        },
        {
          key: "default_wastage_per_100_pcs_g",
          label: "Waste per 100 pcs (g)",
          type: "number",
          step: "0.0001",
          half: true,
          hint: "Only used on the per-100 basis — e.g. 0.400g per 100 stones",
          render: (r) =>
            r.default_wastage_per_100_pcs_g === null
              ? "—"
              : `${Number(r.default_wastage_per_100_pcs_g)} g/100`,
        },
        {
          key: "default_rate_per_piece",
          label: "Rate per piece",
          type: "number",
          step: "0.01",
          half: true,
          hint: "Rs a stone set, or a lacquered item — pre-fills the issue form",
          render: (r) =>
            r.default_rate_per_piece === null ? "—" : `₨ ${Number(r.default_rate_per_piece)}`,
        },
        {
          key: "consumes_stones",
          label: "Consumes stones",
          type: "checkbox",
          hint: "Setting is normally the only one",
        },
        { key: "is_active", label: "Active", type: "checkbox" },
        { key: "notes", label: "Notes", type: "textarea", hideInTable: true },
      ]}
    />
  );
}
