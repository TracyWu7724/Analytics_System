import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Zap, ArrowLeft, Activity, Clock, CheckCircle2, DollarSign, GitBranch,
  AlertTriangle, FileText,
} from "lucide-react";
import { useAuth } from "../../hooks/useAuth";

interface NavItem {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  to?: string; // present = live route; absent = disabled stub
}

const MONITOR: NavItem[] = [
  { key: "overview", label: "Overview", icon: Activity, to: "/observability" },
  { key: "latency", label: "Latency", icon: Clock, to: "/latency" },
  { key: "quality", label: "Quality", icon: CheckCircle2, to: "/quality" },
  { key: "traces", label: "Traces", icon: GitBranch, to: "/traces" },
];

const ANALYZE: NavItem[] = [
  { key: "alerts", label: "Alerts", icon: AlertTriangle },
  { key: "reports", label: "Reports", icon: FileText },
];

function NavSection({ title, items }: { title: string; items: NavItem[] }) {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="mb-5">
      <p className="px-3 mb-1.5 text-[11px] font-semibold tracking-wide text-gray-400">{title}</p>
      <div className="space-y-0.5">
        {items.map(({ key, label, icon: Icon, to }) => {
          const active = !!to && location.pathname === to;
          return (
            <button
              key={key}
              disabled={!to}
              title={to ? undefined : "Coming soon"}
              onClick={() => to && navigate(to)}
              className={`w-full flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                active
                  ? "bg-blue-50 text-blue-700 font-medium"
                  : to
                    ? "text-gray-600 hover:bg-gray-50"
                    : "text-gray-400 cursor-not-allowed opacity-60"
              }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ObservabilitySidebar() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const initials = user ? user.username.slice(0, 2).toUpperCase() : "?";

  return (
    <aside className="w-60 shrink-0 h-screen border-r border-gray-200 bg-white flex flex-col">
      <div className="px-4 py-4 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: "#113D73" }}>
            <Zap className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900 text-sm">Analytics Agent</span>
        </div>
        <button
          onClick={() => navigate("/agent")}
          className="mt-3 flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to chat
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-4">
        <NavSection title="MONITOR" items={MONITOR} />
        <NavSection title="ANALYZE" items={ANALYZE} />
      </nav>

      {user && (
        <div className="px-4 py-3 border-t border-gray-100 flex items-center gap-2.5">
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold text-white shrink-0"
            style={{ backgroundColor: "#113D73" }}
          >
            {initials}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium text-gray-800 truncate">{user.username}</p>
            <p className="text-[11px] text-gray-400 capitalize">{user.role}</p>
          </div>
        </div>
      )}
    </aside>
  );
}
