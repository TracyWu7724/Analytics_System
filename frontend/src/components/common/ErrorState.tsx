import React from 'react';
import { AlertCircle } from 'lucide-react';

interface Props {
  message: string;
  onRetry?: () => void;
}

const ErrorState: React.FC<Props> = ({ message, onRetry }) => (
  <div className="flex flex-col items-center justify-center py-12 gap-3">
    <AlertCircle className="w-8 h-8 text-red-400" />
    <p className="text-sm text-gray-600 text-center max-w-sm">{message}</p>
    {onRetry && (
      <button
        onClick={onRetry}
        className="text-sm px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
      >
        Retry
      </button>
    )}
  </div>
);

export default ErrorState;
