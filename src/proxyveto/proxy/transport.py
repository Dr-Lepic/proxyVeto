from __future__ import annotations

import asyncio
import json
import os
import sys
from abc import ABC, abstractmethod
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class Transport(ABC):
    """Abstract transport for MCP communication."""

    @abstractmethod
    async def read_message(self) -> dict[str, Any] | None:
        """Read a single JSON-RPC message. Returns None on EOF."""
        pass

    @abstractmethod
    async def write_message(self, message: dict[str, Any]) -> None:
        """Write a JSON-RPC message."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the transport."""
        pass


class StdioTransport(Transport):
    """Stdio transport for MCP (newline-delimited JSON-RPC)."""

    def __init__(self, reader: asyncio.StreamReader | None = None, writer: Any | None = None):
        self._reader = reader
        self._writer = writer
        self._stdin_reader: asyncio.StreamReader | None = None
        self._stdout_writer: Any | None = None

    async def _ensure_stdio(self) -> None:
        """Initialize stdio streams if not provided."""
        if self._reader is None or self._writer is None:
            loop = asyncio.get_event_loop()
            self._stdin_reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(self._stdin_reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)

            # Use a simple approach for stdout
            self._stdout_writer = sys.stdout

    async def read_message(self) -> dict[str, Any] | None:
        """Read a JSON-RPC message from stdin."""
        await self._ensure_stdio()

        assert self._stdin_reader is not None
        line = await self._stdin_reader.readline()
        if not line:
            return None

        line = line.decode("utf-8").strip()
        if not line:
            return await self.read_message()  # Skip empty lines

        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            logger.error("stdio_transport_json_decode_error", error=str(e), line=line[:200])
            raise

    async def write_message(self, message: dict[str, Any]) -> None:
        """Write a JSON-RPC message to stdout."""
        await self._ensure_stdio()

        assert self._stdout_writer is not None
        line = json.dumps(message, separators=(",", ":")) + "\n"
        self._stdout_writer.write(line)
        self._stdout_writer.flush()

    async def close(self) -> None:
        """Close the transport."""
        if self._stdout_writer:
            self._stdout_writer.close()
            await self._stdout_writer.wait_closed()


class MCPServerTransport(Transport):
    """Transport for communicating with upstream MCP server via stdio subprocess."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None):
        self.command = command
        self.env = env or {}
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def start(self) -> None:
        """Start the upstream MCP server subprocess."""
        merged_env = {**os.environ, **self.env}
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        self._reader = self._process.stdout
        self._writer = self._process.stdin

        # Start stderr logging
        asyncio.create_task(self._log_stderr())

        logger.info("mcp_server_started", command=self.command, pid=self._process.pid)

    async def _log_stderr(self) -> None:
        """Log stderr from upstream server."""
        assert self._process is not None
        assert self._process.stderr is not None

        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            logger.debug("mcp_server_stderr", server=self.command[0], line=line.decode().strip())

    async def read_message(self) -> dict[str, Any] | None:
        """Read a JSON-RPC message from upstream server."""
        if not self._reader:
            return None

        line = await self._reader.readline()
        if not line:
            return None

        line = line.decode("utf-8").strip()
        if not line:
            return await self.read_message()

        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            logger.error("mcp_server_json_decode_error", error=str(e), line=line[:200])
            raise

    async def write_message(self, message: dict[str, Any]) -> None:
        """Write a JSON-RPC message to upstream server."""
        if not self._writer:
            return

        line = json.dumps(message, separators=(",", ":")) + "\n"
        self._writer.write(line.encode("utf-8"))
        await self._writer.drain()

    async def close(self) -> None:
        """Close the upstream server process."""
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            logger.info("mcp_server_stopped", command=self.command[0])