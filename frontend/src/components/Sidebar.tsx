import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Table, Search, PanelRightOpen, PanelLeftClose } from "lucide-react";
import { queryHistoryService } from "../services/queryHistoryService";

interface TableInfo {
  name: string;
  columns: { name: string; type: string }[];
  row_count: number;
  is_uploaded: boolean;
}

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [recentQueries, setRecentQueries] = useState<string[]>([]);
  const [tables, setTables] = useState<TableInfo[]>([]);

  useEffect(() => {
    loadRecentQueries();
    fetchTablesWithRetry();

    // Refresh recent queries when localStorage changes (cross-tab or same-tab updates)
    const handleStorage = () => loadRecentQueries();
    window.addEventListener('storage', handleStorage);
    window.addEventListener('queryHistoryUpdated', handleStorage);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener('queryHistoryUpdated', handleStorage);
    };
  }, []);

  const loadRecentQueries = () => {
    const queries = queryHistoryService.getRecentQueries().slice(0, 10);
    setRecentQueries(queries.map(q => q.query));
  };

  const fetchTables = async (): Promise<boolean> => {
    try {
      const response = await fetch('http://localhost:8000/tables');
      if (response.ok) {
        const data = await response.json();
        const loaded = data.tables || [];
        setTables(loaded);
        return loaded.length > 0;
      }
    } catch (error) {
      console.log('Failed to fetch tables:', error);
    }
    return false;
  };

  const fetchTablesWithRetry = async () => {
    for (let i = 0; i < 5; i++) {
      const ok = await fetchTables();
      if (ok) return;
      await new Promise(r => setTimeout(r, 2000));
    }
  };

  const handleQueryClick = (query: string) => {
    navigate(`/chat?query=${encodeURIComponent(query)}`);
  };

  const handleTableClick = (tableName: string) => {
    navigate(`/chat?uploaded_table=${encodeURIComponent(tableName)}`);
  };

  const formatQueryDisplay = (query: string, maxLength: number = 35) => {
    return query.length > maxLength ? `${query.substring(0, maxLength)}...` : query;
  };

  const formatTableName = (tableName: string) => {
    if (tableName.startsWith('uploaded_')) {
      return tableName.replace('uploaded_', '').replace(/_/g, ' ');
    }
    return tableName.replace(/_/g, ' ');
  };

  const frequentQueries = [
    "What is the totalUSD by category of operationsExpenses.projectedOPEX?",
    "What is the totalUSD by location of operationsExpenses.projectedOPEX?",
    "Show me all records of operationsExpenses.projectedOPEX",
    "Show me records of DAS_NPI_Development_Cost_EBR",
  ];

  const uploadedTables = tables.filter(table => table.is_uploaded);

  // ── Collapsed view ────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <aside className="w-14 bg-gray-100 text-gray-700 min-h-screen flex flex-col items-center pt-4 gap-3 flex-shrink-0">
        {/* Expand */}
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded-lg hover:bg-gray-200 transition-colors"
          title="Expand sidebar"
        >
          <PanelRightOpen className="w-5 h-5" style={{ color: '#113D73' }} />
        </button>

        {/* New query */}
        <button
          onClick={() => navigate('/')}
          className="p-2 rounded-lg hover:bg-gray-200 transition-colors"
          title="New Data Query"
        >
          <Search className="w-5 h-5" style={{ color: '#113D73' }} />
        </button>
      </aside>
    );
  }

  // ── Expanded view ─────────────────────────────────────────────────────────
  return (
    <aside className="w-72 bg-gray-100 text-gray-700 min-h-screen flex flex-col flex-shrink-0">
      {/* Collapse button */}
      <div className="flex justify-end px-4 pt-4">
        <button
          onClick={() => setCollapsed(true)}
          className="p-1.5 rounded-lg hover:bg-gray-200 transition-colors"
          title="Collapse sidebar"
        >
          <PanelLeftClose className="w-5 h-5 text-gray-500" />
        </button>
      </div>

      {/* Scrollable Navigation Section */}
      <div className="flex-1 overflow-y-auto px-8 pb-8 pt-2">
        <nav className="flex flex-col space-y-8">
          <div className="space-y-2">
            <button
              onClick={() => navigate('/')}
              className="flex items-center space-x-3 hover:text-gray-900 transition-colors w-full text-left"
            >
              <svg className="w-6 h-6 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
              </svg>
              <span className="font-bold" style={{ color: '#113D73' }}>New Data Query</span>
            </button>
          </div>

          {/* Frequently Searched */}
          <div className="space-y-2">
            <div className="flex items-center space-x-3">
              <svg className="w-6 h-6 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
              </svg>
              <span className="font-bold" style={{ color: '#113D73' }}>Frequently Searched</span>
            </div>
            {frequentQueries.map((query, index) => (
              <button
                key={index}
                onClick={() => handleQueryClick(query)}
                className="block hover:text-gray-900 hover:bg-gray-200 transition-colors text-sm pl-9 py-1 rounded w-full text-left"
              >
                {formatQueryDisplay(query)}
              </button>
            ))}
          </div>

          {/* Recent Queries */}
          <div className="space-y-2">
            <div className="flex items-center space-x-3">
              <svg className="w-6 h-6 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
                <path fillRule="evenodd" d="M4 5a2 2 0 012-2v1a1 1 0 001 1h6a1 1 0 001-1V3a2 2 0 012 2v10a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z" clipRule="evenodd" />
              </svg>
              <span className="font-bold" style={{ color: '#113D73' }}>Recent Queries</span>
            </div>
            {recentQueries.length > 0 ? (
              recentQueries.map((query, index) => (
                <button
                  key={index}
                  onClick={() => handleQueryClick(query)}
                  className="block hover:text-gray-900 hover:bg-gray-200 transition-colors text-sm pl-9 py-1 rounded w-full text-left"
                  title={query}
                >
                  {formatQueryDisplay(query)}
                </button>
              ))
            ) : (
              <p className="text-sm text-gray-500 pl-9">No recent queries</p>
            )}
          </div>

          {/* Demo Tables */}
          {uploadedTables.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center space-x-3">
                <Table className="w-6 h-6 flex-shrink-0" style={{ color: '#113D73' }} />
                <span className="font-bold" style={{ color: '#113D73' }}>Demo Tables</span>
              </div>
              {uploadedTables.map((table, index) => (
                <button
                  key={index}
                  onClick={() => handleTableClick(table.name)}
                  className="flex items-center gap-2 hover:text-gray-900 hover:bg-gray-200 transition-colors text-sm pl-9 py-1 rounded w-full text-left"
                  title={`${table.row_count} rows · ${table.columns.length} columns`}
                >
                  <span className="truncate">{formatTableName(table.name)}</span>
                  <span className="ml-auto text-xs text-gray-400 flex-shrink-0">{table.row_count}r</span>
                </button>
              ))}
            </div>
          )}
        </nav>
      </div>
    </aside>
  );
};

export default Sidebar;
