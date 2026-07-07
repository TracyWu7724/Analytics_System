import React from 'react';
import { Zap, Database, BookOpen } from 'lucide-react';

export const ROUTE_META: Record<string, { label: string; Icon: React.FC<any>; color: string; bg: string }> = {
  sql:    { label: 'Text2SQL',            Icon: Database, color: 'text-blue-700',   bg: 'bg-blue-50 border-blue-200' },
  rag:    { label: 'Product Manuals RAG', Icon: BookOpen, color: 'text-green-700',  bg: 'bg-green-50 border-green-200' },
  both:   { label: 'Text2SQL + RAG',      Icon: Zap,      color: 'text-purple-700', bg: 'bg-purple-50 border-purple-200' },
};

interface Props {
  route: string;
  reasoning?: string;
}

export const RouteBadge: React.FC<Props> = ({ route, reasoning }) => {
  const meta = ROUTE_META[route] ?? ROUTE_META.sql;
  const { label, Icon, color, bg } = meta;
  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${bg} ${color}`}
      title={reasoning}
    >
      <Icon className="w-3 h-3" />
      {label}
    </div>
  );
};

export default RouteBadge;
