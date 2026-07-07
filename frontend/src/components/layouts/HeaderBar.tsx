// Top header bar with three slots: left, center, right. Each slot accepts any ReactNode.
// Callers control what goes in each slot; this component only handles placement.
import type { ReactNode } from "react";

type HeaderBarProps = {
  left?: ReactNode;
  center?: ReactNode;
  right?: ReactNode;
};

export default function HeaderBar({ left, center, right }: HeaderBarProps) {
  return (
    <header className="bg-white px-6 py-4 flex items-center">
      <div className="flex items-center">{left}</div>

      <div className="flex-1 flex justify-center">{center}</div>

      <div className="ml-auto flex items-center gap-2">{right}</div>
    </header>
  );
}