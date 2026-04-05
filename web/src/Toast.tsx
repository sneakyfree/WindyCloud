import { AlertTriangle, X } from "lucide-react";
import { useEffect, useState } from "react";

interface Toast {
  id: number;
  message: string;
  type: "error" | "success";
}

let _toastId = 0;
let _addToast: ((t: Toast) => void) | null = null;

export function showToast(message: string, type: "error" | "success" = "error") {
  _addToast?.({ id: ++_toastId, message, type });
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    _addToast = (t) => {
      setToasts((prev) => [...prev, t]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== t.id));
      }, 5000);
    };
    return () => {
      _addToast = null;
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm shadow-lg border ${
            t.type === "error"
              ? "bg-[#1a1117] border-[var(--red)] text-[var(--red)]"
              : "bg-[#111a17] border-[var(--green)] text-[var(--green)]"
          }`}
        >
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() =>
              setToasts((prev) => prev.filter((x) => x.id !== t.id))
            }
            className="cursor-pointer opacity-50 hover:opacity-100"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      ))}
    </div>
  );
}
