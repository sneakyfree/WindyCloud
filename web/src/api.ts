const API_BASE = "/api/v1";

function getToken(): string {
  return localStorage.getItem("windy_jwt") || "";
}

function headers(): HeadersInit {
  return {
    Authorization: `Bearer ${getToken()}`,
  };
}

function jsonHeaders(): HeadersInit {
  return {
    ...headers(),
    "Content-Type": "application/json",
  };
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...headers(), ...init?.headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// --- Storage ---

export interface FileInfo {
  file_id: string;
  product: string;
  file_type: string;
  filename: string;
  storage_key: string;
  size_bytes: number;
  content_type: string;
  encrypted: boolean;
  created_at: string;
}

export interface FileListResponse {
  files: FileInfo[];
  total: number;
  next_token: string | null;
  truncated: boolean;
}

export interface UsageResponse {
  used_bytes: number;
  file_count: number;
  quota_bytes: number;
  used_percent: number;
}

export interface UploadResponse {
  file_id: string;
  key: string;
  size: number;
  content_type: string;
  message: string;
}

export function listFiles(params?: {
  product?: string;
  limit?: number;
  offset?: number;
}): Promise<FileListResponse> {
  const qs = new URLSearchParams();
  if (params?.product) qs.set("product", params.product);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return apiFetch(`/storage/files${q ? `?${q}` : ""}`);
}

export function getUsage(): Promise<UsageResponse> {
  return apiFetch("/storage/usage");
}

export async function uploadFile(
  file: File,
  product: string = "general",
  fileType: string = "file"
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("product", product);
  form.append("file_type", fileType);
  const res = await fetch(`${API_BASE}/storage/upload`, {
    method: "POST",
    headers: headers(),
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export async function downloadFile(fileId: string, filename: string) {
  const res = await fetch(`${API_BASE}/storage/files/${fileId}`, {
    headers: headers(),
  });
  if (!res.ok) throw new Error("Download failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function deleteFile(fileId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/storage/files/${fileId}`, { method: "DELETE" });
}

export interface ProductBreakdown {
  product: string;
  bytes: number;
  file_count: number;
}

export function getStorageBreakdown(): Promise<{
  products: ProductBreakdown[];
}> {
  return apiFetch("/storage/breakdown");
}

export async function exportAllData(
  onProgress?: (pct: number) => void
): Promise<void> {
  onProgress?.(10);
  const res = await fetch(`${API_BASE}/storage/export`, {
    headers: headers(),
  });
  if (!res.ok) throw new Error("Export failed");
  onProgress?.(60);
  const blob = await res.blob();
  onProgress?.(90);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "windy-cloud-export.zip";
  a.click();
  URL.revokeObjectURL(url);
  onProgress?.(100);
}

// --- Compute ---

export interface ComputeUsage {
  identity_id: string;
  month: string;
  total_seconds: number;
  total_jobs: number;
  total_cost_cents: number;
  free_minutes_remaining: number;
}

export interface STTJob {
  job_id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  result: {
    text: string;
    duration_seconds: number;
    cost_cents: number;
  } | null;
}

export function getComputeUsage(): Promise<ComputeUsage> {
  return apiFetch("/compute/usage");
}

// --- Servers ---

export interface ServerInstance {
  server_id: string;
  identity_id: string;
  plan_id: string;
  region: string;
  image: string;
  status: string;
  ip_address: string | null;
  hostname: string | null;
  created_at: string;
  monthly_cost_cents: number;
}

export interface ServerListResponse {
  servers: ServerInstance[];
  total: number;
}

export function listServers(): Promise<ServerListResponse> {
  return apiFetch("/servers");
}

export function serverAction(
  serverId: string,
  action: string
): Promise<{ status: string; message: string }> {
  return apiFetch(`/servers/${serverId}/action`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ action }),
  });
}

export function deleteServer(
  serverId: string
): Promise<{ deleted: boolean }> {
  return apiFetch(`/servers/${serverId}`, { method: "DELETE" });
}

// --- Billing ---

export interface BillingUsage {
  identity_id: string;
  month: string;
  storage: { used_bytes: number; file_count: number; quota_bytes: number };
  compute: {
    total_seconds: number;
    total_jobs: number;
    total_cost_cents: number;
  };
  total_cost_cents: number;
}

export interface BillingHistoryEntry {
  month: string;
  storage_bytes: number;
  compute_seconds: number;
  compute_cost_cents: number;
  total_cost_cents: number;
}

export function getBillingUsage(): Promise<BillingUsage> {
  return apiFetch("/billing/usage");
}

export function getBillingHistory(): Promise<{
  entries: BillingHistoryEntry[];
}> {
  return apiFetch("/billing/history");
}

// --- Plans ---

export interface StoragePlan {
  plan_id: string;
  name: string;
  storage_bytes: number;
  storage_display: string;
  price_cents_per_month: number;
  price_display: string;
}

export function getPlans(): Promise<{ plans: StoragePlan[] }> {
  return apiFetch("/storage/plans");
}

// --- Sync ---

export interface SyncProduct {
  product: string;
  label: string;
  schedule: string;
  last_backup: string;
  last_backup_at: string | null;
  next_backup: string | null;
  bytes_synced: number;
  file_count: number;
  health: "green" | "yellow" | "red" | "gray";
}

export function getSyncStatus(): Promise<{ products: SyncProduct[] }> {
  return apiFetch("/sync/status");
}

// --- Export ---

export interface ExportJobStatus {
  job_id: string;
  status: string;
  total_files: number;
  processed_files: number;
  progress_percent: number;
  download_url?: string;
  expires_at?: string;
  error?: string;
}

export function requestExport(): Promise<ExportJobStatus> {
  return apiFetch("/export/my-data", { method: "POST" });
}

export function getExportStatus(jobId: string): Promise<ExportJobStatus> {
  return apiFetch(`/export/${jobId}`);
}

// --- Auth ---

export function isLoggedIn(): boolean {
  return !!getToken();
}

export function setToken(token: string) {
  localStorage.setItem("windy_jwt", token);
}

export function logout() {
  localStorage.removeItem("windy_jwt");
  window.location.href = "/";
}
