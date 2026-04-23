import React, { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Database, Table, BarChart3, RefreshCw } from "lucide-react";

interface TableInfo {
  name: string;
  rows: number;
  columns: string[];
}

interface TablesResponse {
  tables: TableInfo[];
  total_tables: number;
}

interface TableListProps {
  refreshTrigger?: number;
}

const TableList: React.FC<TableListProps> = ({ refreshTrigger }) => {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTables = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch('http://10.16.56.77:8000/list-tables');
      if (!response.ok) {
        throw new Error('Failed to fetch tables');
      }
      
      const data: TablesResponse = await response.json();
      setTables(data.tables);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tables');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTables();
  }, []);

  useEffect(() => {
    if (refreshTrigger && refreshTrigger > 0) {
      fetchTables();
    }
  }, [refreshTrigger]);

  if (tables.length === 0 && !loading && !error) {
    return null; // Don't show anything if no tables
  }

  if (loading && tables.length === 0) {
    return null; // Don't show loading state initially
  }

  return (
    <div className="w-full max-w-4xl mx-auto mb-8">
      <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Database className="h-5 w-5 text-blue-600" />
            <h3 className="text-lg font-semibold text-gray-900">
              Available Data Tables
            </h3>
          </div>
          
          <motion.button
            onClick={fetchTables}
            disabled={loading}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </motion.button>
        </div>

        {error && (
          <div className="text-red-600 text-sm mb-4 p-3 bg-red-50 rounded-lg">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          </div>
        ) : (
          <div className="grid gap-3">
            {tables.map((table, index) => (
              <motion.div
                key={table.name}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.1 }}
                className="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <Table className="h-5 w-5 text-gray-600" />
                  <div>
                    <h4 className="font-medium text-gray-900 capitalize">
                      {table.name.replace(/_/g, ' ')}
                    </h4>
                    <p className="text-sm text-gray-600">
                      {table.columns.length} columns • {table.rows.toLocaleString()} rows
                    </p>
                  </div>
                </div>
                
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <BarChart3 className="h-4 w-4" />
                  <span className="hidden sm:inline">
                    {table.columns.slice(0, 3).join(', ')}
                    {table.columns.length > 3 && ` +${table.columns.length - 3} more`}
                  </span>
                </div>
              </motion.div>
            ))}
          </div>
        )}

        {tables.length > 0 && (
          <div className="mt-4 text-center text-sm text-gray-500">
            {tables.length} table{tables.length !== 1 ? 's' : ''} available for querying
          </div>
        )}
      </div>
    </div>
  );
};

export default TableList; 