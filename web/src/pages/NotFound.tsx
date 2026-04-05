import { CloudOff } from "lucide-react";
import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <CloudOff className="w-16 h-16 mx-auto mb-4 text-[var(--text-muted)] opacity-40" />
        <h1 className="text-2xl font-semibold mb-2">Page Not Found</h1>
        <p className="text-sm text-[var(--text-muted)] mb-6">
          The page you're looking for doesn't exist.
        </p>
        <Link
          to="/"
          className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm no-underline hover:bg-[var(--accent-hover)]"
        >
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
