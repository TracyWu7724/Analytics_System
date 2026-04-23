import os
import pandas as pd
from typing import List, Dict, Any, Optional
from databricks.sdk.core import Config, oauth_service_principal
from databricks import sql
from dotenv import load_dotenv
import sqlite3
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
        # Databricks configuration
        self.server_hostname = os.getenv("DATABRICKS_SERVER_HOSTNAME")
        self.client_id = os.getenv("DATABRICKS_CLIENT_ID")
        self.client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")
        self.http_path = os.getenv("DATABRICKS_HTTP_PATH")
        
        base_dir = os.path.dirname(__file__)
        self.local_db_path = os.path.join(base_dir, "data.db")
        
        # Validate configuration
        if not all([self.server_hostname, self.client_id, self.client_secret, self.http_path]):
            logger.warning("Databricks configuration incomplete.")
    
    def credential_provider(self):
        """Provides OAuth service principal credentials for Databricks"""
        config = Config(
            host=f"https://{self.server_hostname}",
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        return oauth_service_principal(config)
    
    def get_databricks_connection(self):
        """Get a connection to Databricks with timeout settings"""
        try:
            return sql.connect(
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                credentials_provider=self.credential_provider,
                # Add timeout settings to prevent hanging
                session_configuration={
                    "ansi_mode": "true",
                    "timezone": "UTC"
                },
                # Connection timeout settings
                http_path_timeout=60,  # 60 seconds for warehouse startup
                _user_agent_entry="TracyApp/1.0"
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
            # User specified a custom limit - use it
            if "LIMIT" not in query_upper:
                query = f"{query.rstrip(';')} LIMIT {custom_limit}"
                logger.info(f"Added custom LIMIT {custom_limit} to query")
        elif custom_limit is None:
            # User wants ALL data - don't add automatic LIMIT
            logger.info("No LIMIT added - user requested all data")
        elif "LIMIT" not in query_upper and "COUNT(" not in query_upper and "DESCRIBE" not in query_upper:
            # Default behavior - add safety LIMIT
            query = f"{query.rstrip(';')} LIMIT 1000"
            logger.info(f"Added default LIMIT 1000 to query for safety")
        
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
        """Get all available table names from Databricks gold schema"""
        try:
            # Specifically target the gold schema
            query = "SHOW TABLES IN swks_das_dev.gold"
            # Use shorter timeout for metadata queries
            results = self.execute_query(query, timeout_seconds=15)
            
            # Extract table names
            table_names = []
            for row in results:
                # Results might have different column names depending on Databricks version
                if 'tableName' in row:
                    table_name = row['tableName']
                elif 'table_name' in row:
                    table_name = row['table_name']
                elif len(row) > 1:  # Sometimes it's just positional
                    table_name = list(row.values())[1]
                else:
                    table_name = list(row.values())[0]
                
                # Ensure fully qualified table names for gold schema
                if '.' not in table_name:
                    table_name = f"swks_das_dev.gold.{table_name}"
                
                table_names.append(table_name)
            
            logger.info(f"Successfully discovered {len(table_names)} tables")
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
    
    # Local SQLite methods for uploaded files and query history
    def init_local_db(self):
        """Initialize local SQLite database for uploaded files and query history"""
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()
        
        # Create recent queries table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recent_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create table metadata table for uploaded files
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS table_metadata (
                table_name TEXT PRIMARY KEY,
                original_filename TEXT,
                file_extension TEXT,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_query_to_history(self, query_text: str):
        """Save a query to the recent queries history"""
        try:
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO recent_queries (query_text, created_at) 
                VALUES (?, CURRENT_TIMESTAMP)
            ''', (query_text.strip(),))
            
            conn.commit()
            conn.close()
            logger.info(f"Saved query to history: {query_text[:50]}...")
        except Exception as e:
            logger.error(f"Failed to save query to history: {e}")
    
    def get_recent_queries(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent queries from local database"""
        try:
            conn = sqlite3.connect(self.local_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT query_text, created_at 
                FROM recent_queries 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            recent_queries = [dict(row) for row in rows]
            
            conn.close()
            return recent_queries
        except Exception as e:
            logger.error(f"Error getting recent queries: {e}")
            return []
    
    def handle_uploaded_file(self, df: pd.DataFrame, table_name: str, original_filename: str = None, file_extension: str = None) -> Dict[str, Any]:
        """Store uploaded file in local SQLite database with metadata"""
        try:
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            
            # Drop table if it exists
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            
            # Create table with pandas
            df.to_sql(table_name, conn, index=False, if_exists='replace')
            
            # Store metadata if provided
            if original_filename and file_extension:
                cursor.execute('''
                    INSERT OR REPLACE INTO table_metadata (table_name, original_filename, file_extension)
                    VALUES (?, ?, ?)
                ''', (table_name, original_filename, file_extension))
            
            conn.commit()
            conn.close()
            db_cache.invalidate_table_list()
            db_cache.invalidate_table_schema()
            
            return {
                "success": True,
                "table_name": table_name,
                "row_count": len(df),
                "column_count": len(df.columns),
                "columns": list(df.columns),
                "original_filename": original_filename,
                "file_extension": file_extension
            }
        except Exception as e:
            logger.error(f"Error handling uploaded file: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_table_metadata(self, table_name: str) -> Dict[str, Any]:
        """Get metadata for an uploaded table"""
        try:
            conn = sqlite3.connect(self.local_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT original_filename, file_extension, upload_date
                FROM table_metadata 
                WHERE table_name = ?
            ''', (table_name,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return dict(row)
            else:
                return {}
        except Exception as e:
            logger.error(f"Error getting table metadata for {table_name}: {e}")
            return {}
    
    def get_uploaded_tables(self) -> List[Dict[str, Any]]:
        """Get information about uploaded tables in local SQLite"""
        try:
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            
            # Get uploaded tables (tables that start with "uploaded_")
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' 
                AND name LIKE 'uploaded_%'
                AND name NOT LIKE 'sqlite_%'
            """)
            
            tables = cursor.fetchall()
            table_info = []
            
            for table_name_tuple in tables:
                table_name = table_name_tuple[0]
                
                # Get column info
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                
                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = cursor.fetchone()[0]
                
                # Get original filename metadata
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
                original_filename_row = cursor.fetchone()
                original_filename = original_filename_row[0] if original_filename_row else None
                
                table_info.append({
                    "name": table_name,
                    "columns": [{"name": col[1], "type": col[2]} for col in columns],
                    "row_count": row_count,
                    "is_uploaded": True,
                    "source": "local",
                    "original_filename": original_filename
                })
            
            conn.close()
            return table_info
        except Exception as e:
            logger.error(f"Error getting uploaded tables: {e}")
            return []
    

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

    def delete_uploaded_table(self, table_name: str) -> Dict[str, Any]:
        """Delete an uploaded SQLite table and its metadata."""
        try:
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                conn.close()
                return {"success": False, "error": f"Table '{table_name}' not found"}

            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            cursor.execute("DELETE FROM table_metadata WHERE table_name = ?", (table_name,))
            conn.commit()
            conn.close()
            db_cache.invalidate_table_list()
            db_cache.invalidate_table_schema(table_name)
            return {"success": True, "message": f"Deleted uploaded table '{table_name}'"}
        except Exception as e:
            logger.error(f"Error deleting uploaded table {table_name}: {e}")
            return {"success": False, "error": str(e)}

    def query_uploaded_table(self, query: str) -> List[Dict[str, Any]]:
        """Execute query on local SQLite database (for uploaded tables)"""
        try:
            conn = sqlite3.connect(self.local_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(query)
            rows = cursor.fetchall()
            result = [dict(row) for row in rows]
            
            conn.close()
            return result
        except Exception as e:
            logger.error(f"Error querying uploaded table: {e}")
            raise 
