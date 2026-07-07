// Full-page shell: sidebar on the left, header + scrollable main content on the right.
// Every page wraps its content in this component instead of rebuilding the chrome.
import type { ReactNode } from "react";
import Sidebar from "../Sidebar";
import HeaderBar from "./HeaderBar";

type AppLayoutProps = {
  headerLeft?: ReactNode;
  headerCenter?: ReactNode;
  headerRight?: ReactNode;
  children: ReactNode;
};

export default function AppLayout({
  headerLeft,
  headerCenter,
  headerRight,
  children,
}: AppLayoutProps) {
  return (
    <div className="flex min-h-screen bg-white text-gray-900">
      <Sidebar />

      <div className="flex-1 flex flex-col">
        <HeaderBar
          left={headerLeft}
          center={headerCenter}
          right={headerRight}
        />

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}