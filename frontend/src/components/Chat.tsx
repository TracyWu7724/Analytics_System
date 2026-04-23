import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, ArrowLeft, Bot, User, Settings, Upload, FileSpreadsheet, FileText, X, ChevronDown } from 'lucide-react';
import { QueryOutput } from './Result';
import Sidebar from './Sidebar';
import { DebugPanel } from './DebugPanel';
import TablePreview from './TablePreview';
import { ApiService } from '../services/api';
import type { ChatMessage } from '../types/chat';
import type { QueryResult, TablePreview as TablePreviewType } from '../types/database';

interface ChatProps {
  initialQuery?: string;
  uploadedTable?: string;
}

const Chat: React.FC<ChatProps> = ({ initialQuery = '', uploadedTable }) => {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const [tablePreview, setTablePreview] = useState<TablePreviewType | null>(null);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploadedTableName, setUploadedTableName] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [pendingFileUpload, setPendingFileUpload] = useState<boolean>(false);
  const [selectedModel, setSelectedModel] = useState<string>('gemini-2.5-flash');
  const [availableModels, setAvailableModels] = useState<{ id: string; display_name: string; provider: string; available: boolean }[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lastProcessedQuery = useRef<string>('');

  // Fetch available LLM models on mount
  useEffect(() => {
    ApiService.getLlmModels().then(({ models, default: defaultModel }) => {
      setAvailableModels(models);
      setSelectedModel(defaultModel);
    });
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (initialQuery && initialQuery !== lastProcessedQuery.current) {
      lastProcessedQuery.current = initialQuery;
      // Add the new query to the conversation (don't clear existing messages)
      handleSendMessage(initialQuery);
      setInputValue('');
    }
  }, [initialQuery]);

  // Fetch table preview when component mounts if there's an uploaded table
  useEffect(() => {
    if (uploadedTable && !tablePreview) {
      const fetchTablePreview = async () => {
        try {
          const preview = await ApiService.getTablePreview(uploadedTable);
          setTablePreview(preview);
          // Set uploadedTableName for consistency
          setUploadedTableName(uploadedTable);
          
          // Create a File-like object for display purposes
          // Use actual metadata from backend if available
          let fileName = uploadedTable.replace('uploaded_', '') + '.csv'; // Default fallback
          let fileType = 'text/csv';
          
          if (preview?.original_filename) {
            fileName = preview.original_filename;
            // Determine file type from extension
            const extension = preview.file_extension || '.csv';
            if (extension === '.xlsx' || extension === '.xls') {
              fileType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
            } else if (extension === '.csv') {
              fileType = 'text/csv';
            }
          }
          
          const fakeFile = new File([''], fileName, { type: fileType });
          setUploadedFile(fakeFile);
          
          // Only create an initial message if there's no initialQuery coming
          // This prevents the "disappearing" effect when navigating from home page
          if (messages.length === 0 && !initialQuery) {
            const initialMessage: ChatMessage = {
              id: Date.now().toString(),
              type: 'user',
              content: `Using uploaded data: ${fileName}`,
              timestamp: new Date(),
              hasFileUpload: true,
            };
            setMessages([initialMessage]);
          }
        } catch (error) {
          console.error('Failed to fetch table preview:', error);
        }
      };
      
      fetchTablePreview();
    }
  }, [uploadedTable, messages.length, initialQuery]);

     const executeQuery = async (query: string, tableToUse?: string): Promise<{ results?: QueryResult[], error?: string, sql_query?: string, warning?: string }> => {
     try {
       setLoadingStep('Analyzing your question...');
       // Add a small delay to show the step
       await new Promise(resolve => setTimeout(resolve, 100));
       
       setLoadingStep('Generating SQL query...');
       await new Promise(resolve => setTimeout(resolve, 100));
       
       setLoadingStep('Executing query...');
       
       // Use the real API service to execute natural language queries
       // Use the explicitly passed table, don't fall back to uploaded tables unless specified
       const result = await ApiService.executeNaturalLanguageQuery(query, tableToUse, selectedModel);
      
      setLoadingStep('Formatting results...');
      await new Promise(resolve => setTimeout(resolve, 200));
      
      return result;
    } catch (error) {
      console.error('Query execution error:', error);
      return {
        error: error instanceof Error ? error.message : 'An unexpected error occurred while executing the query'
      };
    } finally {
      setLoadingStep('');
    }
  };

  const handleSendMessage = async (messageContent: string = inputValue) => {
    if (!messageContent.trim()) return;

    const messageContentLower = messageContent.toLowerCase();

    // Only route to SQL Server when user explicitly mentions Databricks-specific identifiers
    const askingAboutDatabricksTable = !uploadedTableName && !uploadedTable && (
      messageContentLower.includes('das_') ||
      messageContentLower.includes('swks_das_dev') ||
      messageContentLower.includes('databricks')
    );

    // If there is any uploaded table in context (from sidebar click or file upload), always use it
    const hasUploadedData = !!(uploadedTableName || uploadedTable);
    const isFileUploadQuery = hasUploadedData || pendingFileUpload;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: messageContent.trim(),
      timestamp: new Date(),
      hasFileUpload: isFileUploadQuery, // Attach file upload only when relevant
    };

    // Always clear hasFileUpload from previous messages to ensure clean context
    if (isFileUploadQuery) {
      // This message is about uploaded data - show upload preview
      setMessages(prev => [
        ...prev.map(msg => ({ ...msg, hasFileUpload: false })), // Clear from ALL previous messages
        userMessage
      ]);
      if (pendingFileUpload) {
        setPendingFileUpload(false); // Reset pending flag for new uploads
      }
    } else {
      // This message is about Databricks - clear all upload previews
      setMessages(prev => [
        ...prev.map(msg => ({ ...msg, hasFileUpload: false })), // Clear from ALL previous messages
        userMessage
      ]);
    }

    const loadingMessage: ChatMessage = {
      id: (Date.now() + 1).toString(),
      type: 'assistant',
      content: 'Processing your query...',
      timestamp: new Date(),
      isLoading: true,
    };

    setMessages(prev => [...prev, loadingMessage]);
    setInputValue('');
    setIsLoading(true);

    // Fetch table preview if there's an uploaded table and we haven't loaded it yet
    if (uploadedTable && !tablePreview) {
      try {
        const preview = await ApiService.getTablePreview(uploadedTable);
        setTablePreview(preview);
        // Try to extract filename from table name
        const fileName = uploadedTable.replace('uploaded_', '') + (preview.table_name?.includes('.') ? '' : '.xlsx');
        // Note: In SearchBar style, fileName is only used for display when file is uploaded
      } catch (error) {
        console.error('Failed to fetch table preview:', error);
      }
    }

    try {
      // Determine which table to use for the query based on message context
      // Only use uploaded table if this message is specifically about uploaded data
      const tableForQuery = isFileUploadQuery ? (uploadedTableName || uploadedTable) : undefined;
      const { results, error, sql_query, warning } = await executeQuery(messageContent, tableForQuery);
      
      const assistantMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: error 
          ? 'I encountered an error while executing your query.' 
          : results && results.length > 0 
            ? `Found ${results[0].values.length} results for your query.`
            : 'Query executed successfully.',
        timestamp: new Date(),
        results,
        error,
        sql_query,
        warning,
      };

      setMessages(prev => prev.slice(0, -1).concat(assistantMessage));
    } catch (err) {
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: 'An unexpected error occurred.',
        timestamp: new Date(),
        error: 'Connection failed',
      };

      setMessages(prev => prev.slice(0, -1).concat(errorMessage));
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    }
  };

  const handleFileUpload = () => {
    fileInputRef.current?.click();
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

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Check file type
    const allowedTypes = ['text/csv', 'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'];
    if (!allowedTypes.includes(file.type) && !file.name.toLowerCase().endsWith('.csv') && !file.name.toLowerCase().endsWith('.xlsx') && !file.name.toLowerCase().endsWith('.xls')) {
      alert('Please upload a CSV or Excel file');
      return;
    }

    setIsUploading(true);
    try {
      const result = await ApiService.uploadFile(file);
      
      if (result.success) {
        setUploadedFile(file);
        setUploadedTableName(result.table_name || null);
        
        // Refresh table preview if table name is available
        if (result.table_name) {
          try {
            const preview = await ApiService.getTablePreview(result.table_name);
            setTablePreview(preview);
          } catch (previewError) {
            console.warn('Failed to get table preview:', previewError);
          }
        }

        // Set flag to attach upload to next user message
        setPendingFileUpload(true);
      } else {
        alert(`Upload failed: ${result.error}`);
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

  const removeUploadedFile = () => {
    setUploadedFile(null);
    setUploadedTableName(null);
    setTablePreview(null);
    // Clear hasFileUpload flag from all messages
    setMessages(prev => prev.map(msg => ({ ...msg, hasFileUpload: false })));
    setPendingFileUpload(false); // Reset pending file upload flag
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  useEffect(() => {
    adjustTextareaHeight();
  }, [inputValue]);

  return (
    <div className="flex h-screen bg-white text-gray-900 overflow-hidden">
      {/* Sidebar */}
      <Sidebar />
      
      {/* Chat Interface */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
          <button
            onClick={() => navigate('/')}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div className="flex items-center gap-3">
            <div>
              <h1 className="font-semibold text-gray-900">Text-to-SQL Assistant</h1>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {/* LLM model selector */}
            {availableModels.length > 0 && (
              <div className="relative">
                <select
                  value={selectedModel}
                  onChange={e => setSelectedModel(e.target.value)}
                  className="appearance-none pl-3 pr-8 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 cursor-pointer hover:border-gray-300 focus:outline-none focus:ring-2 focus:border-transparent"
                  style={{ focusRingColor: '#113D73' } as React.CSSProperties}
                >
                  {availableModels.map(m => (
                    <option key={m.id} value={m.id} disabled={!m.available}>
                      {m.display_name}{!m.available ? ' (no API key)' : ''}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
              </div>
            )}
            <button
              onClick={() => setShowDebugPanel(true)}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              title="Debug API Connection"
            >
              <Settings className="w-5 h-5 text-gray-600" />
            </button>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <AnimatePresence>
            {messages.length === 0 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-12"
              >
                <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <Bot className="w-8 h-8" style={{ color: '#113D73' }} />
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">
                  Ready to help with your data queries
                </h3>
                <p className="text-gray-500">
                  Ask me anything about your database and I'll generate the SQL for you.
                </p>
              </motion.div>
            )}
            
            {messages.map((message) => (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className={`flex ${
                  message.type === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                <div className="max-w-3xl">
                  <div
                    className={`rounded-2xl px-4 py-3 ${
                      message.type === 'user'
                        ? 'text-white'
                        : 'bg-white border border-gray-200'
                    }`}
                    style={message.type === 'user' ? { backgroundColor: '#113D73' } : {}}
                  >
                    <p className="whitespace-pre-wrap">
                      {message.isLoading ? (loadingStep || message.content) : message.content}
                    </p>
                    {message.isLoading && (
                      <div className="flex items-center gap-2 mt-2">
                        <div className="flex space-x-1">
                          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.3s]"></div>
                          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.15s]"></div>
                          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                        </div>
                      </div>
                    )}
                  </div>
                  
                  {/* Show table preview below user messages when uploaded table exists */}
                  {message.type === 'user' && message.hasFileUpload && tablePreview && !message.isLoading && (
                    <TablePreview
                      tableName={tablePreview.table_name || tablePreview.name}
                      columns={tablePreview.columns}
                      rows={tablePreview.rows || []}
                      totalRows={tablePreview.total_rows || 0}
                      fileName={uploadedFile?.name || (uploadedTableName || uploadedTable)?.replace('uploaded_', '') + '.xlsx'}
                    />
                  )}
                  
                  {/* Query Results */}
                  {(message.results || message.error) && !message.isLoading && (
                    <div className="mt-4">
                      <QueryOutput
                        results={message.results || []}
                        error={message.error || ''}
                        sql_query={message.sql_query}
                        warning={message.warning}
                        onClose={() => {
                          // Remove the results from this message
                          setMessages(prev => prev.map(msg => 
                            msg.id === message.id 
                              ? { ...msg, results: undefined, error: undefined, sql_query: undefined, warning: undefined }
                              : msg
                          ));
                        }}
                      />
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 bg-white p-4">
          {/* File Upload Display - SearchBar Style */}
          {uploadedFile && (
            <div className="max-w-4xl mx-auto mb-3">
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
          
          <div className="flex items-center gap-4 max-w-4xl mx-auto">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask me about your data..."
                className="w-full px-4 py-3 pr-12 border border-gray-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:border-transparent"
                style={{ 
                  minHeight: '48px', 
                  maxHeight: '120px'
                }}
                disabled={isLoading}
              />
              
              {/* File Upload Button */}
              <button
                onClick={handleFileUpload}
                disabled={isLoading || isUploading}
                className="absolute right-3 top-1/2 transform -translate-y-1/2 p-2 text-gray-500 hover:text-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Upload CSV or Excel file"
              >
                {isUploading ? (
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                ) : (
                  <Upload className="w-5 h-5" />
                )}
              </button>
              
              {/* Hidden File Input */}
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileChange}
                accept=".csv,.xlsx,.xls"
                className="hidden"
              />
            </div>
            
            <button
              onClick={() => handleSendMessage()}
              disabled={!inputValue.trim() || isLoading}
              className="px-4 py-3 text-white rounded-xl hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
              style={{ 
                backgroundColor: '#113D73',
                height: '48px'
              }}
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>

      {/* Debug Panel */}
      {showDebugPanel && (
        <DebugPanel onClose={() => setShowDebugPanel(false)} />
      )}
    </div>
  );
};

export default Chat; 
