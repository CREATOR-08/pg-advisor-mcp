import sys
from pathlib import Path
import os 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP
from tools.explain import register_explain_tools
from resources.schema import register_db_resources
from prompts.audit import register_prompts

mcp = FastMCP(
    "database-query-optimiser",
    instructions="Local PostgreSQL Query & Migration Safety Analyzer."
)

# Register tool modules
register_explain_tools(mcp)

# Register resource for schema inspection
register_db_resources(mcp)

#register mcp propmts
register_prompts(mcp)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f" Starting Remote MCP Server on http://{host}:{port}/sse ...")
    mcp.run(transport="sse", host=host, port=port)