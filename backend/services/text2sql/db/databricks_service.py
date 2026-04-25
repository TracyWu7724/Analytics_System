import os
from typing import List, Dict, Any, Optional
from databricks import sql
from dotenv import load_dotenv
import logging

try:
    from ..cache_service import db_cache
except ImportError:
    from cache_service import db_cache

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabricksService:
    """Service class for Databricks database operations"""
    
    def __init__(self):
        self.server_hostname = os.getenv("DATABRICKS_SERVER_HOSTNAME")
        self.http_path = os.getenv("DATABRICKS_HTTP_PATH")
        self.token = os.getenv("DATABRICKS_TOKEN")

        # Schema: catalog.schema (e.g. chatbot_mw.default)
        _catalog = os.getenv("DATABRICKS_CATALOG", "").strip()
        _schema  = os.getenv("DATABRICKS_SCHEMA", "default").strip()
        self.db_schema = f"{_catalog}.{_schema}" if _catalog else _schema

        if not all([self.server_hostname, self.http_path, self.token]):
            logger.warning("Databricks configuration incomplete — set DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN.")
    
    def get_databricks_connection(self):
        """Get a PAT-authenticated connection to Databricks."""
        try:
            return sql.connect(
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                access_token=self.token,
                session_configuration={
                    "ansi_mode": "true",
                    "timezone": "UTC",
                },
                _tls_no_verify=True,  # bypass corp/self-signed CA chain on macOS
            )
        except Exception as e:
            logger.error(f"Failed to connect to Databricks: {e}")
            raise
    
    def execute_query(self, query: str, timeout_seconds: int = 60, custom_limit: int = None) -> List[Dict[str, Any]]:
        """Execute a query on Databricks and return results as list of dictionaries"""
        import threading
        import time
        
        # Add automatic LIMIT if not present and no custom limit specified for unlimited queries
        query_upper = query.upper().strip()
        if custom_limit is not None and custom_limit > 0:
            # Caller supplied an explicit positive limit
            if "LIMIT" not in query_upper:
                query = f"{query.rstrip(';')} LIMIT {custom_limit}"
                logger.info(f"Added custom LIMIT {custom_limit} to query")
        elif custom_limit == 0:
            # Explicit 0 means caller wants all rows — skip safety limit
            logger.info("No LIMIT added — caller requested all rows")
        elif "LIMIT" not in query_upper and "COUNT(" not in query_upper and not query_upper.startswith(("DESCRIBE", "SHOW", "EXPLAIN")):
            # Default (custom_limit=None): add safety cap
            query = f"{query.rstrip(';')} LIMIT 1000"
            logger.info("Added default LIMIT 1000 to query for safety")
        
        logger.info(f"Executing query with {timeout_seconds}s timeout: {query[:100]}...")
        
        result_container = {"result": None, "error": None, "completed": False}
        
        def execute_with_timeout():
            try:
                with self.get_databricks_connection() as connection:
                    with connection.cursor() as cursor:
                        # Execute query
                        cursor.execute(query)
                        
                        # Get column names
                        if cursor.description:
                            columns = [desc[0] for desc in cursor.description]
                            logger.info(f"Query returned {len(columns)} columns")
                        else:
                            logger.warning("No columns returned from query")
                            result_container["result"] = []
                            result_container["completed"] = True
                            return
                        
                        # Fetch results with size limit
                        rows = cursor.fetchmany(1000)  # Fetch max 1000 rows at a time
                        logger.info(f"Fetched {len(rows)} rows")
                        
                        # Convert to list of dictionaries
                        result = []
                        for i, row in enumerate(rows):
                            if i % 100 == 0 and i > 0:  # Log progress for large results
                                logger.info(f"Processing row {i}/{len(rows)}")
                            result.append(dict(zip(columns, row)))
                        
                        result_container["result"] = result
                        result_container["completed"] = True
                        logger.info(f"Query completed successfully: {len(result)} rows returned")
                        
            except Exception as e:
                logger.error(f"Query execution error: {e}")
                result_container["error"] = str(e)
                result_container["completed"] = True
        
        # Run query in a separate thread
        query_thread = threading.Thread(target=execute_with_timeout)
        query_thread.daemon = True
        query_thread.start()
        
        # Wait for completion or timeout
        start_time = time.time()
        while not result_container["completed"] and (time.time() - start_time) < timeout_seconds:
            time.sleep(0.1)  # Check every 100ms
        
        if not result_container["completed"]:
            logger.error(f"Query timed out after {timeout_seconds} seconds")
            raise TimeoutError(f"Query timed out after {timeout_seconds} seconds. Try:\n• Adding more specific filters (e.g., WHERE conditions)\n• Using smaller date ranges\n• Adding LIMIT clauses\n• Simplifying the query")
        
        if result_container["error"]:
            raise Exception(result_container["error"])
        
        return result_container["result"] or []
    
    def get_table_names(self) -> List[str]:
        """Get all available table names from the configured Databricks schema."""
        try:
            schema = getattr(self, "db_schema", "chatbot_mw")
            query = f"SHOW TABLES IN {schema}"
            results = self.execute_query(query, timeout_seconds=15)

            table_names = []
            for row in results:
                if 'tableName' in row:
                    table_name = row['tableName']
                elif 'table_name' in row:
                    table_name = row['table_name']
                elif len(row) > 1:
                    table_name = list(row.values())[1]
                else:
                    table_name = list(row.values())[0]

                # Qualify with schema if not already fully qualified
                if '.' not in table_name:
                    table_name = f"{schema}.{table_name}"

                table_names.append(table_name)

            logger.info(f"Discovered {len(table_names)} tables in {self.db_schema}")
            return table_names

        except Exception as e:
            logger.error(f"Error getting table names: {e}")
            return []
    
    def get_table_schema(self, table_name: str) -> List[Dict[str, str]]:
        """Get schema information for a specific table"""
        cached_schema = db_cache.get_table_schema(table_name)
        if cached_schema is not None:
            return cached_schema

        try:
            query = f"DESCRIBE {table_name}"
            # Use shorter timeout for metadata queries
            results = self.execute_query(query, timeout_seconds=15)
            
            schema = []
            for row in results:
                col_name = row.get('col_name') or row.get('column_name') or list(row.values())[0]
                data_type = row.get('data_type') or row.get('type') or list(row.values())[1]
                
                schema.append({
                    "name": col_name,
                    "type": data_type
                })

            db_cache.set_table_schema(table_name, schema, ttl=300)
            return schema
        except Exception as e:
            logger.error(f"Error getting table schema for {table_name}: {e}")
            return []
    
    def get_table_preview(self, table_name: str, limit: int = 5) -> Dict[str, Any]:
        """Get a preview of table data"""
        try:
            query = f"SELECT * FROM {table_name} LIMIT {limit}"
            rows = self.execute_query(query)
            
            # Get schema info
            schema = self.get_table_schema(table_name)
            columns = [col["name"] for col in schema]
            
            # Get total row count (if possible)
            try:
                count_query = f"SELECT COUNT(*) as count FROM {table_name}"
                count_result = self.execute_query(count_query)
                total_rows = count_result[0]["count"] if count_result else len(rows)
            except:
                total_rows = len(rows)  # Fallback if count fails
            
            return {
                "table_name": table_name,
                "columns": columns,
                "rows": rows,
                "preview_count": len(rows),
                "total_rows": total_rows
            }
        except Exception as e:
            logger.error(f"Error getting table preview for {table_name}: {e}")
            raise
    
    def test_connection(self) -> Dict[str, Any]:
        """Check Databricks connectivity and return a compact health payload."""
        try:
            tables = self.get_table_names()
            return {
                "status": "success",
                "message": "Databricks connection successful",
                "tables_count": len(tables),
                "sample_tables": tables[:5],
            }
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return {"status": "error", "message": str(e), "tables_count": 0, "sample_tables": []}

