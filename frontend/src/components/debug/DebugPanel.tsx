import React, { useState } from "react";
import { RefreshCw } from "lucide-react";
import { getDiagnostics } from "../../services/diagnosticsService";
import { DiagnosticsSection } from "./DiagnosticsSection";
import { MetricsDashboard } from "./MetricsDashboard";

interface DebugPanelProps {
  onClose: () => void;
}

type PanelTab = "dashboard" | "diagnostics";

export const DebugPanel: React.FC<DebugPanelProps> = ({ onClose }) => {
  const [tab, setTab] = useState<PanelTab>("dashboard");
  const [diagData, setDiagData] = useState<any>(null);
  const [diagLoading, setDiagLoading] = useState(false);

  const runDiag = async () => {
    setDiagLoading(true);
    const data = await getDiagnostics();
    setDiagData(data);
    setDiagLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 overflow-hidden">
      <div className="bg-white rounded-xl shadow-xl flex flex-col w-[520px] max-h-[80vh] overflow-hidden">

        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h2 className="font-semibold text-gray-800 text-sm">Settings</h2>
          <div className="flex items-center gap-2">
            {tab === "diagnostics" && (
              <button
                onClick={runDiag}
                disabled={diagLoading}
                className="p-1.5 rounded hover:bg-gray-100 text-gray-500 disabled:opacity-40"
                title="Refresh"
              >
                <RefreshCw size={14} className={diagLoading ? "animate-spin" : ""} />
              </button>
            )}
            <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 text-gray-500 text-lg leading-none">×</button>
          </div>
        </div>

        <div className="flex px-5 pt-3 gap-4 border-b">
          {([
            { key: "dashboard", label: "Dashboard" },
            { key: "diagnostics", label: "Diagnostics" },
          ] as const).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`pb-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === key
                  ? "border-blue-500 text-blue-600"
                  : "border-transparent text-gray-400 hover:text-gray-600"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {tab === "dashboard" ? (
            <MetricsDashboard />
          ) : (
            <DiagnosticsSection data={diagData} loading={diagLoading} onRun={runDiag} />
          )}
        </div>

      </div>
    </div>
  );
};
