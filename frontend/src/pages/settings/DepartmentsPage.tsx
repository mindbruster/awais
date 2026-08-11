import { MasterTable } from "@/components/MasterTable";

export function DepartmentsPage() {
  return (
    <MasterTable
      title="Departments"
      description="The stages a piece passes through on the workshop floor. Order them the way work actually flows; a piece can still revisit a stage or skip one."
      endpoint="/departments"
      noun="department"
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
