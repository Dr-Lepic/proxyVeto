#!/usr/bin/env python3
"""
Dangerous Tools MCP Server for testing ProxyVeto.

This server exposes intentionally dangerous tools to test the JEV evaluation
and policy engine.
"""

import json
import os
import sys
import subprocess
from typing import Any
from mcp.server.lowlevel import Server
from mcp import types
from mcp.server.stdio import stdio_server


app = Server("dangerous-tools")


@app.add_request_handler("tools/list", types.ListToolsRequest)
async def list_tools(request: types.ListToolsRequest) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="execute_shell_command",
                description="Execute arbitrary shell command (DANGEROUS)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"},
                    },
                    "required": ["command"],
                },
            ),
            types.Tool(
                name="write_file",
                description="Write content to any file path (DANGEROUS)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to write"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
            ),
            types.Tool(
                name="delete_file",
                description="Delete any file or directory (DANGEROUS)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to delete"},
                        "recursive": {"type": "boolean", "description": "Delete recursively", "default": False},
                    },
                    "required": ["path"],
                },
            ),
            types.Tool(
                name="read_file",
                description="Read any file (less dangerous)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to read"},
                    },
                    "required": ["path"],
                },
            ),
            types.Tool(
                name="http_request",
                description="Make arbitrary HTTP request (DANGEROUS)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"], "default": "GET"},
                        "url": {"type": "string", "description": "URL to request"},
                        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                        "body": {"type": "string"},
                    },
                    "required": ["url"],
                },
            ),
            types.Tool(
                name="sql_query",
                description="Execute arbitrary SQL query (DANGEROUS)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SQL query to execute"},
                        "database": {"type": "string", "description": "Database path", "default": ":memory:"},
                    },
                    "required": ["query"],
                },
            ),
        ]
    )


@app.add_request_handler("tools/call", types.CallToolRequest)
async def call_tool(request: types.CallToolRequest) -> types.CallToolResult:
    name = request.params.name
    arguments = request.params.arguments or {}

    if name == "execute_shell_command":
        command = arguments["command"]
        # WARNING: This is intentionally dangerous for testing
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\nreturncode: {result.returncode}"
        return types.CallToolResult(content=[types.TextContent(type="text", text=output)])

    elif name == "write_file":
        path = arguments["path"]
        content = arguments["content"]
        with open(path, "w") as f:
            f.write(content)
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Written to {path}")])

    elif name == "delete_file":
        path = arguments["path"]
        recursive = arguments.get("recursive", False)
        if recursive:
            import shutil
            shutil.rmtree(path)
        else:
            os.remove(path)
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Deleted {path}")])

    elif name == "read_file":
        path = arguments["path"]
        with open(path, "r") as f:
            content = f.read()
        return types.CallToolResult(content=[types.TextContent(type="text", text=content)])

    elif name == "http_request":
        import urllib.request
        import urllib.error
        method = arguments.get("method", "GET")
        url = arguments["url"]
        headers = arguments.get("headers", {})
        body = arguments.get("body", "")
        req = urllib.request.Request(url, data=body.encode() if body else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return types.CallToolResult(content=[types.TextContent(type="text", text=f"Status: {response.status}\n{response.read().decode()}")])
        except urllib.error.HTTPError as e:
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"HTTP Error: {e.code}\n{e.read().decode()}")])
        except Exception as e:
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"Error: {e}")])

    elif name == "sql_query":
        import sqlite3
        query = arguments["query"]
        database = arguments.get("database", ":memory:")
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            if query.strip().upper().startswith("SELECT"):
                rows = cursor.fetchall()
                return types.CallToolResult(content=[types.TextContent(type="text", text=str(rows))])
            else:
                conn.commit()
                return types.CallToolResult(content=[types.TextContent(type="text", text=f"Rows affected: {cursor.rowcount}")])
        except Exception as e:
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"SQL Error: {e}")])
        finally:
            conn.close()

    else:
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Unknown tool: {name}")])


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())