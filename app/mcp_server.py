"""Exposes the four tools in tools.py over MCP stdio.

The agent talks to this server as a subprocess; Claude Code or Claude Desktop can use the same server.
Run it with: python -m app.mcp_server
"""

from mcp.server.mcpserver import MCPServer

from app import retrieval, tools

server = MCPServer(
    "clearance",
    instructions="Access request tools. Files access requests as GitLab issues; never grants access.",
)

for fn in (tools.search_handbook, tools.get_employee, tools.check_existing_access, tools.create_access_request):
    server.tool()(fn)


if __name__ == "__main__":
    retrieval.embed_query("warm up")  # load the embedding model before the first real query
    server.run()
