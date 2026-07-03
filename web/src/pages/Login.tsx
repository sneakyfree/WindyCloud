import { Cloud, Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { setToken } from "../api";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [jwt, setJwt] = useState("");

  const handleLogin = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!email.trim() || !password) return;
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Sign-in failed. Please try again.");
      }
      const token = data.token || data.jwt || data.access_token;
      if (!token) throw new Error("Sign-in failed — no token returned.");
      setToken(token);
      window.location.href = "/";
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleTokenLogin = () => {
    if (jwt.trim()) {
      setToken(jwt.trim());
      window.location.href = "/";
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="bg-[var(--bg-card)] rounded-2xl p-8 border border-[var(--border)] w-full max-w-sm">
        <div className="text-center mb-6">
          <Cloud className="w-12 h-12 mx-auto mb-3 text-[var(--accent)]" />
          <h1 className="text-xl font-semibold">Windy Cloud</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Sign in with your Windy account
          </p>
        </div>

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="text-sm text-[var(--text-muted)] block mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              className="w-full px-3 py-2 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div>
            <label className="text-sm text-[var(--text-muted)] block mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              className="w-full px-3 py-2 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)]"
            />
          </div>

          {error && (
            <p className="text-sm text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !email.trim() || !password}
            className="w-full py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] disabled:opacity-50 cursor-pointer flex items-center justify-center gap-2"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>

        <p className="text-xs text-[var(--text-muted)] text-center mt-4">
          Don't have an account?{" "}
          <a href="https://windyword.ai" className="text-[var(--accent)]">
            Create one at windyword.ai
          </a>
        </p>

        <div className="mt-6 pt-4 border-t border-[var(--border)]">
          <button
            type="button"
            onClick={() => setShowToken((s) => !s)}
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] cursor-pointer"
          >
            {showToken ? "− Hide" : "+ Advanced"}: sign in with a token
          </button>
          {showToken && (
            <div className="space-y-2 mt-3">
              <input
                type="password"
                value={jwt}
                onChange={(e) => setJwt(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleTokenLogin()}
                placeholder="Paste a Windy identity token..."
                className="w-full px-3 py-2 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)]"
              />
              <button
                type="button"
                onClick={handleTokenLogin}
                disabled={!jwt.trim()}
                className="w-full py-2 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-sm font-medium hover:border-[var(--accent)] disabled:opacity-50 cursor-pointer"
              >
                Use token
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
