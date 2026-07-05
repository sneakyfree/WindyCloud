import {
  Circle,
  ExternalLink,
  Play,
  Power,
  RefreshCw,
  Rocket,
  Server,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  type ServerInstance,
  type ServerPlan,
  deleteServer,
  deployFly,
  getServerPlans,
  listServers,
  serverAction,
} from "../api";
import { formatCents, formatDateTime } from "../util";

const STATUS_COLOR: Record<string, string> = {
  running: "var(--green)",
  stopped: "var(--red)",
  provisioning: "var(--yellow)",
  terminated: "var(--text-muted)",
};

/**
 * "Host on VPS" (ADR-051 relief valve): pick a plan, name your Fly,
 * one click. While prod has no AWS credentials the backend 503s —
 * surfaced as a friendly "not switched on yet" note, so this ships
 * ahead of the ops flip.
 */
function HostFlyPanel({ onDeployed }: { onDeployed: () => void }) {
  const [open, setOpen] = useState(false);
  const [plans, setPlans] = useState<ServerPlan[]>([]);
  const [planId, setPlanId] = useState("starter");
  const [agentName, setAgentName] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || plans.length > 0) return;
    getServerPlans()
      .then((r) => {
        setPlans(r.plans);
        if (!r.plans.some((p) => p.plan_id === planId) && r.plans[0]) {
          setPlanId(r.plans[0].plan_id);
        }
      })
      .catch(() => setError("Couldn't load server plans — try again in a moment."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleDeploy = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await deployFly({
        plan: planId,
        ...(agentName.trim() ? { agent_name: agentName.trim() } : {}),
      });
      setNotice(
        `Your server is on its way (${result.hostname || result.server_id}). ` +
          "It takes a few minutes to wake up — watch the list below.",
      );
      setOpen(false);
      onDeployed();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === "vps_unavailable") {
        setError(
          "Server hosting isn't switched on for this account yet — it's coming soon. Your Fly keeps working from your own devices in the meantime.",
        );
      } else if (msg === "server_limit") {
        setError(
          "You've reached your server limit. Remove one below to make room.",
        );
      } else {
        setError("Something went wrong starting the server. Try again in a moment.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-90 cursor-pointer"
        >
          <Rocket className="w-4 h-4" /> Host my Fly on a server
        </button>
      ) : (
        <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)] space-y-4">
          <div>
            <h2 className="font-medium mb-1">Host your Windy Fly on a server</h2>
            <p className="text-sm text-[var(--text-muted)]">
              Your helper gets its own always-on home in the cloud — it keeps
              thinking even when your computer is off.
            </p>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {plans.map((p) => (
              <button
                key={p.plan_id}
                onClick={() => setPlanId(p.plan_id)}
                className={`text-left rounded-lg border p-3 cursor-pointer ${
                  planId === p.plan_id
                    ? "border-[var(--accent)] bg-[var(--bg-hover)]"
                    : "border-[var(--border)] hover:bg-[var(--bg-hover)]"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium capitalize">{p.name}</span>
                  <span className="text-sm">
                    {formatCents(p.price_cents_per_month)}/mo
                  </span>
                </div>
                <p className="text-xs text-[var(--text-muted)] mt-1">
                  {p.vcpus} CPU · {p.ram_gb} GB memory · {p.disk_gb} GB disk
                </p>
              </button>
            ))}
            {plans.length === 0 && !error && (
              <p className="text-sm text-[var(--text-muted)]">Loading plans…</p>
            )}
          </div>

          <div className="flex flex-wrap gap-2 items-center">
            <input
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              placeholder="Name your Fly (optional)"
              className="px-3 py-2 rounded-lg border border-[var(--border)] bg-transparent text-sm w-56"
            />
            <button
              onClick={handleDeploy}
              disabled={busy || plans.length === 0}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-90 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Rocket className="w-4 h-4" />
              {busy ? "Starting your server…" : "Host my Fly"}
            </button>
            <button
              onClick={() => setOpen(false)}
              disabled={busy}
              className="px-3 py-2 rounded-lg border border-[var(--border)] text-sm text-[var(--text-muted)] hover:bg-[var(--bg-hover)] cursor-pointer"
            >
              Cancel
            </button>
          </div>

          {error && <p className="text-sm text-[var(--red)]">{error}</p>}
        </div>
      )}
      {notice && <p className="text-sm text-[var(--green)]">{notice}</p>}
    </div>
  );
}

export default function Servers() {
  const [servers, setServers] = useState<ServerInstance[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    listServers()
      .then((r) => setServers(r.servers))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const handleAction = async (id: string, action: string) => {
    await serverAction(id, action).catch(() => {});
    load();
  };

  const handleDelete = async (s: ServerInstance) => {
    if (!confirm(`Destroy server ${s.hostname || s.server_id}?`)) return;
    await deleteServer(s.server_id).catch(() => {});
    load();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">VPS Servers</h1>
        <button
          onClick={load}
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--border)] text-sm text-[var(--text-muted)] hover:bg-[var(--bg-hover)] cursor-pointer"
        >
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      <HostFlyPanel onDeployed={load} />

      {loading ? (
        <p className="text-[var(--text-muted)]">Loading...</p>
      ) : servers.length === 0 ? (
        <div className="bg-[var(--bg-card)] rounded-xl p-8 border border-[var(--border)] text-center">
          <Server className="w-12 h-12 mx-auto mb-3 text-[var(--text-muted)]" />
          <p className="text-[var(--text-muted)]">
            No servers provisioned yet.
          </p>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Use "Host my Fly on a server" above — one click, no setup.
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {servers.map((s) => (
            <div
              key={s.server_id}
              className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <Circle
                      className="w-3 h-3"
                      fill={STATUS_COLOR[s.status] || "var(--text-muted)"}
                      stroke="none"
                    />
                    <span className="font-medium">
                      {s.hostname || s.server_id.slice(0, 8)}
                    </span>
                    <span className="text-xs text-[var(--text-muted)] capitalize">
                      {s.status}
                    </span>
                  </div>
                  <div className="flex gap-4 text-sm text-[var(--text-muted)]">
                    <span>Plan: {s.plan_id}</span>
                    <span>Region: {s.region}</span>
                    <span>{formatCents(s.monthly_cost_cents)}/mo</span>
                    {s.ip_address && <span>IP: {s.ip_address}</span>}
                  </div>
                  <p className="text-xs text-[var(--text-muted)] mt-1">
                    Created {formatDateTime(s.created_at)}
                  </p>
                </div>

                <div className="flex gap-1">
                  {s.status === "stopped" && (
                    <button
                      onClick={() => handleAction(s.server_id, "start")}
                      className="p-2 rounded hover:bg-[var(--bg-hover)] text-[var(--green)] cursor-pointer"
                      title="Start"
                    >
                      <Play className="w-4 h-4" />
                    </button>
                  )}
                  {s.status === "running" && (
                    <>
                      <button
                        onClick={() => handleAction(s.server_id, "stop")}
                        className="p-2 rounded hover:bg-[var(--bg-hover)] text-[var(--yellow)] cursor-pointer"
                        title="Stop"
                      >
                        <Power className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleAction(s.server_id, "reboot")}
                        className="p-2 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] cursor-pointer"
                        title="Reboot"
                      >
                        <RefreshCw className="w-4 h-4" />
                      </button>
                    </>
                  )}
                  {s.ip_address && (
                    <a
                      href={`http://${s.ip_address}:3000`}
                      target="_blank"
                      rel="noopener"
                      className="p-2 rounded hover:bg-[var(--bg-hover)] text-[var(--accent)]"
                      title="Dashboard"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  )}
                  <button
                    onClick={() => handleDelete(s)}
                    className="p-2 rounded hover:bg-[var(--bg-hover)] text-[var(--red)] cursor-pointer"
                    title="Destroy"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
