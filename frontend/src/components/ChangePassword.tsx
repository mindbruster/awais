import { FormEvent, useState } from "react";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { Modal } from "@/components/Modal";
import { TextField } from "@/components/Field";
import { toast } from "@/components/Toast";

/**
 * Change your own password.
 *
 * Lives beside "Sign out" in the sidebar rather than on a settings screen,
 * because every role needs it and most roles cannot open Settings at all. A
 * salesman who thinks somebody watched them type should not have to ask the
 * owner to change it for them — that means saying the new password out loud.
 */
export function ChangePassword({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);

  const close = () => {
    setCurrent("");
    setNext("");
    setAgain("");
    onClose();
  };

  // Checked here as well as by the server so the mistake is caught before the
  // round trip — the server does not see this field at all, since "typed it
  // twice the same" is a question about the form, not about the account.
  const mismatch = again.length > 0 && next !== again;
  const valid = current.length > 0 && next.length >= 6 && next === again;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      toast("success", "Password changed. It applies the next time you sign in.");
      close();
    } catch (err) {
      toast("error", apiError(err, "Could not change your password"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={close} title="Change your password" widthClass="max-w-md">
      <form onSubmit={submit} className="space-y-3">
        <TextField
          label="Current password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          required
        />
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          hint="At least 6 characters."
          required
        />
        <TextField
          label="New password again"
          type="password"
          autoComplete="new-password"
          value={again}
          onChange={(e) => setAgain(e.target.value)}
          error={mismatch ? "These two do not match." : undefined}
          required
        />
        <p className="text-xs leading-relaxed text-slate-500">
          Your session stays signed in. Anyone else signed in as you keeps working
          until their session ends — if you are changing this because somebody
          knows it, sign out everywhere you are signed in.
        </p>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn-ghost" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={!valid || busy}>
            {busy ? "Changing…" : "Change password"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
