import React from 'react';

interface Props {
  title: string;
  description?: string;
  icon?: React.ReactNode;
}

const EmptyState: React.FC<Props> = ({ title, description, icon }) => (
  <div className="flex flex-col items-center justify-center py-12 gap-2 text-center">
    {icon && <div className="mb-2 text-gray-300">{icon}</div>}
    <p className="font-medium text-gray-600">{title}</p>
    {description && <p className="text-sm text-gray-400 max-w-sm">{description}</p>}
  </div>
);

export default EmptyState;
