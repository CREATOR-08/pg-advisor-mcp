import json
from fastmcp import FastMCP
# from query_optimiser.db.connection import get_readonly_connection
from db.connection import get_readonly_connection
import sqlglot
from sqlglot import exp
def register_explain_tools(mcp: FastMCP):

    @mcp.tool()
    def explain_query_plan(sql_query: str,database_url: str = None) -> str:
        """Runs EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) on a SELECT query and rolls back."""
        # Safety check: block obvious mutating keywords
        clean_query = sql_query.strip().lower()
        if not clean_query.startswith("select") and not clean_query.startswith("with"):
            return "Error: Only SELECT queries are permitted for performance analysis."

        conn = get_readonly_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql_query}")
                plan = cur.fetchone()[0]
                conn.rollback()  # Always rollback
                return json.dumps(plan, indent=2)
        except Exception as e:
            conn.rollback()
            return f"Execution failed: {str(e)}"
        finally:
            conn.close()

    @mcp.tool()
    def check_migration_safety(ddl_statement: str,database_url: str = None) -> dict:
        """
        Scans a DDL migration (CREATE INDEX, ALTER TABLE, etc.) for destructive 
        table-locking anti-patterns before running it in production.
        """
        statement = ddl_statement.strip().lower()
        risks = []
        recommendations = []

        # Anti-Pattern 1: CREATE INDEX without CONCURRENTLY
        if "create index" in statement and "concurrently" not in statement:
            risks.append("CREATE INDEX without CONCURRENTLY blocks all writes (INSERT/UPDATE/DELETE) on the table.")
            recommendations.append("Use 'CREATE INDEX CONCURRENTLY ...' instead to avoid locking the table.")

        # Anti-Pattern 2: Adding NOT NULL without DEFAULT on older schemas
        if "add column" in statement and "not null" in statement and "default" not in statement:
            risks.append("Adding a NOT NULL column without a DEFAULT will fail on tables with existing rows.")
            recommendations.append("Add the column as nullable first, backfill data in batches, then add NOT NULL constraint.")

        # Anti-Pattern 3: Renaming columns or tables
        if "rename column" in statement or "rename to" in statement:
            risks.append("Renaming objects immediately breaks active application queries and running microservices.")
            recommendations.append("Use the Expand-Contract pattern (add new column, sync data, then drop old column later).")

        # Anti-Pattern 4: Direct table DROP
        if statement.startswith("drop table"):
            risks.append("Irreversible data deletion with ACCESS EXCLUSIVE lock.")
            recommendations.append("Confirm backup exists and consider renaming table to '_deprecated' first.")

        is_safe = len(risks) == 0
        return {
            "safe_for_zero_downtime": is_safe,
            "detected_risks": risks if risks else ["No obvious blocking anti-patterns detected."],
            "recommendations": recommendations
        }
    @mcp.tool()
    def find_missing_foreign_key_indexes(database_url: str = None) -> list[dict]:
        """
        Scans all foreign keys in the database and identifies which ones 
        lack an index on the child table, causing slow JOINs and table locks.
        """
        conn = get_readonly_connection()
        try:
            with conn.cursor() as cur:
                # Queries pg_constraint vs pg_index to detect unindexed foreign keys
                cur.execute("""
                    SELECT 
                        c.conrelid::regclass AS child_table,
                        a.attname AS fk_column,
                        c.confrelid::regclass AS referenced_parent_table
                    FROM pg_constraint c
                    JOIN pg_attribute a 
                      ON a.attrelid = c.conrelid 
                      AND a.attnum = ANY(c.conkey)
                    WHERE c.contype = 'f'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM pg_index i
                          WHERE i.indrelid = c.conrelid
                            AND a.attnum = ANY(i.indkey)
                      )
                    ORDER BY child_table;
                """)
                unindexed_fks = []
                for row in cur.fetchall():
                    child = str(row[0])
                    col = str(row[1])
                    parent = str(row[2])
                    unindexed_fks.append({
                        "child_table": child,
                        "foreign_key_column": col,
                        "parent_table": parent,
                        "suggested_sql": f"CREATE INDEX CONCURRENTLY idx_{child}_{col} ON {child} ({col});"
                    })
                return unindexed_fks
        finally:
            conn.close()



    @mcp.tool()
    def auto_recommend_indexes(table_name: str = None,database_url: str = None) -> list[dict]:
        """
        Automated diagnostic tool: Identifies tables suffering from sequential scans, 
        inspects their existing indexes, and automatically generates recommended 
        CREATE INDEX CONCURRENTLY DDL statements without requiring manual resource lookups.
        """
        conn = get_readonly_connection()
        recommendations = []
        try:
            with conn.cursor() as cur:
                # 1. Find tables with high sequential scans
                if table_name:
                    cur.execute("""
                        SELECT relname, seq_scan, seq_tup_read, idx_scan, n_live_tup
                        FROM pg_stat_user_tables
                        WHERE schemaname = 'public' AND relname = %s;
                    """, (table_name,))
                else:
                    cur.execute("""
                        SELECT relname, seq_scan, seq_tup_read, idx_scan, n_live_tup
                        FROM pg_stat_user_tables
                        WHERE schemaname = 'public' AND seq_scan > 0
                        ORDER BY seq_tup_read DESC
                        LIMIT 5;
                    """)
                
                problem_tables = cur.fetchall()

                for t_row in problem_tables:
                    t_name, seq_scan, seq_read, idx_scan, total_rows = t_row

                    # 2. Automatically hydrate existing indexes for this table
                    cur.execute("""
                        SELECT indexname, indexdef 
                        FROM pg_indexes 
                        WHERE schemaname = 'public' AND tablename = %s;
                    """, (t_name,))
                    existing_indexes = [{"name": r[0], "def": r[1]} for r in cur.fetchall()]

                    # 3. Automatically check unindexed foreign keys on this table
                    cur.execute("""
                        SELECT a.attname
                        FROM pg_constraint c
                        JOIN pg_attribute a 
                        ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                        WHERE c.contype = 'f' 
                        AND c.conrelid = %s::regclass
                        AND NOT EXISTS (
                            SELECT 1 FROM pg_index i 
                            WHERE i.indrelid = c.conrelid AND a.attnum = ANY(i.indkey)
                        );
                    """, (f"public.{t_name}",))
                    missing_fk_cols = [r[0] for r in cur.fetchall()]

                    recommendations.append({
                        "table": t_name,
                        "total_rows": total_rows,
                        "sequential_scans": seq_scan,
                        "rows_read_via_seq_scan": seq_read,
                        "existing_indexes": existing_indexes,
                        "unindexed_foreign_key_columns": missing_fk_cols,
                        "diagnosis": (
                            "High sequential scan activity detected." if seq_scan > idx_scan 
                            else "Balanced index usage."
                        ),
                        "actionable_fix": [
                            f"CREATE INDEX CONCURRENTLY idx_{t_name}_{col} ON {t_name} ({col});"
                            for col in missing_fk_cols
                        ]
                    })

                return recommendations
        finally:
            conn.close()

    @mcp.tool()
    def analyze_and_rewrite_query(sql_query: str,database_url: str = None) -> dict:
        """
        Parses a SQL query's Abstract Syntax Tree (AST) to detect performance anti-patterns
        (like SELECT *, unindexed subqueries, leading wildcards) and proposes optimized SQL rewrites.
        """
        issues = []
        suggestions = []
        
        try:
            parsed = sqlglot.parse_one(sql_query, read="postgres")
        except Exception as e:
            return {"error": f"Invalid SQL syntax: {str(e)}"}

        # 1. Detect SELECT *
        has_select_star = any(isinstance(expression, exp.Star) for expression in parsed.find_all(exp.Star))
        if has_select_star:
            issues.append("Query uses 'SELECT *' which fetches unnecessary columns, increasing network I/O and preventing index-only scans.")
            suggestions.append("Explicitly specify only required columns (e.g. SELECT id, title).")

        # 2. Detect Leading Wildcard LIKE '%...'
        for like_node in parsed.find_all(exp.Like):
            pattern = like_node.expression.sql()
            if pattern.startswith("'%"):
                issues.append(f"Leading wildcard detected in {like_node.sql()}. Standard B-Tree indexes cannot be used.")
                suggestions.append("Use a Trigram GIN index (pg_trgm) or Full-Text Search (to_tsvector) instead.")

        # 3. Detect unoptimized WHERE col IN (SELECT ...)
        for in_node in parsed.find_all(exp.In):
            if isinstance(in_node.args.get("query"), exp.Select):
                issues.append("Using 'WHERE ... IN (SELECT ...)' can cause repeated subquery evaluation on large datasets.")
                suggestions.append("Rewrite the subquery using an INNER JOIN or WHERE EXISTS.")

        return {
            "original_query": sql_query,
            "anti_patterns_found": issues if issues else ["No common anti-patterns detected."],
            "recommended_optimizations": suggestions,
            "ast_representation": parsed.sql(pretty=True)
        }

    @mcp.tool()
    def get_database_health_metrics(database_url: str = None) -> dict:
        """
        Inspects Neon database health: active vs idle connections, cache hit ratios, 
        and transaction rollback rates to detect system-level saturation.
        """
        conn = get_readonly_connection()
        try:
            with conn.cursor() as cur:
                # 1. Connection states
                cur.execute("""
                    SELECT 
                        count(*) FILTER (WHERE state = 'active') AS active_connections,
                        count(*) FILTER (WHERE state = 'idle') AS idle_connections,
                        count(*) AS total_connections
                    FROM pg_stat_activity 
                    WHERE pid <> pg_backend_pid();
                """)
                conn_row = cur.fetchone()

                # 2. Database buffer cache hit ratio (Target: > 99%)
                cur.execute("""
                    SELECT 
                        ROUND(sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read) + 0.0001) * 100, 2) AS cache_hit_ratio
                    FROM pg_statio_user_tables;
                """)
                cache_hit = cur.fetchone()[0]

                return {
                    "active_connections": conn_row[0],
                    "idle_connections": conn_row[1],
                    "total_connections": conn_row[2],
                    "cache_hit_ratio_percentage": float(cache_hit) if cache_hit else 100.0,
                    "status": "Healthy" if cache_hit and cache_hit > 95 else "Degraded - High disk read ratio"
                }
        finally:
            conn.close()