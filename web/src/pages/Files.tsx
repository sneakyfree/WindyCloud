import {
  ArrowUpDown,
  Download,
  Folder,
  Search,
  Trash2,
  Upload,
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
  { key: "", label: "All Files" },
  { key: "windy_chat", label: "Chat Archives" },
  { key: "windy_mail", label: "Mail Archives" },
  { key: "windy_pro", label: "Recordings" },
  { key: "windy_fly", label: "Agent Backups" },
  { key: "windy_code", label: "Code Settings" },
  { key: "general", label: "General" },
];

type SortKey = "filename" | "size_bytes" | "created_at" | "product";

export default function Files() {
  const [data, setData] = useState<FileListResponse | null>(null);
  const [product, setProduct] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("created_at");
  const [sortAsc, setSortAsc] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    listFiles({ product: product || undefined, limit: 200 })
      .then(setData)
      .catch(() => {});
  }, [product]);

  useEffect(() => {
    load();
  }, [load]);

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    for (const f of Array.from(files)) {
      await uploadFile(f, product || "general").catch(() => {});
    }
    setUploading(false);
    load();
  };

  const handleDelete = async (f: FileInfo) => {
    if (!confirm(`Delete ${f.filename}?`)) return;
    await deleteFile(f.file_id).catch(() => {});
    load();
  };

  const handleSort = (key: SortKey) => {
    if (sort === key) setSortAsc(!sortAsc);
    else {
      setSort(key);
      setSortAsc(key === "filename");
    }
  };

  let files = data?.files || [];

  // Search filter
  if (search) {
    const q = search.toLowerCase();
    files = files.filter(
      (f) =>
        f.filename.toLowerCase().includes(q) ||
        productLabel(f.product).toLowerCase().includes(q)
    );
  }

  // Sort
  files = [...files].sort((a, b) => {
    let cmp = 0;
    if (sort === "filename") cmp = a.filename.localeCompare(b.filename);
    else if (sort === "size_bytes") cmp = a.size_bytes - b.size_bytes;
    else if (sort === "created_at")
      cmp =
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    else if (sort === "product") cmp = a.product.localeCompare(b.product);
    return sortAsc ? cmp : -cmp;
  });

  const SortHeader = ({
    label,
    field,
  }: {
    label: string;
    field: SortKey;
  }) => (
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

      <div className="flex gap-4">
        {/* Sidebar — product folders */}
        <div className="w-48 flex-shrink-0 space-y-0.5">
          {PRODUCTS.map((p) => (
            <button
              key={p.key}
              onClick={() => setProduct(p.key)}
              className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-left cursor-pointer transition-colors ${
                product === p.key
                  ? "bg-[var(--accent)] text-white"
                  : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)]"
              }`}
            >
              <Folder className="w-4 h-4" />
              {p.label}
            </button>
          ))}
        </div>

        {/* File list */}
        <div className="flex-1 space-y-3">
          {/* Search */}
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

          {/* Drop zone + table */}
          <div
            className={`bg-[var(--bg-card)] rounded-xl border overflow-hidden transition-colors ${
              dragOver
                ? "border-[var(--accent)] bg-[var(--accent)]/5"
                : "border-[var(--border)]"
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
              <div className="p-8 text-center text-[var(--accent)]">
                Drop files to upload
              </div>
            )}
            {!dragOver && files.length === 0 ? (
              <p className="p-8 text-center text-[var(--text-muted)]">
                {data ? "No files. Drag and drop to upload." : "Loading..."}
              </p>
            ) : !dragOver ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)] text-[var(--text-muted)] text-left">
                    <SortHeader label="Name" field="filename" />
                    <SortHeader label="Product" field="product" />
                    <SortHeader label="Size" field="size_bytes" />
                    <SortHeader label="Date" field="created_at" />
                    <th className="px-4 py-3 font-medium w-24">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((f) => (
                    <tr
                      key={f.file_id}
                      className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)]"
                    >
                      <td className="px-4 py-3 font-medium">{f.filename}</td>
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
                          <button
                            onClick={() =>
                              downloadFile(f.file_id, f.filename)
                            }
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
                  ))}
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
    </div>
  );
}
