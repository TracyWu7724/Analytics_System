import React, { useMemo, useRef } from "react";
import { Play, Flag, Shuffle, Search, Code2, Database, ShieldCheck, Combine, List, GitBranch } from "lucide-react";
import type { TraceSpan } from "../../services/traceService";
import { stepColorHex, PHASE_LEGEND } from "../../utils/stepColors";

interface TraceGraphProps {
  spans: TraceSpan[];
  route: string | null;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}

type IconType = React.ComponentType<{ className?: string; style?: React.CSSProperties }>;

const STEP_ICON: Record<string, IconType> = {
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

function stepIcon(step: string): IconType {
  return STEP_ICON[step] ?? Shuffle;
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

// Label for the sibling route that the router didn't take, shown as a
// grayed-out "path not taken" branch off the router node.
const ALT_ROUTE_LABEL: Record<string, string> = {
  sql: "RAG Path",
  rag: "SQL Path",
  schema: "SQL / RAG Path",
};

// ---- fixed geometry for the abstract canvas (px) ----
const CANVAS_W = 680;
const CENTER_X = 320;
const NODE_W = 208;
const NODE_H = 56;
const PILL_W = 160;
const PILL_H = 44;
const GHOST_W = 168;
const GHOST_H = 44;
const ROW_H = 100;
const FORK_W = 170;
const FORK_GAP = 24;

type NodeKind = "start" | "end" | "step" | "ghost";

interface GraphNode {
  id: string;
  kind: NodeKind;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sub?: string;
  spanIndex?: number;
  color: string;
  Icon: IconType;
}

interface GraphEdge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  dashed?: boolean;
}

interface Layout {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
}

function buildLayout(spans: TraceSpan[], route: string | null): Layout {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const mainX = CENTER_X - NODE_W / 2;
  let row = 0;

  const startY = row * ROW_H;
  nodes.push({
    id: "start", kind: "start", x: CENTER_X - PILL_W / 2, y: startY, w: PILL_W, h: PILL_H,
    label: "Start", color: "#9ca3af", Icon: Play,
  });
  row++;

  const hasFork =
    spans.length >= 2 &&
    spans[spans.length - 2].step === "validating" &&
    spans[spans.length - 1].step === "synthesizing";
  const linearSpans = hasFork ? spans.slice(0, -2) : spans;

  let prevBottom = { x: CENTER_X, y: startY + PILL_H };
  linearSpans.forEach((s, i) => {
    const y = row * ROW_H;
    edges.push({ x1: prevBottom.x, y1: prevBottom.y, x2: CENTER_X, y2: y });
    nodes.push({
      id: `span-${i}`, kind: "step", x: mainX, y, w: NODE_W, h: NODE_H,
      label: s.label.replace(/\.\.\.$/, ""), sub: formatMs(s.duration_ms),
      spanIndex: i, color: stepColorHex(s.step), Icon: stepIcon(s.step),
    });
    prevBottom = { x: CENTER_X, y: y + NODE_H };

    if (i === 0 && s.step === "route" && route && ALT_ROUTE_LABEL[route]) {
      const ghostX = mainX + NODE_W + 56;
      const ghostY = y + (NODE_H - GHOST_H) / 2;
      nodes.push({
        id: "ghost", kind: "ghost", x: ghostX, y: ghostY, w: GHOST_W, h: GHOST_H,
        label: ALT_ROUTE_LABEL[route], color: "#9ca3af", Icon: GitBranch,
      });
      edges.push({
        x1: mainX + NODE_W, y1: y + NODE_H / 2, x2: ghostX, y2: ghostY + GHOST_H / 2, dashed: true,
      });
    }
    row++;
  });

  if (hasFork) {
    const leftIdx = spans.length - 2;
    const rightIdx = spans.length - 1;
    const leftX = CENTER_X - FORK_W - FORK_GAP / 2;
    const rightX = CENTER_X + FORK_GAP / 2;
    const y = row * ROW_H;

    nodes.push({
      id: "fork-left", kind: "step", x: leftX, y, w: FORK_W, h: NODE_H,
      label: spans[leftIdx].label.replace(/\.\.\.$/, ""), sub: formatMs(spans[leftIdx].duration_ms),
      spanIndex: leftIdx, color: stepColorHex(spans[leftIdx].step), Icon: stepIcon(spans[leftIdx].step),
    });
    nodes.push({
      id: "fork-right", kind: "step", x: rightX, y, w: FORK_W, h: NODE_H,
      label: spans[rightIdx].label.replace(/\.\.\.$/, ""), sub: formatMs(spans[rightIdx].duration_ms),
      spanIndex: rightIdx, color: stepColorHex(spans[rightIdx].step), Icon: stepIcon(spans[rightIdx].step),
    });

    edges.push({ x1: prevBottom.x, y1: prevBottom.y, x2: leftX + FORK_W / 2, y2: y });
    edges.push({ x1: prevBottom.x, y1: prevBottom.y, x2: rightX + FORK_W / 2, y2: y });
    edges.push({ x1: leftX + FORK_W, y1: y + NODE_H / 2, x2: rightX, y2: y + NODE_H / 2, dashed: true });

    row++;
    const endY = row * ROW_H;
    edges.push({ x1: leftX + FORK_W / 2, y1: y + NODE_H, x2: CENTER_X, y2: endY });
    edges.push({ x1: rightX + FORK_W / 2, y1: y + NODE_H, x2: CENTER_X, y2: endY });
    prevBottom = { x: CENTER_X, y: endY };
  }

  const endY = row * ROW_H;
  edges.push({ x1: prevBottom.x, y1: prevBottom.y, x2: CENTER_X, y2: endY });
  nodes.push({
    id: "end", kind: "end", x: CENTER_X - PILL_W / 2, y: endY, w: PILL_W, h: PILL_H,
    label: "End", color: "#22c55e", Icon: Flag,
  });
  row++;

  return { nodes, edges, width: CANVAS_W, height: row * ROW_H + 24 };
}

function edgePath(e: GraphEdge): string {
  if (Math.abs(e.x1 - e.x2) < 1 || Math.abs(e.y1 - e.y2) < 1) {
    return `M ${e.x1} ${e.y1} L ${e.x2} ${e.y2}`;
  }
  const midY = (e.y1 + e.y2) / 2;
  return `M ${e.x1} ${e.y1} C ${e.x1} ${midY}, ${e.x2} ${midY}, ${e.x2} ${e.y2}`;
}

function NodeCard({ node, active, onSelect }: { node: GraphNode; active: boolean; onSelect: (i: number) => void }) {
  const { Icon } = node;
  const style: React.CSSProperties = { left: node.x, top: node.y, width: node.w, height: node.h };

  if (node.kind === "start" || node.kind === "end") {
    const tone = node.kind === "end" ? "border-green-200 bg-green-50" : "border-gray-200 bg-gray-50";
    const iconTone = node.kind === "end" ? "bg-green-100 text-green-600" : "bg-gray-100 text-gray-400";
    return (
      <div className={`absolute rounded-xl border px-3 py-2 flex items-center gap-2 ${tone}`} style={style}>
        <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${iconTone}`}>
          <Icon className="w-3.5 h-3.5" />
        </div>
        <p className={`text-xs font-medium ${node.kind === "end" ? "text-green-700" : "text-gray-700"}`}>{node.label}</p>
      </div>
    );
  }

  if (node.kind === "ghost") {
    return (
      <div
        className="absolute rounded-xl border border-dashed border-gray-300 bg-gray-50/70 px-2.5 py-2 flex items-center gap-2 opacity-70"
        style={style}
        title="Path not taken"
      >
        <div className="w-6 h-6 rounded-lg bg-gray-100 flex items-center justify-center shrink-0">
          <Icon className="w-3 h-3 text-gray-400" />
        </div>
        <p className="text-[11px] font-medium text-gray-400 truncate">{node.label}</p>
      </div>
    );
  }

  return (
    <button
      onClick={() => node.spanIndex != null && onSelect(node.spanIndex)}
      className={`absolute rounded-xl border px-2.5 py-2 flex items-center gap-2 text-left transition-colors ${
        active ? "border-blue-400 bg-blue-50 shadow-sm" : "border-gray-200 bg-white hover:border-gray-300"
      }`}
      style={style}
    >
      <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: `${node.color}1a` }}>
        <Icon className="w-3.5 h-3.5" style={{ color: node.color }} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-gray-800 truncate leading-tight">{node.label}</p>
        {node.sub && <p className="text-[11px] text-gray-400 tabular-nums leading-tight">{node.sub}</p>}
      </div>
    </button>
  );
}

function Minimap({ layout, viewportRef }: { layout: Layout; viewportRef: React.RefObject<HTMLDivElement> }) {
  const MM_W = 128;
  const MM_H = 100;
  const scale = Math.min((MM_W - 8) / layout.width, (MM_H - 8) / layout.height);
  const offX = (MM_W - layout.width * scale) / 2;
  const offY = (MM_H - layout.height * scale) / 2;

  const jumpTo = (e: React.MouseEvent<SVGSVGElement>) => {
    const el = viewportRef.current;
    if (!el) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientY - rect.top) / rect.height;
    el.scrollTop = frac * el.scrollHeight - el.clientHeight / 2;
  };

  return (
    <div className="w-32 h-[100px] rounded-lg border border-gray-200 bg-white/90 shadow-sm backdrop-blur-sm overflow-hidden">
      <svg width={MM_W} height={MM_H} onClick={jumpTo} className="cursor-pointer">
        <g transform={`translate(${offX}, ${offY}) scale(${scale})`}>
          {layout.edges.map((e, i) => (
            <line key={i} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke="#d1d5db" strokeWidth={4} />
          ))}
          {layout.nodes.map((n) => (
            <rect
              key={n.id}
              x={n.x}
              y={n.y}
              width={n.w}
              height={n.h}
              rx={6}
              fill={n.kind === "ghost" ? "none" : n.color}
              stroke={n.kind === "ghost" ? "#9ca3af" : "none"}
              strokeDasharray={n.kind === "ghost" ? "6 4" : undefined}
              opacity={n.kind === "ghost" ? 0.5 : n.kind === "start" || n.kind === "end" ? 0.5 : 0.85}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}

export function TraceGraph({ spans, route, selectedIndex, onSelect }: TraceGraphProps) {
  const layout = useMemo(() => buildLayout(spans, route), [spans, route]);
  const viewportRef = useRef<HTMLDivElement>(null);

  return (
    <div>
      <div className="relative">
        <div ref={viewportRef} className="max-h-[560px] overflow-auto rounded-lg bg-gray-50/40">
          <div className="relative mx-auto" style={{ width: layout.width, height: layout.height }}>
            <svg width={layout.width} height={layout.height} className="absolute inset-0 pointer-events-none">
              <defs>
                <marker id="trace-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M0,0 L8,4 L0,8 z" fill="#cbd5e1" />
                </marker>
              </defs>
              {layout.edges.map((e, i) => (
                <path
                  key={i}
                  d={edgePath(e)}
                  fill="none"
                  stroke="#cbd5e1"
                  strokeWidth={1.5}
                  strokeDasharray={e.dashed ? "4 3" : undefined}
                  markerEnd={e.dashed ? undefined : "url(#trace-arrow)"}
                />
              ))}
            </svg>
            {layout.nodes.map((n) => (
              <NodeCard key={n.id} node={n} active={n.spanIndex != null && n.spanIndex === selectedIndex} onSelect={onSelect} />
            ))}
          </div>
        </div>

        <div className="absolute bottom-3 right-3 z-10">
          <Minimap layout={layout} viewportRef={viewportRef} />
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
