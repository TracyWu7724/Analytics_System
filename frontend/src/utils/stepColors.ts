// Fixed categorical order for pipeline step keys — same idea as routeColors.ts.
// Grouped by pipeline phase so a trace reads as router → sql → rag → synthesis
// even before you read the labels.
export const STEP_COLORS_HEX: Record<string, string> = {
  route: "#9ca3af",       // router — gray
  listing: "#9ca3af",     // schema node — gray
  routing: "#60a5fa",     // sql: table selection — blue-400
  columns: "#3b82f6",     // sql: column retrieval — blue-500
  generating: "#2563eb",  // sql: SQL generation — blue-600
  executing: "#4f46e5",   // sql: SQL execution — indigo-600
  validating: "#14b8a6",  // sql/rag: result validation — teal-500
  retrieving: "#8b5cf6",  // rag: retrieval — violet-500
  synthesizing: "#f59e0b", // hybrid synthesis — amber-500
};

export function stepColorHex(step: string): string {
  return STEP_COLORS_HEX[step] ?? "#9ca3af";
}

// Phase grouping for the graph legend — several step keys collapse into one
// human-readable phase (e.g. "routing"+"columns" are both SQL planning).
export const STEP_PHASE: Record<string, string> = {
  route: "Router",
  listing: "Router",
  routing: "Planning",
  columns: "Planning",
  generating: "Generation",
  executing: "Tool / DB",
  retrieving: "Retrieval",
  validating: "Verification",
  synthesizing: "Synthesis",
};

export const PHASE_LEGEND: { phase: string; color: string }[] = [
  { phase: "Router", color: STEP_COLORS_HEX.route },
  { phase: "Planning", color: STEP_COLORS_HEX.routing },
  { phase: "Generation", color: STEP_COLORS_HEX.generating },
  { phase: "Tool / DB", color: STEP_COLORS_HEX.executing },
  { phase: "Retrieval", color: STEP_COLORS_HEX.retrieving },
  { phase: "Verification", color: STEP_COLORS_HEX.validating },
  { phase: "Synthesis", color: STEP_COLORS_HEX.synthesizing },
];

export function stepPhase(step: string): string {
  return STEP_PHASE[step] ?? "Other";
}
