import React from 'react';
import { FileSpreadsheet, FileText } from 'lucide-react';

interface TablePreviewProps {
  tableName: string;
  columns: string[];
  rows: any[];
  totalRows: number;
  fileName?: string;
}

const TablePreview: React.FC<TablePreviewProps> = ({ 
  tableName, 
  columns, 
  rows, 
  totalRows, 
  fileName 
}) => {
  // Determine file type icon
  const getFileIcon = () => {
    if (fileName) {
      const extension = fileName.toLowerCase().split('.').pop();
      if (extension === 'csv') {
        return <FileText className="w-4 h-4 text-blue-600" />;
      } else if (extension === 'xlsx' || extension === 'xls') {
        return <FileSpreadsheet className="w-4 h-4 text-green-600" />;
      }
    }
    return <FileSpreadsheet className="w-4 h-4 text-blue-600" />;
  };

  // Format table name for display
  const getDisplayName = () => {
    if (fileName) return fileName;
    return tableName.replace('uploaded_', '').replace(/_/g, ' ');
  };

  if (!rows || rows.length === 0) {
    return (
      <div className="mt-3 p-3 bg-gray-50 border border-gray-200 rounded-lg">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          {getFileIcon()}
          <span>No data available in {getDisplayName()}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 bg-white border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {getFileIcon()}
            <span className="text-sm font-medium text-gray-900">
              {getDisplayName()}
            </span>
          </div>
          <span className="text-xs text-gray-500">
            Showing {rows.length} of {totalRows} rows
          </span>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              {columns.map((column, index) => (
                <th
                  key={index}
                  className="px-4 py-2 text-left font-medium text-gray-900 border-b border-gray-200"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr 
                key={rowIndex} 
                className={rowIndex % 2 === 0 ? 'bg-white' : 'bg-gray-50'}
              >
                {columns.map((column, colIndex) => (
                  <td 
                    key={colIndex} 
                    className="px-4 py-2 text-gray-700 border-b border-gray-100"
                  >
                    {row[column] !== null && row[column] !== undefined 
                      ? String(row[column]) 
                      : '-'
                    }
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TablePreview; 
