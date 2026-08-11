import { MasterTable } from "@/components/MasterTable";

export function ItemsPage() {
  return (
    <MasterTable
      title="Items"
      description="The kinds of piece the shop makes. The abbreviation becomes the prefix of every design number — taka with abbreviation TK produces TK-00001 — so keep it short and don't reuse one."
      endpoint="/items"
      noun="item"
      searchPlaceholder="Search by name, code or category…"
      fields={[
        { key: "name", label: "Name", required: true, half: true },
        {
          key: "abbreviation",
          label: "Abbreviation",
          required: true,
          half: true,
          placeholder: "TK",
          hint: "Letters and numbers only; used in design numbers",
        },
        { key: "category", label: "Category", half: true },
        { key: "is_active", label: "Active", type: "checkbox", half: true },
        { key: "notes", label: "Notes", type: "textarea", hideInTable: true },
      ]}
    />
  );
}
