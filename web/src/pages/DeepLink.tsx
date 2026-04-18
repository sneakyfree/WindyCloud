import { Navigate, useParams, useSearchParams } from "react-router-dom";

// Mirrors the backend allow-list in api/app/routes/deeplink.py.
// Keeping the map here means the web app can resolve a known target
// instantly without a round-trip, while unknown targets fall through
// to the dashboard.
const WEB_PATHS: Record<string, string> = {
  dashboard: "/",
  backup: "/?action=start-backup",
  usage: "/billing",
  plan: "/billing?view=upgrade",
};

const SAFE_PARAM = /^[A-Za-z0-9_\-./]{1,64}$/;
const ALLOWED_PARAMS = new Set(["source", "ref"]);

function appendParams(basePath: string, extras: Record<string, string>): string {
  const keys = Object.keys(extras).sort();
  if (keys.length === 0) return basePath;
  const sep = basePath.includes("?") ? "&" : "?";
  const query = keys.map((k) => `${k}=${extras[k]}`).join("&");
  return `${basePath}${sep}${query}`;
}

export default function DeepLink() {
  const { target } = useParams<{ target: string }>();
  const [search] = useSearchParams();

  if (!target || !(target in WEB_PATHS)) {
    return <Navigate to="/" replace />;
  }

  const extras: Record<string, string> = {};
  for (const [key, value] of search.entries()) {
    if (!ALLOWED_PARAMS.has(key)) continue;
    if (!SAFE_PARAM.test(value)) continue;
    extras[key] = value;
  }

  return <Navigate to={appendParams(WEB_PATHS[target], extras)} replace />;
}
