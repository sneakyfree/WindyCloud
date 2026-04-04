import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  Cloud,
  Clock,
  Download,
  HardDrive,
  Loader2,
  RefreshCw,
  TrendingUp,
  Upload,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  type FileInfo,
  type ProductBreakdown,
  type UsageResponse,
  exportAllData,
  getBillingUsage,
  getStorageBreakdown,
  getUsage,
  listFiles,
} from "../api";
import {
  formatBytes,
  formatCents,
  formatDateTime,
  productColor,
  productLabel,
} from "../util";

// --- Donut chart (pure SVG) ---

function DonutChart({
  segments,
  total,
  quota,
}: {
  segments: { product: string; bytes: number }[];
  total: number;
  quota: number;
}) {
  const size = 160;
  const stroke = 20;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const cx = size / 2;
  const cy = size / 2;

  let offset = 0;
  const arcs = segments
    .filter((s) => s.bytes > 0)
    .map((s) => {
      const pct = total > 0 ? s.bytes / total : 0;
      const len = pct * circumference;
      const arc = { ...s, len, offset, color: productColor(s.product) };
      offset += len;
      return arc;
    });

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90">
        {/* Background ring */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="var(--bg-hover)"
          strokeWidth={stroke}
        />
        {/* Segments */}
        {arcs.map((a) => (
          <circle
            key={a.product}
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={a.color}
            strokeWidth={stroke}
            strokeDasharray={`${a.len} ${circumference - a.len}`}
            strokeDashoffset={-a.offset}
            strokeLinecap="round"
            className="transition-all duration-500"
          />
        ))}
      </svg>
      <div className="absolute text-center">
        <p className="text-lg font-bold">{formatBytes(total)}</p>
        <p className="text-xs text-[var(--text-muted)]">
          of {formatBytes(quota)}
        </p>
      </div>
    </div>
  );
}

// --- Sync status cards ---

interface SyncStatus {
  product: string;
  label: string;
  schedule: string;
  lastSync: string;
  nextSync: string;
  ok: boolean;
}

const SYNC_STATUSES: SyncStatus[] = [
  {
    product: "windy_chat",
    label: "Windy Chat",
    schedule: "Encrypted backup every 24h",
    lastSync: "2 hours ago",
    nextSync: "in 22 hours",
    ok: true,
  },
  {
    product: "windy_mail",
    label: "Windy Mail",
    schedule: "Auto-archive emails older than 90 days",
    lastSync: "Yesterday",
    nextSync: "Daily at midnight",
    ok: true,
  },
  {
    product: "windy_fly",
    label: "Windy Fly",
    schedule: "Database backup daily at 3am",
    lastSync: "5 hours ago",
    nextSync: "in 19 hours",
    ok: true,
  },
  {
    product: "windy_pro",
    label: "Windy Word",
    schedule: "Recordings sync on save",
    lastSync: "3 days ago",
    nextSync: "On next recording",
    ok: true,
  },
  {
    product: "windy_code",
    label: "Windy Code",
    schedule: "Settings sync",
    lastSync: "Never",
    nextSync: "-",
    ok: false,
  },
];

export default function Dashboard() {
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [billing, setBilling] = useState<{
    total_cost_cents: number;
    compute: { total_jobs: number };
  } | null>(null);
  const [breakdown, setBreakdown] = useState<ProductBreakdown[]>([]);
  const [exporting, setExporting] = useState(false);
  const [exportPct, setExportPct] = useState(0);

  useEffect(() => {
    getUsage().then(setUsage).catch(() => {});
    listFiles({ limit: 6 })
      .then((r) => setFiles(r.files))
      .catch(() => {});
    getBillingUsage()
      .then(setBilling)
      .catch(() => {});
    getStorageBreakdown()
      .then((r) => setBreakdown(r.products))
      .catch(() => {});
  }, []);

  const pct = usage ? usage.used_percent : 0;
  const total = usage?.used_bytes || 0;
  const quota = usage?.quota_bytes || 1;

  const handleExport = async () => {
    setExporting(true);
    setExportPct(0);
    try {
      await exportAllData((p) => setExportPct(p));
    } catch {
      // error handled in api
    }
    setTimeout(() => {
      setExporting(false);
      setExportPct(0);
    }, 1500);
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {/* Top stats row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <HardDrive className="w-5 h-5 text-[var(--accent)]" />
            <span className="text-sm text-[var(--text-muted)]">Storage</span>
          </div>
          <p className="text-2xl font-bold">
            {usage ? formatBytes(usage.used_bytes) : "..."}
          </p>
          <p className="text-sm text-[var(--text-muted)]">
            of {usage ? formatBytes(usage.quota_bytes) : "..."} used
          </p>
          <div className="mt-3 h-2 rounded-full bg-[var(--bg-hover)] overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(pct, 100)}%`,
                background:
                  pct > 90
                    ? "var(--red)"
                    : pct > 70
                      ? "var(--yellow)"
                      : "var(--accent)",
              }}
            />
          </div>
        </div>

        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <Zap className="w-5 h-5 text-[var(--yellow)]" />
            <span className="text-sm text-[var(--text-muted)]">Compute</span>
          </div>
          <p className="text-2xl font-bold">
            {billing ? billing.compute.total_jobs : 0} jobs
          </p>
          <p className="text-sm text-[var(--text-muted)]">this month</p>
        </div>

        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <div className="flex items-center gap-3 mb-3">
            <Cloud className="w-5 h-5 text-[var(--green)]" />
            <span className="text-sm text-[var(--text-muted)]">
              Total Cost
            </span>
          </div>
          <p className="text-2xl font-bold">
            {billing ? formatCents(billing.total_cost_cents) : "$0.00"}
          </p>
          <p className="text-sm text-[var(--text-muted)]">this month</p>
        </div>
      </div>

      {/* Upgrade prompt */}
      {pct >= 70 && (
        <div
          className="rounded-xl p-4 border flex items-center gap-3"
          style={{
            borderColor: pct >= 90 ? "var(--red)" : "var(--yellow)",
            background:
              pct >= 90
                ? "rgba(239,68,68,0.08)"
                : "rgba(234,179,8,0.08)",
          }}
        >
          <AlertTriangle
            className="w-5 h-5 flex-shrink-0"
            style={{ color: pct >= 90 ? "var(--red)" : "var(--yellow)" }}
          />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {pct >= 90
                ? `You're at ${Math.round(pct)}% — running out of space!`
                : `You're at ${Math.round(pct)}% — upgrade for more space`}
            </p>
            <p className="text-xs text-[var(--text-muted)]">
              {formatBytes(quota - total)} remaining
            </p>
          </div>
          <Link
            to="/billing"
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[var(--accent)] text-white text-xs no-underline hover:bg-[var(--accent-hover)]"
          >
            Upgrade <ArrowUpRight className="w-3 h-3" />
          </Link>
        </div>
      )}

      {/* Storage breakdown + donut chart */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <h2 className="text-lg font-medium mb-4">Storage by Product</h2>
          <div className="flex items-center gap-6">
            <DonutChart segments={breakdown} total={total} quota={quota} />
            <div className="space-y-2 flex-1">
              {breakdown.length === 0 && (
                <p className="text-sm text-[var(--text-muted)]">No data yet</p>
              )}
              {breakdown
                .sort((a, b) => b.bytes - a.bytes)
                .map((p) => (
                  <div key={p.product} className="flex items-center gap-2">
                    <div
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ background: productColor(p.product) }}
                    />
                    <span className="text-sm flex-1">
                      {productLabel(p.product)}
                    </span>
                    <span className="text-sm text-[var(--text-muted)]">
                      {formatBytes(p.bytes)}
                    </span>
                  </div>
                ))}
            </div>
          </div>
          {total > 0 && (
            <p className="mt-4 text-xs text-[var(--text-muted)] flex items-center gap-1">
              <TrendingUp className="w-3 h-3" />
              Storage growing at ~{formatBytes(Math.round(total / 4))}/month
            </p>
          )}
        </div>

        {/* Auto-sync status */}
        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
          <h2 className="text-lg font-medium mb-4 flex items-center gap-2">
            <RefreshCw className="w-4 h-4" /> Auto-Sync Status
          </h2>
          <div className="space-y-3">
            {SYNC_STATUSES.map((s) => (
              <div
                key={s.product}
                className="flex items-start gap-3 py-1.5"
              >
                <div
                  className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0"
                  style={{
                    background: s.ok ? "var(--green)" : "var(--text-muted)",
                  }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{s.label}</span>
                    {s.ok ? (
                      <Check className="w-3 h-3 text-[var(--green)]" />
                    ) : (
                      <AlertTriangle className="w-3 h-3 text-[var(--text-muted)]" />
                    )}
                  </div>
                  <p className="text-xs text-[var(--text-muted)]">
                    {s.schedule}
                  </p>
                  {s.ok && (
                    <p className="text-xs text-[var(--text-muted)] flex items-center gap-1 mt-0.5">
                      <Clock className="w-3 h-3" />
                      Last: {s.lastSync} &middot; Next: {s.nextSync}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Quick actions */}
      <div className="flex gap-3 flex-wrap">
        <Link
          to="/files"
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm no-underline hover:bg-[var(--accent-hover)] transition-colors"
        >
          <Upload className="w-4 h-4" /> Upload Files
        </Link>
        <Link
          to="/billing"
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-[var(--border)] text-sm no-underline text-[var(--text)] hover:bg-[var(--bg-hover)] transition-colors"
        >
          Manage Plan
        </Link>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-[var(--border)] text-sm text-[var(--text)] hover:bg-[var(--bg-hover)] transition-colors disabled:opacity-50 cursor-pointer"
        >
          {exporting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Download className="w-4 h-4" />
          )}
          {exporting
            ? exportPct >= 100
              ? "Done!"
              : `Exporting... ${exportPct}%`
            : "Download My Data"}
        </button>
      </div>

      {/* Export progress bar */}
      {exporting && (
        <div className="h-1.5 rounded-full bg-[var(--bg-hover)] overflow-hidden">
          <div
            className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
            style={{ width: `${exportPct}%` }}
          />
        </div>
      )}

      {/* Recent files */}
      <div>
        <h2 className="text-lg font-medium mb-3">Recent Files</h2>
        <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] overflow-hidden">
          {files.length === 0 ? (
            <p className="p-6 text-center text-[var(--text-muted)]">
              No files yet. Upload something!
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-[var(--text-muted)] text-left">
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Product</th>
                  <th className="px-4 py-3 font-medium">Size</th>
                  <th className="px-4 py-3 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {files.map((f) => (
                  <tr
                    key={f.file_id}
                    className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)]"
                  >
                    <td className="px-4 py-3">{f.filename}</td>
                    <td className="px-4 py-3">
                      <span
                        className="inline-block px-2 py-0.5 rounded text-xs"
                        style={{
                          background: productColor(f.product) + "22",
                          color: productColor(f.product),
                        }}
                      >
                        {productLabel(f.product)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[var(--text-muted)]">
                      {formatBytes(f.size_bytes)}
                    </td>
                    <td className="px-4 py-3 text-[var(--text-muted)]">
                      {formatDateTime(f.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
