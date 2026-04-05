# Windy Cloud — Visual Stress Test Audit

**Date:** 2026-04-04
**Build:** `npm run build` → 266KB JS + 20KB CSS (gzipped: 80KB + 4.6KB)
**Backend:** 108 tests passing, ruff clean

---

## Page-by-Page Audit

### /login
- [x] Renders: Cloud icon, "Windy Cloud" heading, JWT input, Sign In button
- [x] Empty state: JWT placeholder text "Paste your Windy Pro JWT..."
- [x] Auth flow: paste token → Save → redirect to /
- [x] Links to windyword.ai (domain migration verified)

### / (Dashboard)
- [x] Storage usage bar: shows used/quota with color coding (green/yellow/red)
- [x] Compute stats: job count this month
- [x] Total cost: formatted as $X.XX
- [x] Donut chart: SVG renders per-product breakdown with branded colors
- [x] Sync status: fetches from /api/v1/sync/status, shows health colors
- [x] "Download My Data" button: triggers background export job with progress
- [x] Upgrade prompt: renders at 70%/90% with CTA
- [x] Empty state: "Your Windy Cloud is empty" with 5 product cards
- [x] Quick actions: Upload Files → /files, Manage Plan → /billing

### /files (File Browser)
- [x] Product folder sidebar: 7 folders with icons (Chat, Mail, Recordings, Agent, Code, General, All)
- [x] Click folder: filters file list by product
- [x] Search bar: filters by filename and product label
- [x] Sort headers: click to sort by name/product/size/date
- [x] Upload button: opens file picker, supports multiple files
- [x] Drag-and-drop: "Drop files to upload" overlay
- [x] Upload progress: per-file progress bars with name + percentage
- [x] File type icons: image/audio/document context-aware
- [x] Preview button (eye icon): text/JSON renders in monospace, images as thumbnail, audio with controls, PDF in iframe
- [x] Download button: triggers file download
- [x] Delete button: confirmation dialog, file disappears
- [x] Empty state: folder icons with "Files sync here automatically"
- [x] File count: "X files" at bottom

### /compute
- [x] STT jobs count this month
- [x] Minutes used with progress bar
- [x] Free minutes remaining
- [x] Cost this month
- [x] Info card: provider, model, free tier details

### /servers
- [x] Empty state: "No servers provisioned yet" with icon
- [x] Server cards: status dot (green/red/yellow), plan, region, cost, IP
- [x] Actions: Start/Stop/Reboot/Destroy buttons
- [x] Dashboard link: opens IP:3000 in new tab
- [x] Refresh button

### /billing
- [x] Storage/Compute/Total breakdown cards
- [x] Billing history table (month, storage, compute, total)
- [x] Plan cards (Free, Basic, Pro, Ultra) with pricing
- [x] Empty state: "No billing history yet"

### /settings
- [x] JWT token input with save
- [x] Auto-sync toggle
- [x] Retention days selector (30/90/180/365/forever)
- [x] Connected services list with status dots
- [x] Sign Out button

### 404 (any invalid route)
- [x] "Page Not Found" with back to dashboard link

---

## Issues Found & Fixed

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | HTML `<title>` was "web" not "Windy Cloud" | Medium | **FIXED** |
| 2 | No 404 catch-all route — invalid URLs showed blank page | Medium | **FIXED** — NotFound.tsx added |
| 3 | API errors silently swallowed (`.catch(() => {})`) — no user feedback | High | **FIXED** — Toast notification system added, 401/403 auto-logout |
| 4 | Dead `exportAllData` function in api.ts (replaced by background job) | Low | **FIXED** — removed |
| 5 | Missing `<meta description>` tag | Low | **FIXED** |
| 6 | No toast/feedback on upload success/failure | Medium | **FIXED** — apiFetch shows toast on error |

## Items Verified Working (no fix needed)

- Dark theme renders correctly (CSS vars applied)
- Tailwind classes compile properly
- All 7 routes load without blank pages
- All API calls include Bearer auth
- SVG donut chart renders with correct segments
- File preview modal works for text, images, audio
- Drag-and-drop upload zone shows visual feedback
- Product folder sidebar filters correctly
- Search works across filenames and product labels
- Sort toggles ascending/descending
- Responsive layout: sidebar + main content

## Build Stats

| Metric | Value |
|--------|-------|
| JS bundle | 266 KB (80 KB gzipped) |
| CSS bundle | 20 KB (4.6 KB gzipped) |
| Total pages | 8 (Dashboard, Files, Compute, Servers, Billing, Settings, Login, 404) |
| Components | 10 (Layout, Toast, DonutChart, EmptyFiles, SortHeader, etc.) |
| API functions | 22 |
| TypeScript | Clean (no errors) |
| Backend tests | 108 passing |
