import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { isLoggedIn } from "./api";
import Layout from "./Layout";
import Billing from "./pages/Billing";
import Compute from "./pages/Compute";
import Dashboard from "./pages/Dashboard";
import Files from "./pages/Files";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Servers from "./pages/Servers";
import SettingsPage from "./pages/SettingsPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isLoggedIn()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<Dashboard />} />
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
