import re

# Any keyword that can mutate or control the database
_MUTATING = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|MERGE|UPSERT|REPLACE|"
    r"CREATE|DROP|ALTER|TRUNCATE|RENAME|"
    r"GRANT|REVOKE|DENY|"
    r"CALL|EXEC(?:UTE)?|"
    r"COPY|PUT|GET|REMOVE|"          # Databricks / Snowflake file ops
    r"SET\s+\w|USE\s+\w|"           # session-level changes
    r"xp_cmdshell|OPENROWSET"
    r")\b",
    re.IGNORECASE,
)

# The statement must start with one of these read-only commands
_READ_ONLY_START = re.compile(
    r"^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN|VALUES)\b",
    re.IGNORECASE,
)


def validate_sql_server_query(sql: str) -> str:
    """
    Enforce read-only access to Databricks.

    Raises ValueError if the query:
      - does not start with SELECT / WITH / SHOW / DESCRIBE / EXPLAIN
      - contains any mutating keyword anywhere in the statement
    Returns the query unchanged if it passes both checks.
    """
    if not _READ_ONLY_START.match(sql):
        first = sql.strip().split()[0] if sql.strip() else "(empty)"
        raise ValueError(
            f"Only read-only queries are allowed. "
            f"'{first}' is not a permitted statement type."
        )
    m = _MUTATING.search(sql)
    if m:
        raise ValueError(
            f"Disallowed SQL operation detected: '{m.group()}'. "
            f"Only SELECT queries are permitted against Databricks."
        )
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

    # Strip SQL Server-style square bracket quoting (not valid in Databricks)
    # e.g. [default] → default,  [column name] → `column name`
    def _unbracket(m: re.Match) -> str:
        inner = m.group(1)
        # Re-quote with backticks only if the identifier has spaces/special chars
        return f"`{inner}`" if re.search(r'[^a-zA-Z0-9_]', inner) else inner
    sql = re.sub(r'\[([^\]]+)\]', _unbracket, sql)
    
    # Clean whitespace and remove trailing semicolon
    sql = re.sub(r'\s+', ' ', sql.strip().rstrip(';'))
    
    if not sql or len(sql) < 5:
        raise ValueError(f"Invalid SQL query: {sql}")
    
    # Validate SQL Server specific syntax
    sql = validate_sql_server_query(sql)
    
    print(f"Final SQL: '{sql}'")
    return sql