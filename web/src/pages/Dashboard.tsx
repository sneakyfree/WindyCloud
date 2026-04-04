import { Cloud, HardDrive, Upload, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  type FileInfo,
  type UsageResponse,
  getBillingUsage,
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

export default function Dashboard() {
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [billing, setBilling] = useState<{
    total_cost_cents: number;
    compute: { total_jobs: number };
  } | null>(null);

  useEffect(() => {
    getUsage().then(setUsage).catch(() => {});
    listFiles({ limit: 8 })
      .then((r) => setFiles(r.files))
      .catch(() => {});
    getBillingUsage()
      .then(setBilling)
      .catch(() => {});
  }, []);

  const pct = usage ? usage.used_percent : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {/* Stats row */}
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

      {/* Quick actions */}
      <div className="flex gap-3">
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
      </div>

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
