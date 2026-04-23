import React, { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, FileSpreadsheet, FileText, CheckCircle, XCircle, AlertCircle, X, File as FileIcon } from "lucide-react";
import { getApiUrl } from "../config/api";

interface UploadStatus {
  type: 'idle' | 'uploading' | 'success' | 'error';
  message?: string;
  fileName?: string;
}

interface FileUploadProps {
  onUploadSuccess?: () => void;
}

const FileUpload: React.FC<FileUploadProps> = ({ onUploadSuccess }) => {
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>({ type: 'idle' });
  const [dragActive, setDragActive] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0]);
    }
  };

  const handleFile = async (file: File) => {
    // Validate file type
    const allowedTypes = [
      'text/csv',
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    ];
    
    const allowedExtensions = ['.csv', '.xls', '.xlsx'];
    const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
    
    if (!allowedTypes.includes(file.type) && !allowedExtensions.includes(fileExtension)) {
      setUploadStatus({
        type: 'error',
        message: 'Please upload a CSV or Excel file (.csv, .xls, .xlsx)',
        fileName: file.name
      });
      return;
    }

    // Check file size (max 10MB)
    if (file.size > 10 * 1024 * 1024) {
      setUploadStatus({
        type: 'error',
        message: 'File size must be less than 10MB',
        fileName: file.name
      });
      return;
    }

    setUploadStatus({
      type: 'uploading',
      message: 'Uploading and processing file...',
      fileName: file.name
    });

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(getApiUrl('/upload'), {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Upload failed');
      }

      const result = await response.json();
      setUploadedFile(file);
      setUploadStatus({
        type: 'success',
        message: `Successfully uploaded ${result.row_count} rows to table "${result.table_name}"`,
        fileName: file.name
      });

      // Clear file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }

      // Trigger table list refresh
      if (onUploadSuccess) {
        onUploadSuccess();
      }

    } catch (error) {
      setUploadStatus({
        type: 'error',
        message: error instanceof Error ? error.message : 'Upload failed',
        fileName: file.name
      });
    }
  };

  const onButtonClick = () => {
    fileInputRef.current?.click();
  };

  const resetStatus = () => {
    setUploadStatus({ type: 'idle' });
    setUploadedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const removeUploadedFile = () => {
    setUploadedFile(null);
    setUploadStatus({ type: 'idle' });
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <div className="w-full max-w-2xl mx-auto mb-8">
      {/* ChatGPT-like File Display */}
      {uploadedFile && uploadStatus.type === 'success' && (
        <div className="mb-4">
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
                {formatFileSize(uploadedFile.size)} • Uploaded successfully
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

      <div
        className={`relative border-2 border-dashed rounded-2xl p-8 transition-all duration-300 ${
          dragActive 
            ? 'border-blue-400 bg-blue-50' 
            : 'border-gray-300 hover:border-gray-400'
        }`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".csv,.xls,.xlsx"
          onChange={handleChange}
        />

        <div className="text-center">
          <motion.div
            animate={{ scale: dragActive ? 1.1 : 1 }}
            transition={{ duration: 0.2 }}
            className="mb-4"
          >
            <Upload className="mx-auto h-12 w-12 text-gray-400" />
          </motion.div>

          <h3 className="text-lg font-semibold text-gray-900 mb-2">
            Upload Data File
          </h3>
          
          <p className="text-gray-600 mb-4">
            Drag and drop your CSV or Excel file here, or click to browse
          </p>

          <motion.button
            onClick={onButtonClick}
            disabled={uploadStatus.type === 'uploading'}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <FileIcon className="w-5 h-5" />
            Choose File
          </motion.button>

          <p className="text-sm text-gray-500 mt-3">
            Supports CSV, XLS, XLSX files up to 10MB
          </p>
        </div>
      </div>

      {/* Upload Status */}
      <AnimatePresence>
        {uploadStatus.type !== 'idle' && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className={`mt-4 p-4 rounded-lg flex items-start gap-3 ${
              uploadStatus.type === 'success' ? 'bg-green-50 border border-green-200' :
              uploadStatus.type === 'error' ? 'bg-red-50 border border-red-200' :
              'bg-blue-50 border border-blue-200'
            }`}
          >
            <div className="flex-shrink-0 mt-0.5">
              {uploadStatus.type === 'uploading' && (
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
              )}
              {uploadStatus.type === 'success' && (
                <CheckCircle className="h-5 w-5 text-green-600" />
              )}
              {uploadStatus.type === 'error' && (
                <XCircle className="h-5 w-5 text-red-600" />
              )}
            </div>
            
            <div className="flex-1">
              <p className={`font-medium ${
                uploadStatus.type === 'success' ? 'text-green-800' :
                uploadStatus.type === 'error' ? 'text-red-800' :
                'text-blue-800'
              }`}>
                {uploadStatus.fileName}
              </p>
              <p className={`text-sm ${
                uploadStatus.type === 'success' ? 'text-green-600' :
                uploadStatus.type === 'error' ? 'text-red-600' :
                'text-blue-600'
              }`}>
                {uploadStatus.message}
              </p>
            </div>

            {uploadStatus.type !== 'uploading' && (
              <button
                onClick={resetStatus}
                className="flex-shrink-0 text-gray-400 hover:text-gray-600"
              >
                <XCircle className="h-5 w-5" />
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default FileUpload; 
