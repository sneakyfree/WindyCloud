export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(i > 0 ? 1 : 0)} ${sizes[i]}`;
}

export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function productLabel(product: string): string {
  const map: Record<string, string> = {
    windy_chat: "Chat Archives",
    windy_mail: "Mail Archives",
    windy_pro: "Recordings",
    windy_fly: "Agent Backups",
    windy_code: "Code Settings",
    general: "General",
  };
  return map[product] || product;
}

export function productColor(product: string): string {
  const map: Record<string, string> = {
    windy_chat: "#6366f1",
    windy_mail: "#ec4899",
    windy_pro: "#f59e0b",
    windy_fly: "#22c55e",
    windy_code: "#06b6d4",
    general: "#71717a",
  };
  return map[product] || "#71717a";
}
