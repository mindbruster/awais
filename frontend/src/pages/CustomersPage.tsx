import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextField, TextArea } from "@/components/Field";
import { SearchBox, Toolbar } from "@/components/Toolbar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

interface Customer {
  id: number;
  name: string;
  is_trade: boolean;
  account_no: string | null;
  phone: string | null;
  phone2: string | null;
  email: string | null;
  cnic: string | null;
  address: string | null;
  reference: string | null;
  date_of_birth: string | null;
  anniversary: string | null;
  city_id: number | null;
  country_id: number | null;
  city_name: string | null;
  country_name: string | null;
  opening_balance: string;
  notes: string | null;
}

interface NamedRow {
  id: number;
  name: string;
}

export function CustomersPage() {
  const [items, setItems] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [deleting, setDeleting] = useState<Customer | null>(null);
  const [busyDelete, setBusyDelete] = useState(false);
  const [q, setQ] = useState("");

  const load = () => {
    setLoading(true);
    api
      .get<Customer[]>("/customers", { params: q ? { q } : {} })
      .then((res) => setItems(res.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q]);

  const confirmDelete = async () => {
    if (!deleting) return;
    setBusyDelete(true);
    try {
      await api.delete(`/customers/${deleting.id}`);
      toast("success", `Deleted ${deleting.name}`);
      setDeleting(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Delete failed"));
    } finally {
      setBusyDelete(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Customers</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          New customer
        </button>
      </div>
      <Toolbar>
        <SearchBox value={q} onChange={setQ} placeholder="Search by name, phone, email…" className="w-72" />
        <span className="ml-auto text-xs text-slate-500">{items.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {q ? `No customers matching "${q}".` : "No customers yet."}
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Address</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium">
                    <Link to={`/customers/${c.id}`} className="text-brand-700 hover:underline">
                      {c.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{c.phone ?? "—"}</td>
                  <td className="px-4 py-3">{c.email ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-500">{c.address ?? "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        className="text-xs text-brand-700 hover:underline"
                        onClick={() => setEditing(c)}
                      >
                        Edit
                      </button>
                      <button
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => setDeleting(c)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <CustomerForm
        open={open}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          load();
        }}
      />
      <CustomerForm
        open={!!editing}
        existing={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          load();
        }}
      />
      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.name ?? "customer"}?`}
        description="Customers linked to existing invoices cannot be deleted (the FK is RESTRICT)."
        destructive
        confirmLabel="Delete"
        busy={busyDelete}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function CustomerForm({
  open,
  onClose,
  onSaved,
  existing,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  existing?: Customer | null;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [accountNo, setAccountNo] = useState("");
  const [isTrade, setIsTrade] = useState(false);
  const [phone2, setPhone2] = useState("");
  const [email, setEmail] = useState("");
  const [cnic, setCnic] = useState("");
  const [address, setAddress] = useState("");
  const [reference, setReference] = useState("");
  const [dob, setDob] = useState("");
  const [anniversary, setAnniversary] = useState("");
  const [countryId, setCountryId] = useState("");
  const [cityId, setCityId] = useState("");
  const [openingBalance, setOpeningBalance] = useState("");
  const [notes, setNotes] = useState("");
  const [countries, setCountries] = useState<NamedRow[]>([]);
  const [cities, setCities] = useState<NamedRow[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setName(existing?.name ?? "");
      setPhone(existing?.phone ?? "");
      setAccountNo(existing?.account_no ?? "");
      setIsTrade(existing?.is_trade ?? false);
      setPhone2(existing?.phone2 ?? "");
      setEmail(existing?.email ?? "");
      setCnic(existing?.cnic ?? "");
      setAddress(existing?.address ?? "");
      setReference(existing?.reference ?? "");
      setDob(existing?.date_of_birth ?? "");
      setAnniversary(existing?.anniversary ?? "");
      setCountryId(existing?.country_id ? String(existing.country_id) : "");
      setCityId(existing?.city_id ? String(existing.city_id) : "");
      setOpeningBalance(existing?.opening_balance ?? "");
      setNotes(existing?.notes ?? "");
      api
        .get<NamedRow[]>("/countries", { params: { limit: "500", is_active: "true" } })
        .then((r) => setCountries(r.data))
        .catch(() => setCountries([]));
      api
        .get<NamedRow[]>("/cities", { params: { limit: "500", is_active: "true" } })
        .then((r) => setCities(r.data))
        .catch(() => setCities([]));
    }
  }, [open, existing]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body = {
        name,
        is_trade: isTrade,
        account_no: accountNo || null,
        phone: phone || null,
        phone2: phone2 || null,
        email: email || null,
        cnic: cnic || null,
        address: address || null,
        reference: reference || null,
        date_of_birth: dob || null,
        anniversary: anniversary || null,
        country_id: countryId ? Number(countryId) : null,
        city_id: cityId ? Number(cityId) : null,
        opening_balance: openingBalance || "0",
        notes: notes || null,
      };
      if (existing) {
        await api.patch(`/customers/${existing.id}`, body);
        toast("success", `"${name}" updated`);
      } else {
        await api.post("/customers", body);
        toast("success", `Customer "${name}" created`);
      }
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not save customer"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={existing ? "Edit customer" : "New customer"}>
      <form onSubmit={submit} className="space-y-4">
        <TextField
          label="Name"
          required
          hint="The only required field — capture the rest when the customer offers it"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {/* The single most consequential field on this form: it decides the
            shape of every bill this customer is ever given. Set out on its own
            with the consequence spelled out, rather than buried in the grid as
            one more optional detail. */}
        <label className="flex cursor-pointer items-start gap-3 rounded border border-slate-200 bg-slate-50 p-3">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4"
            checked={isTrade}
            onChange={(e) => setIsTrade(e.target.checked)}
          />
          <span className="text-sm">
            <span className="font-medium text-slate-900">This is a jeweller, not a counter customer</span>
            <span className="mt-0.5 block text-slate-500">
              Their bills settle the gold in metal: the invoice states the fine grams to hand over
              and never prices them, and cash is charged only for stones and making. Leave this off
              and they are billed in rupees for everything.
            </span>
          </span>
        </label>
        <div className="grid grid-cols-2 gap-3">
          {/* The shop's own ledger number for this account. Prints on their
              bills, so trade customers get one and walk-ins do not. */}
          <TextField
            label="Account no"
            hint="Printed on this customer's bills"
            value={accountNo}
            onChange={(e) => setAccountNo(e.target.value)}
          />
          <TextField label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
          <TextField
            label="Second phone"
            value={phone2}
            onChange={(e) => setPhone2(e.target.value)}
          />
          <TextField
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <TextField
            label="CNIC"
            value={cnic}
            onChange={(e) => setCnic(e.target.value)}
            placeholder="42101-1234567-1"
          />
          <SelectField
            label="Country"
            options={[
              { value: "", label: "—" },
              ...countries.map((c) => ({ value: c.id, label: c.name })),
            ]}
            value={countryId}
            onChange={(e) => setCountryId(e.target.value)}
          />
          <SelectField
            label="City"
            options={[
              { value: "", label: "—" },
              ...cities.map((c) => ({ value: c.id, label: c.name })),
            ]}
            value={cityId}
            onChange={(e) => setCityId(e.target.value)}
          />
          <TextField
            label="Date of birth"
            type="date"
            value={dob}
            onChange={(e) => setDob(e.target.value)}
          />
          <TextField
            label="Anniversary"
            type="date"
            value={anniversary}
            onChange={(e) => setAnniversary(e.target.value)}
          />
          <TextField
            label="Reference"
            hint="Who introduced them"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
          />
          <TextField
            label="Opening balance"
            type="number"
            step="0.01"
            hint="Positive = customer owes the shop"
            value={openingBalance}
            onChange={(e) => setOpeningBalance(e.target.value)}
          />
        </div>
        <TextArea label="Address" value={address} onChange={(e) => setAddress(e.target.value)} />
        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting || !name}>
            {submitting ? "Saving…" : existing ? "Save changes" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
