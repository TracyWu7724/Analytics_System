import React, { useState } from "react";
import { RefreshCw } from "lucide-react";
import { getDiagnostics } from "../../services/diagnosticsService";
import { DiagnosticsSection } from "./DiagnosticsSection";

interface DebugPanelProps {
  onClose: () => void;
}

export const DebugPanel: React.FC<DebugPanelProps> = ({ onClose }) => {
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
          <h2 className="font-semibold text-gray-800 text-sm">System Diagnostics</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={runDiag}
              disabled={diagLoading}
              className="p-1.5 rounded hover:bg-gray-100 text-gray-500 disabled:opacity-40"
              title="Refresh"
            >
              <RefreshCw size={14} className={diagLoading ? "animate-spin" : ""} />
            </button>
            <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 text-gray-500 text-lg leading-none">×</button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <DiagnosticsSection data={diagData} loading={diagLoading} onRun={runDiag} />
        </div>

      </div>
    </div>
  );
};
