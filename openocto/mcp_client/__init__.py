"""openocto.mcp_client — MCP client for consuming external MCP servers.

Public API::

    from openocto.mcp_client import (
        MCPClient,
        MCPClientRegistry,
        MCPRemoteToolSkill,
        MCPServerStore,
        MCPSecretsStore,
        MCPClientError,
        MCPTransportError,
        MCPProtocolError,
        MCPNotConnected,
    )
"""

from openocto.mcp_client.client import (
    MCPClient,
    MCPClientError,
    MCPNotConnected,
    MCPProtocolError,
    MCPStdioClient,
    MCPTransportError,
)
from openocto.mcp_client.adapter import MCPRemoteToolSkill
from openocto.mcp_client.registry import MCPClientRegistry
from openocto.mcp_client.secrets import MCPSecretsStore
from openocto.mcp_client.store import MCPServerStore

__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPClientRegistry",
    "MCPNotConnected",
    "MCPProtocolError",
    "MCPRemoteToolSkill",
    "MCPSecretsStore",
    "MCPServerStore",
    "MCPStdioClient",
    "MCPTransportError",
]
