import { CheckCircle, AlertCircle, XCircle } from "lucide-react";

export type DiagStatus = "ok" | "error" | "misconfigured" | "not_configured" | "index_missing";

export function StatusDot({ status }: { status: DiagStatus | boolean }) {
  const ok = status === "ok" || status === true;
  const warn = status === "misconfigured" || status === "not_configured" || status === "index_missing";
  if (ok) return <CheckCircle size={14} className="text-green-500 shrink-0" />;
  if (warn) return <AlertCircle size={14} className="text-amber-400 shrink-0" />;
  return <XCircle size={14} className="text-red-500 shrink-0" />;
}
