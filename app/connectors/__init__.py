"""Connectors — the real trust boundary.

The one-sentence security model: **the prompt is not the boundary, the connector
is.** Under ``data_scope: caller_tenant`` the connector layer injects the
caller's resolved scope into every outbound call *below the model*, so a
prompt-injected "show me other tenants" physically cannot escape.
"""
from .base import Connector, ConnectorResult
from .http_connector import HttpConnector
from .mcp_connector import McpConnector
from .static_connector import StaticConnector

__all__ = [
    "Connector",
    "ConnectorResult",
    "HttpConnector",
    "McpConnector",
    "StaticConnector",
    "build_connector",
]


def build_connector(spec):
    """Instantiate a connector from its :class:`AgentDefinition` spec."""
    mapping = {
        "http": HttpConnector,
        "mcp": McpConnector,
        "static": StaticConnector,
    }
    cls = mapping.get(spec.kind, StaticConnector)
    return cls(spec.name, spec.config)
