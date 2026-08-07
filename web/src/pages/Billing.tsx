import { CreditCard, HardDrive, TrendingUp, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import {
  type BillingHistoryEntry,
  type BillingUsage,
  type StoragePlan,
  getBillingHistory,
  getBillingUsage,
  getPlans,
  startCheckout,
} from "../api";
import { formatBytes, formatCents } from "../util";

export default function Billing() {
  const [usage, setUsage] = useState<BillingUsage | null>(null);
  const [history, setHistory] = useState<BillingHistoryEntry[]>([]);
  const [plans, setPlans] = useState<StoragePlan[]>([]);
  const [cycle, setCycle] = useState<"monthly" | "yearly">("monthly");
  const [buying, setBuying] = useState<string | null>(null);

  // Free is not purchasable, and Hurricane is sold by contract, not by card.
  const isPurchasable = (planId: string) =>
    planId !== "free" && planId !== "hurricane";

  async function buy(tier: string, billingCycle: "monthly" | "yearly") {
    setBuying(tier);
    try {
      const { url } = await startCheckout(tier, billingCycle);
      window.location.href = url;
    } catch {
      // apiFetch already surfaced the error as a toast.
      setBuying(null);
    }
  }

  // Arriving from windycloud.com with a plan already chosen: send them straight
  // to Stripe rather than making them find the same button a second time.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const plan = params.get("plan");
    const wanted = params.get("cycle") === "annual" ? "yearly" : "monthly";
    if (!plan || !isPurchasable(plan)) return;
    setCycle(wanted);
    window.history.replaceState({}, "", window.location.pathname);
    void buy(plan, wanted);
    // Runs once on mount; buy() is stable enough for this one-shot handoff.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    getBillingUsage().then(setUsage).catch(() => {});
    getBillingHistory()
      .then((r) => setHistory(r.entries))
      .catch(() => {});
    getPlans()
      .then((r) => setPlans(r.plans))
      .catch(() => {});
  }, []);

  const storageCost = usage && plans.length
    ? estimateStorageCost(usage.storage.used_bytes, plans)
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
        {/* One ladder across the ecosystem: a plan bought in Windy Word and a
            plan bought here are the same plan. See PRICING-TIERS.md. */}
        <p className="text-sm text-[var(--text-muted)] mb-3">
          Every paid plan includes Windy Word — the voice-to-text app, cloud
          transcription and translation come with your storage. Buy from either
          product and it unlocks both.
        </p>

        <div className="inline-flex rounded-lg border border-[var(--border)] p-1 mb-4">
          {(["monthly", "yearly"] as const).map((c) => (
            <button
              key={c}
              onClick={() => setCycle(c)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                cycle === c
                  ? "bg-[var(--accent)] text-white"
                  : "text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              {c === "monthly" ? "Monthly" : "Yearly"}
              {c === "yearly" && (
                <span className="ml-1.5 text-[10px] font-semibold">
                  2 months free
                </span>
              )}
            </button>
          ))}
        </div>
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
              {isPurchasable(p.plan_id) ? (
                <button
                  onClick={() => buy(p.plan_id, cycle)}
                  disabled={buying !== null}
                  className="mt-3 w-full py-2 rounded-lg text-sm font-medium bg-[var(--accent)] text-white disabled:opacity-50 transition-opacity"
                >
                  {buying === p.plan_id ? "Starting…" : "Choose"}
                </button>
              ) : (
                <p className="mt-3 text-xs text-[var(--text-muted)]">
                  {p.plan_id === "free" ? "Included" : "Contact us"}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * Smallest plan that covers `bytes` — that's the month's storage cost.
 *
 * Derived from the plans fetched from the server, NEVER from a table in this
 * file. This function used to hardcode its own ladder (500 MB / 5 GB / 50 GB
 * at $2 / $5 / $10), which matched no real plan and no real price — a fifth
 * competing copy of the pricing ladder living in the browser.
 *
 * Hurricane is skipped: its price is 0 meaning "Custom", so including it would
 * quote a very large account as free.
 */
function estimateStorageCost(bytes: number, plans: StoragePlan[]): number {
  const billable = plans.filter((p) => p.plan_id !== "hurricane");
  const ascending = [...billable].sort((a, b) => a.storage_bytes - b.storage_bytes);
  for (const plan of ascending) {
    if (bytes <= plan.storage_bytes) return plan.price_cents_per_month;
  }
  return ascending.length ? ascending[ascending.length - 1].price_cents_per_month : 0;
}
