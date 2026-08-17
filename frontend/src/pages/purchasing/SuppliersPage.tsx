import { Link } from "react-router-dom";
import { MasterTable } from "@/components/MasterTable";

/**
 * The parties the shop buys from.
 *
 * The records have existed since purchasing was built, and there was no screen:
 * every purchase form offered a dropdown of suppliers with no way to add one,
 * so a shop starting fresh could not raise its first gold or stone purchase at
 * all. The API was complete; only the door was missing.
 *
 * Deliberately separate from Workers. A karigar is given the shop's metal to
 * transform and owes it back as pieces; a supplier sells the shop material and
 * is owed money for it. The two carry different balances that settle in
 * different units, and merging them into one "parties" list would put a gram
 * figure and a rupee figure in the same column.
 */
export function SuppliersPage() {
  return (
    <MasterTable
      title="Suppliers"
      description="Who the shop buys bullion and stones from. Purchases are raised against these, and what is owed to each shows on the supplier account."
      endpoint="/purchasing/suppliers"
      noun="supplier"
      searchPlaceholder="Search by name or phone…"
      fields={[
        {
          key: "name",
          label: "Name",
          required: true,
          half: true,
          // The name is the way through to what they have sold the shop and
          // what is owed. Without it this list is where the trail ends.
          render: (row) => (
            <Link
              to={`/purchasing/suppliers/${row.id}`}
              className="font-medium text-brand-700 hover:underline"
            >
              {row.name}
            </Link>
          ),
        },
        { key: "phone", label: "Phone", half: true },
        {
          key: "opening_balance",
          label: "Opening balance",
          type: "number",
          half: true,
          hint: "What was already owed to them when the shop started on this system",
        },
        { key: "is_active", label: "Active", type: "checkbox", half: true },
        { key: "address", label: "Address", type: "textarea", hideInTable: true },
        { key: "notes", label: "Notes", type: "textarea", hideInTable: true },
      ]}
    />
  );
}
