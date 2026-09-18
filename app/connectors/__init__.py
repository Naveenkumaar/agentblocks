"""Connectors — where outbound access is scoped and enforced.

Enforcement lives below the model, not in the prompt: under
``data_scope: caller_tenant`` the connector layer merges the caller's resolved
scope into every outbound call, so an injected "show me other tenants" cannot
widen its own access.
"""
from .agent_connector import AgentConnector
from .base import Connector, ConnectorResult
from .http_connector import HttpConnector
from .mcp_connector import McpConnector
from .static_connector import StaticConnector
from .weather_connector import OpenMeteoConnector

__all__ = [
    "Connector",
    "ConnectorResult",
    "HttpConnector",
    "McpConnector",
    "StaticConnector",
    "OpenMeteoConnector",
    "AgentConnector",
    "build_connector",
]


def build_connector(spec):
    """Instantiate a connector from its :class:`AgentDefinition` spec."""
    mapping = {
        "http": HttpConnector,
        "mcp": McpConnector,
        "static": StaticConnector,
        "weather": OpenMeteoConnector,
        "agent": AgentConnector,
    }
    cls = mapping.get(spec.kind, StaticConnector)
    return cls(spec.name, spec.config)
