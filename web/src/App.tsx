import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { isLoggedIn } from "./api";
import Layout from "./Layout";
import Billing from "./pages/Billing";
import CloudTour from "./pages/CloudTour";
import Compute from "./pages/Compute";
import Dashboard from "./pages/Dashboard";
import DeepLink from "./pages/DeepLink";
import Files from "./pages/Files";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Servers from "./pages/Servers";
import SettingsPage from "./pages/SettingsPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  if (!isLoggedIn()) {
    // Carry the intended destination through the login wall. Without this,
    // "Choose Ultra" on windycloud.com landed here as /billing?plan=translate,
    // bounced to /login with the query DROPPED, and after signing in the user
    // was sent to the home page — the entire buy funnel died at the door for
    // every new customer.
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/d/:target" element={<DeepLink />} />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/tour" element={<CloudTour />} />
          <Route path="/files" element={<Files />} />
          <Route path="/compute" element={<Compute />} />
          <Route path="/servers" element={<Servers />} />
          <Route path="/billing" element={<Billing />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
