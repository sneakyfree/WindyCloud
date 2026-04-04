import {
  Circle,
  ExternalLink,
  Play,
  Power,
  RefreshCw,
  Server,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  type ServerInstance,
  deleteServer,
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

      {loading ? (
        <p className="text-[var(--text-muted)]">Loading...</p>
      ) : servers.length === 0 ? (
        <div className="bg-[var(--bg-card)] rounded-xl p-8 border border-[var(--border)] text-center">
          <Server className="w-12 h-12 mx-auto mb-3 text-[var(--text-muted)]" />
          <p className="text-[var(--text-muted)]">
            No servers provisioned yet.
          </p>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Deploy a Windy Fly agent via the API or CLI.
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
