import re


_FORBIDDEN = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w|ALTER\s+TABLE|CREATE\s+TABLE|EXEC\s*\(|EXECUTE\s*\(|xp_cmdshell)\b",
    re.IGNORECASE,
)


def validate_sql_server_query(sql: str) -> str:
    """
    Reject statements that would mutate or destroy data.

    Raises ValueError for DML/DDL other than SELECT.
    Returns the query unchanged if it passes.
    """
    m = _FORBIDDEN.search(sql)
    if m:
        raise ValueError(f"Disallowed SQL operation detected: '{m.group()}'")
    return sql


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