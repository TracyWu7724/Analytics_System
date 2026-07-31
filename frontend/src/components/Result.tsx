'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { XCircle, Table as TableIcon, Download, ChevronUp, ChevronDown, FileSpreadsheet, Maximize2, Minimize2, Code, Copy, Check } from 'lucide-react'
import type { QueryResult } from '../types/database'
import { useRef, useEffect, useState, useMemo } from 'react'
import { ApiService } from '../services/api'

interface QueryOutputProps {
  results: QueryResult[]
  error: string
  onClose: () => void
  sql_query?: string
  warning?: string
  sql_table?: string
  mdl_metrics_referenced?: { name: string; expression: string; description: string }[]
  entity_resolutions?: { mention: string; resolved_to: string; table: string; column: string }[]
}

const formatErrorMessage = (error: string) => {
  try {
    if (error.includes('near')) {
      const parts = error.split('near')
      const errorLocation = parts[1]?.split(':')?.[0]?.replace(/['"]/g, '').trim()
      return (
        <div className="text-muted-foreground text-sm">
          We found an issue with your SQL query near{' '}
          <code className="px-1.5 py-0.5 bg-destructive/10 text-destructive rounded">
            {errorLocation}
          </code>
        </div>
      )
    } else {
      // Generic error message if we can't parse the specific location
      return (
        <div className="text-muted-foreground text-sm">
          {error}
        </div>
      )
    }
  } catch {
    // Fallback for any parsing errors
    return (
      <div className="text-muted-foreground text-sm">
        An error occurred while executing the query
      </div>
    )
  }
}

export function QueryOutput({ results, error, onClose, sql_query, warning, sql_table, mdl_metrics_referenced, entity_resolutions }: QueryOutputProps) {
  const headerRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [sortConfig, setSortConfig] = useState<{
    column: string;
    direction: 'asc' | 'desc' | null;
  }>({ column: '', direction: null });
  const [isZoomedIn, setIsZoomedIn] = useState(false);
  const [showSQL, setShowSQL] = useState(true);
  const [isCopied, setIsCopied] = useState(false);

  useEffect(() => {
    const headerEl = headerRef.current;
    const bodyEl = bodyRef.current;

    if (headerEl && bodyEl) {
      const handleScroll = () => {
        headerEl.scrollLeft = bodyEl.scrollLeft;
      };

      bodyEl.addEventListener('scroll', handleScroll);
      return () => bodyEl.removeEventListener('scroll', handleScroll);
    }
  }, []);

  const handleDownloadCSV = async () => {
    if (!results.length || !results[0]) return;
    
    try {
      await ApiService.downloadCSV();
    } catch (error) {
      console.error('CSV download failed:', error);
      // Fallback to client-side generation if backend fails
      const headers = results[0].columns;
      const rows = results[0].values;
      
      const csvContent = [
        headers.join(','),
        ...rows.map((row: any[]) => row.join(','))
      ].join('\n');
      
      const blob = new Blob([csvContent], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'query_results.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    }
  };

  const handleDownloadExcel = () => {
    if (!results.length || !results[0]) return;

    const headers = results[0].columns;
    const rows = results[0].values;

    // Build CSV content and serve as .xlsx-compatible file
    // For a true xlsx, fall back to CSV which Excel opens natively
    const csvContent = [
      headers.join(','),
      ...rows.map((row: any[]) =>
        row.map(cell =>
          cell == null ? '' : String(cell).includes(',') ? `"${String(cell).replace(/"/g, '""')}"` : String(cell)
        ).join(',')
      ),
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `query_results_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  };

  const handleToggleZoom = () => {
    setIsZoomedIn(!isZoomedIn);
  };

  const handleCopySQL = async () => {
    if (sql_query) {
      try {
        await navigator.clipboard.writeText(sql_query);
        setIsCopied(true);
        setTimeout(() => setIsCopied(false), 2000);
      } catch (error) {
        console.error('Failed to copy SQL:', error);
      }
    }
  };

  const handleToggleSQL = () => {
    setShowSQL(!showSQL);
  };

  const sortedResults = useMemo(() => {
    if (!results.length || !results[0] || !sortConfig.direction) return results;

    const sorted = [...results[0].values];
    const columnIndex = results[0].columns.indexOf(sortConfig.column);

    return [{
      ...results[0],
      values: sorted.sort((a, b) => {
        if (a[columnIndex] === b[columnIndex]) return 0;
        
        // Handle numeric sorting
        if (!isNaN(a[columnIndex]) && !isNaN(b[columnIndex])) {
          return sortConfig.direction === 'asc' 
            ? Number(a[columnIndex]) - Number(b[columnIndex])
            : Number(b[columnIndex]) - Number(a[columnIndex]);
        }
        
        // String sorting
        return sortConfig.direction === 'asc'
          ? String(a[columnIndex]).localeCompare(String(b[columnIndex]))
          : String(b[columnIndex]).localeCompare(String(a[columnIndex]));
      })
    }];
  }, [results, sortConfig]);

  const handleSort = (column: string) => {
    setSortConfig(current => ({
      column,
      direction: 
        current.column === column && current.direction === 'asc'
          ? 'desc'
          : current.column === column && current.direction === 'desc'
          ? null
          : 'asc'
    }));
  };

  if (!error && (!results.length || !results[0])) return null

  const tableContent = results[0] ? (
    <div className="max-h-[500px] overflow-auto border border-border/40 rounded-md shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
      <table className="w-full [box-shadow:0_2px_10px_rgba(0,0,0,0.2)]">
        <thead>
          <tr>
            {results[0].columns.map((column: string, i: number) => (
              <th 
                key={i} 
                className="sticky top-0 px-4 py-2 text-left text-xs font-bold uppercase tracking-wider text-white bg-primary group cursor-pointer"
                onClick={() => handleSort(column)}
              >
                <div className="flex items-center gap-2">
                  {column}
                  <div className="flex flex-col opacity-0 group-hover:opacity-100 transition-opacity">
                    <ChevronUp 
                      className={`h-3 w-3 ${
                        sortConfig.column === column && sortConfig.direction === 'asc'
                          ? 'text-white opacity-100'
                          : 'text-white/50'
                      }`}
                    />
                    <ChevronDown 
                      className={`h-3 w-3 -mt-1 ${
                        sortConfig.column === column && sortConfig.direction === 'desc'
                          ? 'text-white opacity-100'
                          : 'text-white/50'
                      }`}
                    />
                  </div>
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedResults[0]?.values.map((row: any[], i: number) => (
            <tr 
              key={i}
              className="border-t border-border hover:bg-muted/50 transition-colors"
            >
              {row.map((cell: any, j: number) => (
                <td key={j} className="px-4 py-3 text-sm whitespace-nowrap">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : null;

  return (
    <>
      <AnimatePresence mode="wait">
        <motion.div
          key={error ? 'error' : 'results'}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 20 }}
          className="mt-6 overflow-hidden [box-shadow:0_8px_30px_rgba(0,0,0,0.12)]"
        >
          <div className="relative group [box-shadow:0_4px_24px_rgba(0,0,0,0.2)]">
            <div className="absolute inset-0 bg-gradient-to-r from-primary/20 to-primary/10 rounded-lg blur-md group-hover:blur-lg transition-all" />
            <div className="relative bg-background rounded-lg border border-primary/20 shadow-[0_8px_28px_rgba(0,0,0,0.25)]">
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-border/40">
                <div className="flex items-center gap-3">
                  {!error && <TableIcon className="w-5 h-5 text-primary" />}
                  <h3 className="font-semibold">
                    {error ? 'Error' : 'Query Results'}
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  {!error && sql_query && (
                    <button
                      onClick={handleToggleSQL}
                      className="text-muted-foreground hover:text-foreground transition-colors p-2 hover:bg-muted/50 rounded-lg"
                      title={showSQL ? "Hide SQL" : "Show SQL"}
                    >
                      <Code className="w-5 h-5" />
                    </button>
                  )}
                  {!error && (
                    <>
                      <button
                        onClick={handleDownloadCSV}
                        className="text-muted-foreground hover:text-foreground transition-colors p-2 hover:bg-muted/50 rounded-lg"
                        title="Download CSV"
                      >
                        <Download className="w-5 h-5" />
                      </button>
                      <button
                        onClick={handleDownloadExcel}
                        className="text-muted-foreground hover:text-foreground transition-colors p-2 hover:bg-muted/50 rounded-lg"
                        title="Download Excel"
                      >
                        <FileSpreadsheet className="w-5 h-5" />
                      </button>
                      <button
                        onClick={handleToggleZoom}
                        className="text-muted-foreground hover:text-foreground transition-colors p-2 hover:bg-muted/50 rounded-lg"
                        title={isZoomedIn ? "Minimize Table" : "Zoom Table"}
                      >
                        {isZoomedIn ? <Minimize2 className="w-5 h-5" /> : <Maximize2 className="w-5 h-5" />}
                      </button>
                    </>
                  )}
                  
                </div>
              </div>

              {/* Provenance: which table / metric / entity answered the question */}
              {!error && (sql_table || (mdl_metrics_referenced && mdl_metrics_referenced.length > 0) || (entity_resolutions && entity_resolutions.length > 0)) && (
                <div className="px-6 py-3 border-b border-border/40 bg-muted/20 flex flex-wrap items-center gap-2 text-xs">
                  {sql_table && (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-background border border-border">
                      <span className="text-muted-foreground">Table:</span>
                      <span className="font-mono font-medium">{sql_table}</span>
                    </span>
                  )}
                  {mdl_metrics_referenced?.map((m) => (
                    <span
                      key={m.name}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-background border border-border"
                      title={m.description}
                    >
                      <span className="text-muted-foreground">{m.name}:</span>
                      <span className="font-mono font-medium">{m.expression}</span>
                    </span>
                  ))}
                  {entity_resolutions?.map((r) => (
                    <span
                      key={r.mention}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-background border border-border"
                    >
                      <span className="text-muted-foreground">{r.mention} →</span>
                      <span className="font-medium">{r.resolved_to}</span>
                      <span className="font-mono text-muted-foreground">({r.table}.{r.column})</span>
                    </span>
                  ))}
                </div>
              )}

              {/* SQL Query Display */}
              {showSQL && sql_query && (
                <div className="px-6 py-4 border-b border-border/40 bg-muted/30">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="font-medium text-sm text-muted-foreground uppercase tracking-wide">Generated SQL Query</h4>
                    <button
                      onClick={handleCopySQL}
                      className="flex items-center gap-2 px-3 py-1.5 text-xs bg-background border border-border rounded-md hover:bg-muted/50 transition-colors"
                      title="Copy SQL to clipboard"
                    >
                      {isCopied ? (
                        <>
                          <Check className="w-3 h-3 text-green-600" />
                          Copied!
                        </>
                      ) : (
                        <>
                          <Copy className="w-3 h-3" />
                          Copy SQL
                        </>
                      )}
                    </button>
                  </div>
                  <div className="bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto">
                    <pre className="text-sm font-mono whitespace-pre-wrap">{sql_query}</pre>
                  </div>
                </div>
              )}

              {/* Warning Display */}
              {warning && !error && (
                <div className="px-6 py-3 bg-yellow-50 border-b border-yellow-200">
                  <div className="flex items-start gap-2">
                    <div className="w-4 h-4 text-yellow-600 mt-0.5">⚠️</div>
                    <div className="text-sm text-yellow-800">{warning}</div>
                  </div>
                </div>
              )}

              {/* Content */}
              <div className="p-6">
                {error ? (
                  <div className="space-y-2">
                    <div className="font-medium text-destructive">
                      Error executing query
                    </div>
                    {formatErrorMessage(error)}
                    <div className="text-sm text-muted-foreground">
                      This might be due to:
                      <ul className="list-disc ml-5 mt-1 space-y-1">
                        <li>A misspelled keyword or table name</li>
                        <li>Missing or extra punctuation</li>
                        <li>Incorrect SQL syntax structure</li>
                      </ul>
                    </div>
                    <div className="text-sm mt-4 p-3 bg-muted/50 rounded-md">
                      <span className="font-medium">Full error: </span>
                      {error}
                    </div>
                  </div>
                ) : (
                  tableContent
                )}
              </div>
            </div>
          </div>
        </motion.div>
      </AnimatePresence>

             {/* Zoomed In Modal */}
       {isZoomedIn && !error && (
         <motion.div
           initial={{ opacity: 0 }}
           animate={{ opacity: 1 }}
           exit={{ opacity: 0 }}
           className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-2"
           onClick={handleToggleZoom}
         >
           <motion.div
             initial={{ scale: 0.9, opacity: 0 }}
             animate={{ scale: 1, opacity: 1 }}
             exit={{ scale: 0.9, opacity: 0 }}
             className="bg-white rounded-lg shadow-2xl w-[98vw] h-[98vh] overflow-hidden flex flex-col"
             onClick={(e: React.MouseEvent) => e.stopPropagation()}
           >
             <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 flex-shrink-0">
               <h3 className="font-semibold text-lg">Query Results - Zoomed View</h3>
               <div className="flex items-center gap-2">
                 <button
                   onClick={handleDownloadCSV}
                   className="text-gray-600 hover:text-gray-900 transition-colors p-2 hover:bg-gray-100 rounded-lg"
                   title="Download CSV"
                 >
                   <Download className="w-5 h-5" />
                 </button>
                 <button
                   onClick={handleDownloadExcel}
                   className="text-gray-600 hover:text-gray-900 transition-colors p-2 hover:bg-gray-100 rounded-lg"
                   title="Download Excel"
                 >
                   <FileSpreadsheet className="w-5 h-5" />
                 </button>
                 <button
                   onClick={handleToggleZoom}
                   className="text-gray-600 hover:text-gray-900 transition-colors p-2 hover:bg-gray-100 rounded-lg"
                 >
                   <Minimize2 className="w-5 h-5" />
                 </button>
               </div>
             </div>
             <div className="flex-1 p-4 overflow-hidden">
               <div className="h-full overflow-auto border border-gray-300 rounded-md shadow-lg">
                 <table className="w-full">
                   <thead>
                     <tr>
                       {results[0].columns.map((column: string, i: number) => (
                         <th 
                           key={i} 
                           className="sticky top-0 px-4 py-3 text-left text-xs font-bold uppercase tracking-wider text-white bg-primary group cursor-pointer"
                           onClick={() => handleSort(column)}
                         >
                           <div className="flex items-center gap-2">
                             {column}
                             <div className="flex flex-col opacity-0 group-hover:opacity-100 transition-opacity">
                               <ChevronUp 
                                 className={`h-3 w-3 ${
                                   sortConfig.column === column && sortConfig.direction === 'asc'
                                     ? 'text-white opacity-100'
                                     : 'text-white/50'
                                 }`}
                               />
                               <ChevronDown 
                                 className={`h-3 w-3 -mt-1 ${
                                   sortConfig.column === column && sortConfig.direction === 'desc'
                                     ? 'text-white opacity-100'
                                     : 'text-white/50'
                                 }`}
                               />
                             </div>
                           </div>
                         </th>
                       ))}
                     </tr>
                   </thead>
                   <tbody>
                     {sortedResults[0].values.map((row: any[], i: number) => (
                       <tr 
                         key={i}
                         className="border-t border-gray-200 hover:bg-gray-50 transition-colors"
                       >
                         {row.map((cell: any, j: number) => (
                           <td key={j} className="px-4 py-3 text-sm whitespace-nowrap">
                             {cell}
                           </td>
                         ))}
                       </tr>
                     ))}
                   </tbody>
                 </table>
               </div>
             </div>
           </motion.div>
         </motion.div>
       )}
    </>
  );
} 
