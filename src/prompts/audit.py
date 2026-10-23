from fastmcp import FastMCP



def register_prompts(mcp):
  @mcp.prompt()
  def audit_query_performance(sql_query: str) -> str:
      """Pre-engineered prompt instructing Claude to review an EXPLAIN plan."""
      return f"""
      Please perform a deep PostgreSQL performance audit for this query:
      ```sql
      {sql_query}
      ```
      
      Instructions:
      1. Call the 'explain_query_plan' tool with run_analyze=True.
      2. Check the table's schema via 'postgres://schema/posts'.
      3. Identify whether it uses Sequential Scans or expensive in-memory Sorts.
      4. Provide the exact 'CREATE INDEX CONCURRENTLY' statements needed to fix the bottlenecks.
      """
  @mcp.prompt()
  def begginer_audit_query_performance(sql_query: str)->str:
     
      """Pre-engineered prompt instructing Claude to review an EXPLAIN plan."""
      return f"""
      Please perform a deep PostgreSQL performance audit for this query:
      ```sql
      {sql_query}
      ```
      
      Instructions:
      1. Call the 'explain_query_plan' tool with run_analyze=True.
      2. Check the table's schema via 'postgres://schema/posts'.
      3. Identify whether it uses Sequential Scans or expensive in-memory Sorts.
      4. Provide the exact 'CREATE INDEX CONCURRENTLY' statements needed to fix the bottlenecks.
      """


  @mcp.prompt()
  def full_database_performance_checkup() -> str:
      """Automated end-to-end database diagnostic workflow for Claude."""
      return """
      You are an expert PostgreSQL Database Reliability Engineer.
      Please execute a full database health and performance checkup:
      
      1. First, call 'get_database_health_metrics' to assess connection saturation and cache hit rates.
      2. Next, call 'auto_recommend_indexes' to automatically inspect sequential scans, existing indexes, and unindexed foreign keys.
      3. If any tables have sequential scans or missing indexes, call 'get_table_schema' to examine data types.
      4. Provide an executive summary with:
        - System Health Grade (A/B/C/F)
        - The top 3 performance bottlenecks
        - Copy-paste ready 'CREATE INDEX CONCURRENTLY' SQL commands to resolve them immediately.
      """