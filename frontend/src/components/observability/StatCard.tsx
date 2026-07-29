import React from "react";

interface StatCardProps {
  icon: React.ComponentType<{ className?: string }>;
  iconColor: string; // tailwind text-* class
  iconBg: string; // tailwind bg-* class
  label: string;
  value: string;
  sub?: string;
}

export function StatCard({ icon: Icon, iconColor, iconBg, label, value, sub }: StatCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white px-4 py-3.5">
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${iconBg}`}>
          <Icon className={`w-4 h-4 ${iconColor}`} />
        </div>
        <span className="text-sm text-gray-500">{label}</span>
      </div>
      <p className="text-2xl font-semibold text-gray-900 leading-tight">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}
