import React from "react";
import { StatusDot } from "./StatusDot";
import type { DiagStatus } from "./StatusDot";

type DiagRowProps = {
  icon: React.ReactNode;
  label: string;
  status: DiagStatus | boolean;
  detail?: string;
};

export default function DiagRow({ icon, label, status, detail }: DiagRowProps) {
  return (
    <div className="flex items-start gap-3 py-3 border-b last:border-0">
      <div className="mt-0.5 text-gray-400">{icon}</div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-700">{label}</span>
          <StatusDot status={status} />
        </div>

        {detail && (
          <p className="text-xs text-gray-500 mt-0.5 truncate">{detail}</p>
        )}
      </div>
    </div>
  );
}
