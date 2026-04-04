import { Cloud } from "lucide-react";
import { useState } from "react";
import { setToken } from "../api";

export default function Login() {
  const [jwt, setJwt] = useState("");

  const handleLogin = () => {
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
            Sign in with your Windy Pro account
          </p>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-sm text-[var(--text-muted)] block mb-1">
              JWT Token
            </label>
            <input
              type="password"
              value={jwt}
              onChange={(e) => setJwt(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              placeholder="Paste your Windy Pro JWT..."
              className="w-full px-3 py-2 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)]"
            />
          </div>

          <button
            onClick={handleLogin}
            disabled={!jwt.trim()}
            className="w-full py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] disabled:opacity-50 cursor-pointer"
          >
            Sign In
          </button>

          <p className="text-xs text-[var(--text-muted)] text-center">
            Get your JWT from{" "}
            <a
              href="https://windypro.thewindstorm.uk"
              className="text-[var(--accent)]"
            >
              windypro.thewindstorm.uk
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
