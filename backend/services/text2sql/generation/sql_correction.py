def clean_sql_query(raw_sql: str) -> str:
    """
    Clean and validate SQL query
    """
    if not raw_sql:
        raise ValueError("Empty SQL response")
    
    # Basic cleanup only
    sql = raw_sql.strip()
    
    # Remove any markdown artifacts if present
    sql = re.sub(r'```sql\s*', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'```\s*', '', sql)
    
    # Clean whitespace and remove trailing semicolon
    sql = re.sub(r'\s+', ' ', sql.strip().rstrip(';'))
    
    if not sql or len(sql) < 5:
        raise ValueError(f"Invalid SQL query: {sql}")
    
    # Validate SQL Server specific syntax
    sql = validate_sql_server_query(sql)
    
    print(f"Final SQL: '{sql}'")
    return sql