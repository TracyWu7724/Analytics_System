import React from "react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center h-full text-sm text-red-500 gap-1 p-6 text-center">
          <p className="font-medium">Something went wrong rendering this view.</p>
          <p className="text-xs text-gray-400 font-mono">{this.state.error.message}</p>
        </div>
      );
    }
    return this.props.children;
  }
}
