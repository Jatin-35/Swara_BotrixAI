import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Leads from "./pages/Leads";
import CallHistory from "./pages/CallHistory";
import Campaign from "./pages/Campaign";

// Reusable protected route
function ProtectedRoute({ children }) {
  const isLoggedIn = localStorage.getItem("auth") === "true";
  return isLoggedIn ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>

          {/* Login Route */}
          <Route
            path="/login"
            element={
              localStorage.getItem("auth") === "true"
                ? <Navigate to="/dashboard" replace />
                : <Login />
            }
          />

          {/* Dashboard (Protected) */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />

          {/* Leads (Protected) */}
          <Route
            path="/leads"
            element={
              <ProtectedRoute>
                <Leads />
              </ProtectedRoute>
            }
          />

          {/* Call History (Protected) */}
          <Route
            path="/call-history"
            element={
              <ProtectedRoute>
                <CallHistory />
              </ProtectedRoute>
            }
          />

          {/* Campaign (Protected) */}
          <Route
            path="/campaign"
            element={
              <ProtectedRoute>
                <Campaign />
              </ProtectedRoute>
            }
          />

          {/* Default redirect */}
          <Route path="*" element={<Navigate to="/login" replace />} />

        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
