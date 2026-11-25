"""MCP-Server (L 8.1, T 2.8), als ASGI-App unter /mcp. Implementierung: Task 5.3 (P5)."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dock")

# Tools werden in Task 5.3 gegen die REST-API/Op-Pipeline implementiert (search, get_document, apply_ops, …).
