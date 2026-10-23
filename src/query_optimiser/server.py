import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP

from prompts.audit import register_prompts
from resources.schema import register_db_resources
from tools.explain import register_explain_tools

mcp = FastMCP(
    "database-query-optimiser",
    instructions="Local PostgreSQL Query & Migration Safety Analyzer.",
)

# Register tool modules
register_explain_tools(mcp)

# Register resource for schema inspection
register_db_resources(mcp)

# register mcp prompts
register_prompts(mcp)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f" Starting Remote MCP Server on http://{host}:{port}/sse ...")
    asyncio.run(mcp.run_async(transport="sse", host=host, port=port))