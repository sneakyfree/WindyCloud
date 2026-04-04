import { CreditCard, HardDrive, TrendingUp, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import {
  type BillingHistoryEntry,
  type BillingUsage,
  type StoragePlan,
  getBillingHistory,
  getBillingUsage,
  getPlans,
} from "../api";
import { formatBytes, formatCents } from "../util";

export default function Billing() {
  const [usage, setUsage] = useState<BillingUsage | null>(null);
  const [history, setHistory] = useState<BillingHistoryEntry[]>([]);
  const [plans, setPlans] = useState<StoragePlan[]>([]);

  useEffect(() => {
    getBillingUsage().then(setUsage).catch(() => {});
    getBillingHistory()
      .then((r) => setHistory(r.entries))
      .catch(() => {});
    getPlans()
      .then((r) => setPlans(r.plans))
      .catch(() => {});
  }, []);

  const storageCost = usage
    ? estimateStorageCost(usage.storage.used_bytes)
    : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Billing</h1>

      {/* Current month breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <HardDrive className="w-5 h-5 text-[var(--accent)]" />
            <span className="text-sm text-[var(--text-muted)]">Storage</span>
          </div>
          <p className="text-2xl font-bold">
            {usage ? formatBytes(usage.storage.used_bytes) : "..."}
          </p>
          <p className="text-sm text-[var(--text-muted)]">
            {formatCents(storageCost)}/mo
          </p>
        </div>

        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <Zap className="w-5 h-5 text-[var(--yellow)]" />
            <span className="text-sm text-[var(--text-muted)]">Compute</span>
          </div>
          <p className="text-2xl font-bold">
            {usage
              ? `${Math.round(usage.compute.total_seconds / 60)} min`
              : "..."}
          </p>
          <p className="text-sm text-[var(--text-muted)]">
            {usage ? formatCents(usage.compute.total_cost_cents) : "$0.00"}
          </p>
        </div>

        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <CreditCard className="w-5 h-5 text-[var(--green)]" />
            <span className="text-sm text-[var(--text-muted)]">Total</span>
          </div>
          <p className="text-2xl font-bold">
            {usage ? formatCents(usage.total_cost_cents) : "$0.00"}
          </p>
          <p className="text-sm text-[var(--text-muted)]">
            {usage?.month || "..."}
          </p>
        </div>
      </div>

      {/* History */}
      <div>
        <h2 className="text-lg font-medium mb-3 flex items-center gap-2">
          <TrendingUp className="w-5 h-5" /> Billing History
        </h2>
        <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] overflow-hidden">
          {history.length === 0 ? (
            <p className="p-6 text-center text-[var(--text-muted)]">
              No billing history yet.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-[var(--text-muted)] text-left">
                  <th className="px-4 py-3 font-medium">Month</th>
                  <th className="px-4 py-3 font-medium">Storage</th>
                  <th className="px-4 py-3 font-medium">Compute</th>
                  <th className="px-4 py-3 font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr
                    key={h.month}
                    className="border-b border-[var(--border)] last:border-0"
                  >
                    <td className="px-4 py-3">{h.month}</td>
                    <td className="px-4 py-3 text-[var(--text-muted)]">
                      {formatBytes(h.storage_bytes)}
                    </td>
                    <td className="px-4 py-3 text-[var(--text-muted)]">
                      {formatCents(h.compute_cost_cents)}
                    </td>
                    <td className="px-4 py-3 font-medium">
                      {formatCents(h.total_cost_cents)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Plans */}
      <div>
        <h2 className="text-lg font-medium mb-3">Storage Plans</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {plans.map((p) => (
            <div
              key={p.plan_id}
              className="bg-[var(--bg-card)] rounded-xl p-4 border border-[var(--border)] text-center"
            >
              <p className="font-medium mb-1">{p.name}</p>
              <p className="text-2xl font-bold text-[var(--accent)]">
                {p.price_display}
              </p>
              <p className="text-sm text-[var(--text-muted)]">
                {p.storage_display}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function estimateStorageCost(bytes: number): number {
  const mb = bytes / (1024 * 1024);
  if (mb <= 500) return 0;
  if (mb <= 5120) return 200;
  if (mb <= 51200) return 500;
  return 1000;
}
