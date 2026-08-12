import { FormEvent, useState } from "react";
import { AxiosError } from "axios";

import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { TextArea } from "@/components/Field";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { staticUrl } from "@/lib/url";

/**
 * Draw a proposal for a piece, optionally from photographs of others.
 *
 * The two-step shape — draw, look, then decide whether to attach — is the point
 * rather than an extra click. A generated picture is an illustration; the image
 * already on a finished product may be a photograph of the actual article. One
 * should never quietly replace the other, so attaching is always a separate,
 * deliberate act.
 */

const MAX_REFERENCES = 4;

interface Result {
  image_url: string;
  model: string;
  attached: boolean;
  references_used: number;
}

export function ImageStudio({
  productId,
  productName,
  open,
  onClose,
  onAttached,
}: {
  productId: number;
  productName: string;
  open: boolean;
  onClose: () => void;
  onAttached: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [refs, setRefs] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setupNote, setSetupNote] = useState<string | null>(null);

  const reset = () => {
    setPrompt("");
    setRefs([]);
    setResult(null);
    setError(null);
    setSetupNote(null);
  };

  const run = async (attach: boolean) => {
    if (!prompt.trim()) return;
    setBusy(true);
    setError(null);
    setSetupNote(null);
    try {
      const fd = new FormData();
      fd.append("prompt", prompt.trim());
      fd.append("attach", String(attach));
      refs.forEach((f) => fd.append("references", f));
      const { data } = await api.post<Result>(`/products/${productId}/image/generate`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(data);
      if (data.attached) {
        toast("success", "Image attached to the piece");
        onAttached();
      }
    } catch (err) {
      if (err instanceof AxiosError && err.response?.status === 503) {
        setSetupNote(apiError(err, "Image generation is not configured."));
      } else {
        setError(apiError(err, "Could not generate an image."));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title={`Draw a proposal — ${productName}`}
    >
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          run(false);
        }}
        className="space-y-4"
      >
        <TextArea
          label="Describe the piece"
          required
          rows={3}
          placeholder="e.g. a 22k gold taka pendant, floral pattern, small round diamonds around the border"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />

        <div>
          <label className="block text-sm font-medium text-slate-700">
            Reference photographs <span className="font-normal text-slate-400">(optional)</span>
          </label>
          <p className="mt-1 text-xs text-slate-500">
            Up to {MAX_REFERENCES}. The drawing follows their style, proportion and finish —
            useful when a customer points at pieces in the tray.
          </p>
          <input
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="mt-2 block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm"
            onChange={(e) => setRefs(Array.from(e.target.files ?? []).slice(0, MAX_REFERENCES))}
          />
          {refs.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              {refs.length} attached: {refs.map((f) => f.name).join(", ")}
            </p>
          )}
        </div>

        {setupNote && (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            {setupNote}
          </div>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {result && (
          <div className="space-y-2 rounded-lg border border-slate-200 p-3">
            <img
              src={staticUrl(result.image_url)}
              alt="Generated proposal"
              className="aspect-square w-full rounded-md object-cover"
            />
            <p className="text-xs text-slate-500">
              Drawn by {result.model}
              {result.references_used > 0 && ` from ${result.references_used} reference(s)`}.
              {result.attached ? " Attached to this piece." : " Not attached yet."}
            </p>
            <div className="flex gap-2">
              {/* A plain link with `download`, not a fetch: the file is already
                  stored and served, so there is nothing to re-fetch. */}
              <a className="btn-ghost text-sm" href={staticUrl(result.image_url)} download>
                Download
              </a>
              {!result.attached && (
                <button
                  type="button"
                  className="btn-ghost text-sm"
                  disabled={busy}
                  onClick={() => run(true)}
                >
                  Use as the piece's image
                </button>
              )}
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-slate-200 pt-3">
          <button type="button" className="btn-ghost" onClick={reset} disabled={busy}>
            Clear
          </button>
          <button type="submit" className="btn-primary" disabled={busy || !prompt.trim()}>
            {busy ? "Drawing…" : result ? "Draw another" : "Draw"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
