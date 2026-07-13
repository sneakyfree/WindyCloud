import {
  Cloud,
  Cpu,
  FileText,
  Globe,
  Home,
  LayoutDashboard,
  LogOut,
  Receipt,
  Server,
  Settings,
} from "lucide-react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { logout } from "./api";

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/files", icon: FileText, label: "Files" },
  { to: "/compute", icon: Cpu, label: "Compute" },
  { to: "/servers", icon: Server, label: "Servers" },
  { to: "/billing", icon: Receipt, label: "Billing" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

// Sibling-cell pages (windy-cloud-domains / windy-cloud-sites) served
// same-origin by nginx path routing — plain <a>, not router Links. The
// session rides the FRAGMENT (never ?token= — that seam is closed).
const CELL_NAV = [
  { href: "/domains/", icon: Globe, label: "Domains" },
  { href: "/websites/", icon: Home, label: "Websites" },
];

function cellHref(href: string): string {
  const token = localStorage.getItem("windy_jwt");
  return token ? `${href}#token=${encodeURIComponent(token)}` : href;
}

export default function Layout() {
  const { pathname } = useLocation();

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 border-r border-[var(--border)] bg-[var(--bg-card)] flex flex-col">
        <div className="p-4 border-b border-[var(--border)]">
          <Link to="/" className="flex items-center gap-2 no-underline">
            <Cloud className="w-6 h-6 text-[var(--accent)]" />
            <span className="text-lg font-semibold text-[var(--text)]">
              Windy Cloud
            </span>
          </Link>
        </div>

        <nav className="flex-1 p-2 space-y-0.5">
          {NAV.map(({ to, icon: Icon, label }) => {
            const active =
              to === "/" ? pathname === "/" : pathname.startsWith(to);
            return (
              <Link
                key={to}
                to={to}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm no-underline transition-colors ${
                  active
                    ? "bg-[var(--accent)] text-white"
                    : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text)]"
                }`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </Link>
            );
          })}
          {CELL_NAV.map(({ href, icon: Icon, label }) => (
            <a
              key={href}
              href={cellHref(href)}
              className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm no-underline transition-colors text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text)]"
            >
              <Icon className="w-4 h-4" />
              {label}
            </a>
          ))}
        </nav>

        <div className="p-2 border-t border-[var(--border)]">
          <button
            onClick={logout}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--red)] w-full transition-colors cursor-pointer"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
