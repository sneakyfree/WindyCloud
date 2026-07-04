import { Check, Cloud, Shield, Trash2 } from "lucide-react";
import { useState } from "react";
import { logout, setToken } from "../api";

const PRODUCTS = [
  { name: "Windy Word", status: "connected", color: "var(--green)" },
  { name: "Windy Chat", status: "connected", color: "var(--green)" },
  { name: "Windy Mail", status: "connected", color: "var(--green)" },
  { name: "Windy Fly", status: "connected", color: "var(--green)" },
  { name: "Windy Code", status: "not connected", color: "var(--text-muted)" },
];

export default function SettingsPage() {
  const [autoSync, setAutoSync] = useState(true);
  const [retentionDays, setRetentionDays] = useState("90");
  const [saved, setSaved] = useState(false);
  const [jwt, setJwt] = useState("");
  const [showToken, setShowToken] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-semibold">Settings</h1>

      {/* Account — sign-out up front; the raw-token swap lives behind
          the same collapsed Advanced idiom as the Login page. */}
      <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
        <h2 className="text-lg font-medium mb-3">Account</h2>
        <div className="space-y-3">
          <p className="text-sm text-[var(--text-muted)]">
            You're signed in with your Windy account.
          </p>
          <button
            onClick={logout}
            className="flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--border)] text-sm text-[var(--red)] hover:bg-[var(--bg-hover)] cursor-pointer"
          >
            <Trash2 className="w-4 h-4" /> Sign out
          </button>

          <div className="pt-3 border-t border-[var(--border)]">
            <button
              type="button"
              onClick={() => setShowToken((s) => !s)}
              className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] cursor-pointer"
            >
              {showToken ? "− Hide" : "+ Advanced"}: replace your identity token
            </button>
            {showToken && (
              <div className="flex gap-2 mt-3">
                <input
                  type="password"
                  value={jwt}
                  onChange={(e) => setJwt(e.target.value)}
                  placeholder="Paste a Windy identity token..."
                  className="flex-1 px-3 py-2 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)]"
                />
                <button
                  onClick={() => {
                    setToken(jwt);
                    window.location.reload();
                  }}
                  disabled={!jwt.trim()}
                  className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm hover:bg-[var(--accent-hover)] disabled:opacity-50 cursor-pointer"
                >
                  Save
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Auto-sync */}
      <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
        <h2 className="text-lg font-medium mb-3 flex items-center gap-2">
          <Cloud className="w-5 h-5" /> Sync Preferences
        </h2>
        <div className="space-y-4">
          <label className="flex items-center justify-between cursor-pointer">
            <span className="text-sm">Auto-sync to Cloud</span>
            <button
              onClick={() => setAutoSync(!autoSync)}
              className={`w-10 h-6 rounded-full transition-colors cursor-pointer ${
                autoSync ? "bg-[var(--accent)]" : "bg-[var(--bg-hover)]"
              }`}
            >
              <div
                className={`w-4 h-4 rounded-full bg-white transition-transform mx-1 mt-1 ${
                  autoSync ? "translate-x-4" : ""
                }`}
              />
            </button>
          </label>

          <div>
            <label className="text-sm text-[var(--text-muted)] block mb-1">
              Default Retention (days)
            </label>
            <select
              value={retentionDays}
              onChange={(e) => setRetentionDays(e.target.value)}
              className="px-3 py-2 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm text-[var(--text)] outline-none"
            >
              <option value="30">30 days</option>
              <option value="90">90 days</option>
              <option value="180">180 days</option>
              <option value="365">1 year</option>
              <option value="0">Forever</option>
            </select>
          </div>
        </div>
      </div>

      {/* Connected services */}
      <div className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]">
        <h2 className="text-lg font-medium mb-3 flex items-center gap-2">
          <Shield className="w-5 h-5" /> Connected Services
        </h2>
        <div className="space-y-2">
          {PRODUCTS.map((p) => (
            <div
              key={p.name}
              className="flex items-center justify-between py-2"
            >
              <span className="text-sm">{p.name}</span>
              <span
                className="text-xs flex items-center gap-1"
                style={{ color: p.color }}
              >
                {p.status === "connected" && (
                  <Check className="w-3 h-3" />
                )}
                {p.status}
              </span>
            </div>
          ))}
        </div>
      </div>

      <button
        onClick={handleSave}
        className="flex items-center gap-2 px-6 py-2 rounded-lg bg-[var(--accent)] text-white text-sm hover:bg-[var(--accent-hover)] cursor-pointer"
      >
        {saved ? (
          <>
            <Check className="w-4 h-4" /> Saved
          </>
        ) : (
          "Save Settings"
        )}
      </button>
    </div>
  );
}
