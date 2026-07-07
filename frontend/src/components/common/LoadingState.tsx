import React from 'react';

interface Props {
  label?: string;
}

const LoadingState: React.FC<Props> = ({ label = 'Loading...' }) => (
  <div className="flex items-center justify-center py-12">
    <div className="flex items-center gap-3 text-gray-500">
      <div className="w-5 h-5 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
      <span className="text-sm">{label}</span>
    </div>
  </div>
);

export default LoadingState;
