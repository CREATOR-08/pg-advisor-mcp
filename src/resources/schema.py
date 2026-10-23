from fastmcp import FastMCP

from db.connection import get_readonly_connection

def register_db_resources(mcp:FastMCP):
    @mcp.resource("postgres://tables")
    def list_available_tables() -> list[str]:
        """Exposes all user tables in the public schema."""
        
        conn = get_readonly_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    ORDER BY table_name;
                """)
                return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()
    # get table schemas
    @mcp.resource("postgres://schema/{table_name}")
    def get_table_schema(table_name: str) -> dict:
        """Returns detailed column definitions, data types, and constraints for a table."""
        conn = get_readonly_connection()
        try:
            with conn.cursor() as cur:
                # 1. Fetch column specifications
                cur.execute("""
                    SELECT 
                        column_name, 
                        data_type, 
                        is_nullable, 
                        column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position;
                """, (table_name,))
                columns = [
                    {
                        "column": row[0],
                        "type": row[1],
                        "nullable": row[2] == "YES",
                        "default": row[3]
                    }
                    for row in cur.fetchall()
                ]

                # 2. Fetch primary and foreign key constraints
                cur.execute("""
                    SELECT
                        tc.constraint_type,
                        kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    WHERE tc.table_schema = 'public' 
                    AND tc.table_name = %s
                    AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY');
                """, (table_name,))
                constraints = [
                    {"type": row[0], "column": row[1]} 
                    for row in cur.fetchall()
                ]

                return {
                    "table": table_name,
                    "columns": columns,
                    "constraints": constraints
                }
        finally:
            conn.close()

    #get  indexes
    @mcp.resource("postgres://indexes/{table_name}")
    def get_table_indexes(table_name: str) -> list[dict]:
        """Exposes all existing index definitions and DDL for a given table."""
        conn = get_readonly_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        indexname, 
                        indexdef 
                    FROM pg_indexes 
                    WHERE schemaname = 'public' AND tablename = %s;
                """, (table_name,))
                return [
                    {"index_name": row[0], "definition": row[1]}
                    for row in cur.fetchall()
                ]
        finally:
            conn.close()
    

    #get tables suffering from sequential scans

    @mcp.resource("postgres://tables/seq-scans")
    def get_sequential_scan_hotspots() -> list[dict]:
        """Identifies tables with high sequential scans compared to index scans."""
        conn = get_readonly_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        relname AS table_name,
                        seq_scan,
                        seq_tup_read,
                        idx_scan,
                        n_live_tup AS total_rows
                    FROM pg_stat_user_tables
                    WHERE schemaname = 'public' AND seq_scan > 0
                    ORDER BY seq_tup_read DESC
                    LIMIT 10;
                """)
                return [
                    {
                        "table_name": row[0],
                        "sequential_scans": row[1],
                        "rows_read_via_seq_scan": row[2],
                        "index_scans": row[3],
                        "total_rows": row[4]
                    }
                    for row in cur.fetchall()
                ]
        finally:
            conn.close()

    @mcp.resource("postgres://locks/active")
    def get_active_locks() -> list[dict]:
        """Exposes currently held table locks and any blocked queries."""
        conn = get_readonly_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        a.pid,
                        a.usename,
                        l.locktype,
                        l.mode,
                        c.relname AS locked_table,
                        a.query,
                        a.state,
                        NOW() - a.query_start AS duration
                    FROM pg_locks l
                    JOIN pg_stat_activity a ON l.pid = a.pid
                    LEFT JOIN pg_class c ON l.relation = c.oid
                    WHERE a.pid <> pg_backend_pid()
                    AND l.mode IN ('AccessExclusiveLock', 'ExclusiveLock', 'RowExclusiveLock')
                    ORDER BY duration DESC
                    LIMIT 10;
                """)
                return [
                    {
                        "pid": row[0],
                        "user": row[1],
                        "lock_type": row[2],
                        "mode": row[3],
                        "table": row[4],
                        "query": row[5],
                        "state": row[6],
                        "duration": str(row[7])
                    }
                    for row in cur.fetchall()
                ]
        finally:
            conn.close()

