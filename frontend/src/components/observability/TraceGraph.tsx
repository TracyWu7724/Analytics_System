import React from "react";
import { Play, Flag, Shuffle, Search, Code2, Database, ShieldCheck, Combine, List } from "lucide-react";
import type { TraceSpan } from "../../services/traceService";
import { stepColorHex, PHASE_LEGEND } from "../../utils/stepColors";

interface TraceGraphProps {
  spans: TraceSpan[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}

const STEP_ICON: Record<string, React.ComponentType<{ className?: string; style?: React.CSSProperties }>> = {
  route: Shuffle,
  listing: List,
  routing: Search,
  columns: Search,
  generating: Code2,
  executing: Database,
  validating: ShieldCheck,
  retrieving: Search,
  synthesizing: Combine,
};

function stepIcon(step: string): React.ComponentType<{ className?: string; style?: React.CSSProperties }> {
  return STEP_ICON[step] ?? Shuffle;
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function Connector() {
  return (
    <div className="flex flex-col items-center py-0.5">
      <div className="w-px h-5 bg-gray-300" />
      <div className="w-2 h-2 border-b border-r border-gray-300 rotate-45 -mt-1.5" />
    </div>
  );
}

export function TraceGraph({ spans, selectedIndex, onSelect }: TraceGraphProps) {
  return (
    <div>
      <div className="flex flex-col items-center">
        {/* Start */}
        <div className="w-40 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gray-100 flex items-center justify-center shrink-0">
            <Play className="w-3.5 h-3.5 text-gray-400" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium text-gray-700">Start</p>
          </div>
        </div>
        <Connector />

        {spans.map((s, i) => {
          const color = stepColorHex(s.step);
          const active = selectedIndex === i;
          const Icon = stepIcon(s.step);
          return (
            <React.Fragment key={i}>
              <button
                onClick={() => onSelect(i)}
                className={`w-56 rounded-xl border px-3 py-2.5 flex items-center gap-2.5 text-left transition-colors ${
                  active ? "border-blue-400 bg-blue-50 shadow-sm" : "border-gray-200 bg-white hover:border-gray-300"
                }`}
              >
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                  style={{ backgroundColor: `${color}1a` }}
                >
                  <Icon className="w-4 h-4" style={{ color }} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-800 truncate">{s.label.replace(/\.\.\.$/, "")}</p>
                  <p className="text-xs text-gray-400 tabular-nums">{formatMs(s.duration_ms)}</p>
                </div>
              </button>
              {i < spans.length - 1 && <Connector />}
            </React.Fragment>
          );
        })}

        <Connector />
        <div className="w-40 rounded-xl border border-green-200 bg-green-50 px-3 py-2 flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-green-100 flex items-center justify-center shrink-0">
            <Flag className="w-3.5 h-3.5 text-green-600" />
          </div>
          <p className="text-xs font-medium text-green-700">End</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 mt-5 pt-3 border-t border-gray-100">
        {PHASE_LEGEND.map(({ phase, color }) => (
          <span key={phase} className="flex items-center gap-1.5 text-xs text-gray-500">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
            {phase}
          </span>
        ))}
      </div>
    </div>
  );
}
