import React, { useState, useRef } from 'react';
import { Upload, FileSpreadsheet, FileText, X } from "lucide-react";
import TablePreview from './TablePreview';
import { ApiService } from '../services/api';

interface SearchBarProps {
  onSearch: (query: string, uploadedTable?: string) => void;
  isLoading: boolean;
}

const SearchBar: React.FC<SearchBarProps> = ({ onSearch, isLoading }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploadedTableName, setUploadedTableName] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [tablePreview, setTablePreview] = useState<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      onSearch(searchQuery.trim(), uploadedTableName || undefined);
    }
  };

  // Function to get the appropriate file icon based on file type
  const getFileIcon = (fileName: string) => {
    const extension = fileName.toLowerCase().split('.').pop();
    if (extension === 'csv') {
      return <FileText className="w-5 h-5 text-green-600" />;
    } else if (extension === 'xlsx' || extension === 'xls') {
      return <FileSpreadsheet className="w-5 h-5 text-green-600" />;
    }
    return <FileText className="w-5 h-5 text-green-600" />;
  };

  // Function to format file size
  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Check file type
    const allowedTypes = ['text/csv', 'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'];
    if (!allowedTypes.includes(file.type) && !file.name.toLowerCase().endsWith('.csv') && !file.name.toLowerCase().endsWith('.xlsx') && !file.name.toLowerCase().endsWith('.xls')) {
      alert('Please upload a CSV or Excel file');
      return;
    }

    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch('http://10.16.56.77:8000/upload', {
        method: 'POST',
        body: formData,
      });

      if (response.ok) {
        const result = await response.json();
        setUploadedFile(file);
        setUploadedTableName(result.table_name);
        
        // Fetch table preview after successful upload
        try {
          const preview = await ApiService.getTablePreview(result.table_name);
          setTablePreview(preview);
        } catch (previewError) {
          console.error('Failed to fetch table preview:', previewError);
        }
      } else {
        const error = await response.text();
        alert(`Upload failed: ${error}`);
      }
    } catch (error) {
      console.error('Upload error:', error);
      alert('Upload failed. Please try again.');
    } finally {
      setIsUploading(false);
      // Clear the file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleFileButtonClick = () => {
    fileInputRef.current?.click();
  };

  const removeUploadedFile = () => {
    setUploadedFile(null);
    setUploadedTableName(null);
    setTablePreview(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSearch(e as any);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center mb-12 py-8 relative w-full max-w-6xl">
      {/* ChatGPT-like File Upload Display */}
      {uploadedFile && (
        <div className="mb-4 max-w-5xl w-full">
          <div className="inline-flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-sm hover:shadow-md transition-shadow">
            {/* File Type Icon */}
            <div className="flex-shrink-0">
              {getFileIcon(uploadedFile.name)}
            </div>
            
            {/* File Info */}
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-medium text-gray-900 truncate">
                {uploadedFile.name}
              </span>
              <span className="text-xs text-gray-500">
                {formatFileSize(uploadedFile.size)}
              </span>
            </div>
            
            {/* Remove Button */}
            <button
              onClick={removeUploadedFile}
              className="flex-shrink-0 p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
              title="Remove file"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      <form onSubmit={handleSearch} className="w-full">
        {/* Advanced Search Bar with Gradient Glow Effect - EXTRA LONG */}
        <div 
          className="relative mx-auto max-w-5xl"
          style={{
            filter: 'drop-shadow(0 10px 20px rgba(17, 61, 115, 0.1))',
          }}
        >
          <div 
            className="relative bg-white rounded-2xl border-4 overflow-hidden transition-all duration-300 hover:scale-[1.02] transform"
            style={{ 
              borderColor: 'rgba(17, 61, 115, 0.2)',
              background: 'linear-gradient(135deg, rgba(255,255,255,0.95) 0%, rgba(248,250,255,0.95) 100%)',
              backdropFilter: 'blur(10px)',
              boxShadow: '0 20px 40px rgba(17, 61, 115, 0.1), 0 1px 3px rgba(17, 61, 115, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.6)'
            }}
          >
            
            <div className="flex items-center px-10 py-3 gap-4">
              {/* Command Icon */}
              <div className="flex-shrink-0">
                <svg className="w-6 h-6 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
              </div>
              
              {/* Search Input - LONG & NARROW */}
              <textarea
                className="flex-1 bg-transparent border-0 focus:ring-0 focus:outline-none text-lg placeholder:text-gray-400 resize-none min-h-[50px] py-3 leading-relaxed w-full"
                placeholder="Enter your text or upload a file for data query..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                style={{ fontFamily: 'inherit', minWidth: '0' }}
              />

              {/* File Upload Button - Integrated */}
              <div className="flex-shrink-0">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={handleFileButtonClick}
                  disabled={isUploading}
                  className="p-2 text-gray-500 hover:text-blue-600 transition-colors disabled:opacity-50"
                  title="Upload CSV or Excel file"
                >
                  {isUploading ? (
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                  ) : (
                    <Upload className="w-5 h-5" />
                  )}
                </button>
              </div>
              
              {/* Execute Button - COMPACT */}
              <button 
                type="submit"
                disabled={isLoading || !searchQuery.trim()}
                className="inline-flex items-center gap-2 px-6 py-3 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium text-base shadow-xl hover:shadow-2xl flex-shrink-0"
                style={{ 
                  backgroundColor: '#113D73',
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#0e3560'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#113D73'}
              >
                {isLoading ? (
                  <svg className="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                ) : (
                  <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                )}
                Execute
              </button>
            </div>
          </div>
        </div>
      </form>

      {/* Table Preview - Below Search Bar */}
      {tablePreview && (
        <div className="mt-6 max-w-5xl w-full">
          <TablePreview
            tableName={tablePreview.table_name}
            columns={tablePreview.columns}
            rows={tablePreview.rows.slice(0, 2)}
            totalRows={tablePreview.total_rows}
            fileName={uploadedFile?.name}
          />
        </div>
      )}
    </div>
  );
};

export default SearchBar; 
