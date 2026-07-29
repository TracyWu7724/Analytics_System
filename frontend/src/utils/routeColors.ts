// Fixed categorical order — never reassigned by rank, so a route keeps its
// color as other routes come and go. Shared across every dashboard so the
// same route always reads as the same color.
export const ROUTE_ORDER = ["sql", "rag", "both", "schema", "unknown"] as const;

export const ROUTE_COLORS_TW: Record<string, string> = {
  sql: "bg-blue-500",
  rag: "bg-violet-500",
  both: "bg-teal-500",
  schema: "bg-amber-500",
  unknown: "bg-gray-400",
};

export const ROUTE_COLORS_HEX: Record<string, string> = {
  sql: "#3b82f6",
  rag: "#8b5cf6",
  both: "#14b8a6",
  schema: "#f59e0b",
  unknown: "#9ca3af",
};

export function routeColorTw(route: string): string {
  return ROUTE_COLORS_TW[route] ?? ROUTE_COLORS_TW.unknown;
}

export function routeColorHex(route: string): string {
  return ROUTE_COLORS_HEX[route] ?? ROUTE_COLORS_HEX.unknown;
}
