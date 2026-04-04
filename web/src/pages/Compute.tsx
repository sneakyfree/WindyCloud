import { Clock, Cpu, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { type ComputeUsage, getComputeUsage } from "../api";
import { formatCents } from "../util";

export default function Compute() {
  const [usage, setUsage] = useState<ComputeUsage | null>(null);

  useEffect(() => {
    getComputeUsage().then(setUsage).catch(() => {});
  }, []);

  const totalMin = usage ? Math.round(usage.total_seconds / 60 * 10) / 10 : 0;
  const freeMin = usage ? usage.free_minutes_remaining : 10;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Cloud Compute</h1>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <Cpu className="w-5 h-5 text-[var(--accent)]" />
            <span className="text-sm text-[var(--text-muted)]">STT Jobs</span>
          </div>
          <p className="text-2xl font-bold">{usage?.total_jobs ?? 0}</p>
          <p className="text-sm text-[var(--text-muted)]">this month</p>
        </div>

        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <Clock className="w-5 h-5 text-[var(--green)]" />
            <span className="text-sm text-[var(--text-muted)]">Minutes Used</span>
          </div>
          <p className="text-2xl font-bold">{totalMin} min</p>
          <p className="text-sm text-[var(--text-muted)]">
            {freeMin} free min remaining
          </p>
          <div className="mt-3 h-2 rounded-full bg-[var(--bg-hover)] overflow-hidden">
            <div
              className="h-full rounded-full bg-[var(--green)] transition-all"
              style={{ width: `${Math.min((totalMin / (totalMin + freeMin)) * 100, 100)}%` }}
            />
          </div>
        </div>

        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <Zap className="w-5 h-5 text-[var(--yellow)]" />
            <span className="text-sm text-[var(--text-muted)]">Cost</span>
          </div>
          <p className="text-2xl font-bold">
            {usage ? formatCents(usage.total_cost_cents) : "$0.00"}
          </p>
          <p className="text-sm text-[var(--text-muted)]">this month</p>
        </div>
      </div>

      {/* Info */}
      <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
        <h2 className="text-lg font-medium mb-2">How Cloud STT Works</h2>
        <p className="text-sm text-[var(--text-muted)] leading-relaxed">
          When your local Whisper can't keep up, audio routes to Windy Cloud's
          GPU cluster for transcription. First 10 minutes per month are free.
          After that, you pay per minute at 3x provider cost.
        </p>
        <div className="mt-4 grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-xs text-[var(--text-muted)]">Provider</p>
            <p className="text-sm font-medium">RunPod GPU</p>
          </div>
          <div>
            <p className="text-xs text-[var(--text-muted)]">Model</p>
            <p className="text-sm font-medium">Whisper Large V3</p>
          </div>
          <div>
            <p className="text-xs text-[var(--text-muted)]">Free Tier</p>
            <p className="text-sm font-medium">10 min/month</p>
          </div>
        </div>
      </div>
    </div>
  );
}
