import { FormEvent, ReactNode, useState } from "react";
import { Modal } from "@/components/Modal";
import { TextField } from "@/components/Field";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  description: string;
  onConfirm: (password: string) => Promise<void>;
  confirmLabel?: string;
  destructive?: boolean;
  /**
   * Extra fields rendered above the password prompt. The caller owns their
   * state and reads it inside `onConfirm` — used where confirming an action
   * also requires recording what happened (e.g. settling material on a
   * cancelled job).
   */
  extra?: ReactNode;
  /** Blocks the confirm button while the caller's own fields are incomplete. */
  extraValid?: boolean;
}

export function PasswordConfirm({
  open,
  onClose,
  title,
  description,
  onConfirm,
  confirmLabel = "Confirm",
  destructive = true,
  extra,
  extraValid = true,
}: Props) {
  const [pwd, setPwd] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await onConfirm(pwd);
      setPwd("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={title}>
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-600">{description}</p>
        {extra}
        <TextField
          label="Re-enter your password"
          type="password"
          required
          value={pwd}
          onChange={(e) => setPwd(e.target.value)}
          autoFocus
        />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !pwd || !extraValid}
            className={
              destructive
                ? "inline-flex items-center justify-center rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                : "btn-primary"
            }
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}
