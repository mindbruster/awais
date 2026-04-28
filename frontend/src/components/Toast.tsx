import { create } from "zustand";

interface Toast {
  id: number;
  kind: "success" | "error" | "info";
  msg: string;
}

interface ToastState {
  toasts: Toast[];
  push: (t: Omit<Toast, "id">) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (t) => {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), 4000);
  },
  dismiss: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export function toast(kind: Toast["kind"], msg: string) {
  useToastStore.getState().push({ kind, msg });
}

export function ToastViewport() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);
  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[60] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          onClick={() => dismiss(t.id)}
          className={`pointer-events-auto cursor-pointer rounded-lg px-4 py-2 text-sm shadow-lg ring-1 ${
            t.kind === "success"
              ? "bg-emerald-50 text-emerald-900 ring-emerald-200"
              : t.kind === "error"
              ? "bg-red-50 text-red-900 ring-red-200"
              : "bg-slate-50 text-slate-900 ring-slate-200"
          }`}
        >
          {t.msg}
        </div>
      ))}
    </div>
  );
}
