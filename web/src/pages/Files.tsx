import {
  ArrowUpDown,
  Download,
  Eye,
  FileText,
  Folder,
  FolderOpen,
  Image,
  MessageSquare,
  Music,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  type FileInfo,
  type FileListResponse,
  deleteFile,
  downloadFile,
  listFiles,
  uploadFile,
} from "../api";
import {
  formatBytes,
  formatDateTime,
  productColor,
  productLabel,
} from "../util";

const PRODUCTS = [
  { key: "", label: "All Files", icon: Folder },
  { key: "windy_chat", label: "Chat Archives", icon: MessageSquare },
  { key: "windy_mail", label: "Mail Archives", icon: FileText },
  { key: "windy_pro", label: "Recordings", icon: Music },
  { key: "windy_fly", label: "Agent Backups", icon: FolderOpen },
  { key: "windy_code", label: "Code Settings", icon: FileText },
  { key: "general", label: "General", icon: Folder },
];

type SortKey = "filename" | "size_bytes" | "created_at" | "product";

interface UploadProgress {
  name: string;
  progress: number;
  done: boolean;
  error?: string;
}

function fileIcon(contentType: string) {
  if (contentType.startsWith("image/")) return Image;
  if (contentType.startsWith("audio/")) return Music;
  return FileText;
}

function canPreview(contentType: string): boolean {
  return (
    contentType.startsWith("text/") ||
    contentType.startsWith("image/") ||
    contentType.startsWith("audio/") ||
    contentType === "application/json" ||
    contentType === "application/pdf"
  );
}

export default function Files() {
  const [data, setData] = useState<FileListResponse | null>(null);
  const [product, setProduct] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("created_at");
  const [sortAsc, setSortAsc] = useState(false);
  const [uploads, setUploads] = useState<UploadProgress[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState<{
    file: FileInfo;
    url: string;
    text?: string;
  } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    listFiles({ product: product || undefined, limit: 200 })
      .then(setData)
      .catch(() => {});
  }, [product]);

  useEffect(() => {
    load();
  }, [load]);

  const handleUpload = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    const files = Array.from(fileList);
    const progress: UploadProgress[] = files.map((f) => ({
      name: f.name,
      progress: 0,
      done: false,
    }));
    setUploads(progress);

    for (let i = 0; i < files.length; i++) {
      progress[i].progress = 30;
      setUploads([...progress]);
      try {
        await uploadFile(files[i], product || "general");
        progress[i].progress = 100;
        progress[i].done = true;
      } catch {
        progress[i].progress = 100;
        progress[i].done = true;
        progress[i].error = "Failed";
      }
      setUploads([...progress]);
    }
    load();
    setTimeout(() => setUploads([]), 2000);
  };

  const handleDelete = async (f: FileInfo) => {
    if (!confirm(`Delete ${f.filename}?`)) return;
    await deleteFile(f.file_id).catch(() => {});
    load();
  };

  const handlePreview = async (f: FileInfo) => {
    if (!canPreview(f.content_type)) {
      downloadFile(f.file_id, f.filename);
      return;
    }
    const res = await fetch(`/api/v1/storage/files/${f.file_id}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("windy_jwt")}` },
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    let text: string | undefined;
    if (f.content_type.startsWith("text/") || f.content_type === "application/json") {
      text = await blob.text();
    }
    setPreview({ file: f, url, text });
  };

  const closePreview = () => {
    if (preview) URL.revokeObjectURL(preview.url);
    setPreview(null);
  };

  const handleSort = (key: SortKey) => {
    if (sort === key) setSortAsc(!sortAsc);
    else {
      setSort(key);
      setSortAsc(key === "filename");
    }
  };

  let files = data?.files || [];
  if (search) {
    const q = search.toLowerCase();
    files = files.filter(
      (f) =>
        f.filename.toLowerCase().includes(q) ||
        productLabel(f.product).toLowerCase().includes(q)
    );
  }
  files = [...files].sort((a, b) => {
    let cmp = 0;
    if (sort === "filename") cmp = a.filename.localeCompare(b.filename);
    else if (sort === "size_bytes") cmp = a.size_bytes - b.size_bytes;
    else if (sort === "created_at")
      cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    else if (sort === "product") cmp = a.product.localeCompare(b.product);
    return sortAsc ? cmp : -cmp;
  });

  const uploading = uploads.length > 0 && uploads.some((u) => !u.done);

  const SortHeader = ({ label, field }: { label: string; field: SortKey }) => (
    <th
      className="px-4 py-3 font-medium cursor-pointer select-none hover:text-[var(--text)]"
      onClick={() => handleSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown className="w-3 h-3" />
      </span>
    </th>
  );

  // --- Empty state for file browser ---
  const EmptyFiles = () => (
    <div className="p-10 text-center">
      <FolderOpen className="w-16 h-16 mx-auto mb-4 text-[var(--text-muted)] opacity-40" />
      <p className="text-lg font-medium mb-2">No files yet</p>
      <p className="text-sm text-[var(--text-muted)] mb-6 max-w-md mx-auto">
        Files from your Windy products sync here automatically.
        You can also drag and drop files to upload manually.
      </p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 max-w-lg mx-auto">
        {PRODUCTS.filter((p) => p.key && p.key !== "general").map((p) => {
          const Icon = p.icon;
          return (
            <div
              key={p.key}
              className="flex flex-col items-center gap-1.5 p-3 rounded-lg bg-[var(--bg-hover)] opacity-50"
            >
              <Icon className="w-5 h-5" style={{ color: productColor(p.key) }} />
              <span className="text-xs text-[var(--text-muted)]">{p.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Files</h1>
        <button
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm hover:bg-[var(--accent-hover)] transition-colors disabled:opacity-50 cursor-pointer"
        >
          <Upload className="w-4 h-4" />
          {uploading ? "Uploading..." : "Upload"}
        </button>
        <input
          ref={fileInput}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => handleUpload(e.target.files)}
        />
      </div>

      {/* Upload progress bars */}
      {uploads.length > 0 && (
        <div className="space-y-1.5">
          {uploads.map((u, i) => (
            <div key={i} className="flex items-center gap-3 text-sm">
              <span className="truncate w-48 text-[var(--text-muted)]">{u.name}</span>
              <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-hover)] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${u.progress}%`,
                    background: u.error ? "var(--red)" : "var(--accent)",
                  }}
                />
              </div>
              <span className="text-xs text-[var(--text-muted)] w-12 text-right">
                {u.error ? "Error" : u.done ? "Done" : `${u.progress}%`}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-4">
        {/* Sidebar — product folders */}
        <div className="w-48 flex-shrink-0 space-y-0.5">
          {PRODUCTS.map((p) => {
            const Icon = p.icon;
            return (
              <button
                key={p.key}
                onClick={() => setProduct(p.key)}
                className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-left cursor-pointer transition-colors ${
                  product === p.key
                    ? "bg-[var(--accent)] text-white"
                    : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)]"
                }`}
              >
                <Icon className="w-4 h-4" />
                {p.label}
              </button>
            );
          })}
        </div>

        {/* File list */}
        <div className="flex-1 space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" />
            <input
              type="text"
              placeholder="Search files..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)]"
            />
          </div>

          <div
            className={`bg-[var(--bg-card)] rounded-xl border overflow-hidden transition-colors ${
              dragOver ? "border-[var(--accent)] bg-[var(--accent)]/5" : "border-[var(--border)]"
            }`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              handleUpload(e.dataTransfer.files);
            }}
          >
            {dragOver && (
              <div className="p-8 text-center text-[var(--accent)]">Drop files to upload</div>
            )}
            {!dragOver && files.length === 0 ? (
              data ? (
                <EmptyFiles />
              ) : (
                <p className="p-8 text-center text-[var(--text-muted)]">Loading...</p>
              )
            ) : !dragOver ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)] text-[var(--text-muted)] text-left">
                    <SortHeader label="Name" field="filename" />
                    <SortHeader label="Product" field="product" />
                    <SortHeader label="Size" field="size_bytes" />
                    <SortHeader label="Date" field="created_at" />
                    <th className="px-4 py-3 font-medium w-28">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((f) => {
                    const Icon = fileIcon(f.content_type);
                    return (
                      <tr
                        key={f.file_id}
                        className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)]"
                      >
                        <td className="px-4 py-3 font-medium">
                          <span className="inline-flex items-center gap-2">
                            <Icon className="w-4 h-4 text-[var(--text-muted)]" />
                            {f.filename}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className="inline-block px-2 py-0.5 rounded text-xs"
                            style={{
                              background: productColor(f.product) + "22",
                              color: productColor(f.product),
                            }}
                          >
                            {productLabel(f.product)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-[var(--text-muted)]">
                          {formatBytes(f.size_bytes)}
                        </td>
                        <td className="px-4 py-3 text-[var(--text-muted)]">
                          {formatDateTime(f.created_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex gap-1">
                            {canPreview(f.content_type) && (
                              <button
                                onClick={() => handlePreview(f)}
                                className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--accent)] cursor-pointer"
                                title="Preview"
                              >
                                <Eye className="w-4 h-4" />
                              </button>
                            )}
                            <button
                              onClick={() => downloadFile(f.file_id, f.filename)}
                              className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--accent)] cursor-pointer"
                              title="Download"
                            >
                              <Download className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDelete(f)}
                              className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--red)] cursor-pointer"
                              title="Delete"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
          </div>

          {data && (
            <p className="text-xs text-[var(--text-muted)]">
              {data.total} file{data.total !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      </div>

      {/* Preview modal */}
      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] w-full max-w-2xl max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
              <div>
                <p className="font-medium">{preview.file.filename}</p>
                <p className="text-xs text-[var(--text-muted)]">
                  {formatBytes(preview.file.size_bytes)} &middot;{" "}
                  {preview.file.content_type}
                </p>
              </div>
              <button
                onClick={closePreview}
                className="p-1.5 rounded hover:bg-[var(--bg-hover)] cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {preview.text !== undefined && (
                <pre className="text-sm whitespace-pre-wrap font-mono text-[var(--text)] bg-[var(--bg)] p-4 rounded-lg overflow-auto max-h-[60vh]">
                  {preview.text.slice(0, 50000)}
                </pre>
              )}
              {preview.file.content_type.startsWith("image/") && (
                <img
                  src={preview.url}
                  alt={preview.file.filename}
                  className="max-w-full max-h-[60vh] mx-auto rounded-lg"
                />
              )}
              {preview.file.content_type.startsWith("audio/") && (
                <div className="flex items-center justify-center py-8">
                  <audio controls src={preview.url} className="w-full max-w-md" />
                </div>
              )}
              {preview.file.content_type === "application/pdf" && (
                <iframe
                  src={preview.url}
                  className="w-full h-[60vh] rounded-lg"
                  title="PDF Preview"
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
