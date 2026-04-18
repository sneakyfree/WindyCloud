// First-run Cloud Tour (Wave 8) — persisted flag lives here so the
// hook runs in Dashboard without pulling the CloudTour component into
// its module graph.

const TOUR_SEEN_KEY = "windy_cloud_tour_seen";

export function hasSeenCloudTour(): boolean {
  try {
    return localStorage.getItem(TOUR_SEEN_KEY) === "1";
  } catch {
    return true;
  }
}

export function markCloudTourSeen(): void {
  try {
    localStorage.setItem(TOUR_SEEN_KEY, "1");
  } catch {
    // localStorage unavailable (incognito, WebView sandbox) — the tour
    // will just show again next time. Not worth surfacing.
  }
}
