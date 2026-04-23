import React, { useState } from 'react';
import { ApiService } from '../services/api';
import { getApiUrl } from '../config/api';

interface DebugPanelProps {
  onClose: () => void;
}

interface TestResult {
  name: string;
  status: 'pending' | 'success' | 'error';
  message?: string;
  duration?: number;
}

export const DebugPanel: React.FC<DebugPanelProps> = ({ onClose }) => {
  const [tests, setTests] = useState<TestResult[]>([]);
  const [isRunning, setIsRunning] = useState(false);

  const updateTest = (name: string, update: Partial<TestResult>) => {
    setTests(prev => 
      prev.map(test => 
        test.name === name ? { ...test, ...update } : test
      )
    );
  };

  const runDiagnostics = async () => {
    setIsRunning(true);
    const testList: TestResult[] = [
      { name: 'Basic Connectivity', status: 'pending' },
      { name: 'Health Check', status: 'pending' },
      { name: 'Simple Query', status: 'pending' },
      { name: 'SQL Generation', status: 'pending' },
    ];
    setTests(testList);

    // Test 1: Basic connectivity
    try {
      const start = Date.now();
      const response = await fetch(getApiUrl('/'), { 
        method: 'GET',
        signal: AbortSignal.timeout(5000)
      });
      const duration = Date.now() - start;
      
      if (response.ok) {
        updateTest('Basic Connectivity', { 
          status: 'success', 
          message: `Connected successfully (${duration}ms)`, 
          duration 
        });
      } else {
        updateTest('Basic Connectivity', { 
          status: 'error', 
          message: `HTTP ${response.status}: ${response.statusText}` 
        });
      }
    } catch (error) {
      updateTest('Basic Connectivity', { 
        status: 'error', 
        message: error instanceof Error ? error.message : 'Connection failed' 
      });
    }

    // Test 2: Health check
    try {
      const start = Date.now();
      const health = await ApiService.healthCheck();
      const duration = Date.now() - start;
      
      updateTest('Health Check', { 
        status: 'success', 
        message: `Database: ${health.database}, Tables: ${health.tables_count} (${duration}ms)`,
        duration 
      });
    } catch (error) {
      updateTest('Health Check', { 
        status: 'error', 
        message: error instanceof Error ? error.message : 'Health check failed' 
      });
    }

    // Test 3: Simple query
    try {
      const start = Date.now();
      const result = await ApiService.executeNaturalLanguageQuery('show tables');
      const duration = Date.now() - start;
      
      if (result.error) {
        updateTest('Simple Query', { 
          status: 'error', 
          message: result.error 
        });
      } else {
        updateTest('Simple Query', { 
          status: 'success', 
          message: `Query executed successfully (${duration}ms)`,
          duration 
        });
      }
    } catch (error) {
      updateTest('Simple Query', { 
        status: 'error', 
        message: error instanceof Error ? error.message : 'Query failed' 
      });
    }

    // Test 4: SQL generation only
    try {
      const start = Date.now();
      const result = await ApiService.generateSQL('show me all tables');
      const duration = Date.now() - start;
      
      if (result.error) {
        updateTest('SQL Generation', { 
          status: 'error', 
          message: result.error 
        });
      } else {
        updateTest('SQL Generation', { 
          status: 'success', 
          message: `SQL generated: ${result.sql_query?.substring(0, 50)}... (${duration}ms)`,
          duration 
        });
      }
    } catch (error) {
      updateTest('SQL Generation', { 
        status: 'error', 
        message: error instanceof Error ? error.message : 'SQL generation failed' 
      });
    }

    setIsRunning(false);
  };

  const getStatusIcon = (status: TestResult['status']) => {
    switch (status) {
      case 'pending': return '⏳';
      case 'success': return '✅';
      case 'error': return '❌';
    }
  };

  const getStatusColor = (status: TestResult['status']) => {
    switch (status) {
      case 'pending': return 'text-yellow-600';
      case 'success': return 'text-green-600';
      case 'error': return 'text-red-600';
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-auto">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">API Debug Panel</h2>
          <button 
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 text-xl"
          >
            ×
          </button>
        </div>

        <div className="mb-4">
          <p className="text-sm text-gray-600 mb-2">
            API URL: <code className="bg-gray-100 px-2 py-1 rounded">{getApiUrl('/')}</code>
          </p>
          <button
            onClick={runDiagnostics}
            disabled={isRunning}
            className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 disabled:opacity-50"
          >
            {isRunning ? 'Running Tests...' : 'Run Diagnostics'}
          </button>
        </div>

        {tests.length > 0 && (
          <div className="space-y-3">
            {tests.map((test, index) => (
              <div key={index} className="border rounded p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="text-lg">{getStatusIcon(test.status)}</span>
                    <span className="font-medium">{test.name}</span>
                  </div>
                  {test.duration && (
                    <span className="text-xs text-gray-500">{test.duration}ms</span>
                  )}
                </div>
                {test.message && (
                  <p className={`text-sm mt-1 ${getStatusColor(test.status)}`}>
                    {test.message}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="mt-6 text-sm text-gray-600">
          <h3 className="font-medium mb-2">Troubleshooting Tips:</h3>
          <ul className="list-disc list-inside space-y-1">
            <li>Make sure FastAPI is running: <code>python app.py</code></li>
            <li>Check the backend console for error messages</li>
            <li>Verify your Google API key is set in the backend</li>
            <li>Ensure the database file exists and is accessible</li>
            <li>Check browser console for additional error details</li>
          </ul>
        </div>
      </div>
    </div>
  );
}; 