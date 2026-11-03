from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MCPSettings:
    banking_api_url: str = field(
        default_factory=lambda: os.environ.get("BANKING_API_URL", "http://localhost:8000")
    )
    agent_client_id: str = field(
        default_factory=lambda: os.environ.get("AGENT_CLIENT_ID", "assistant-v1")
    )
    agent_client_secret: str = field(
        default_factory=lambda: os.environ.get("AGENT_CLIENT_SECRET", "")
    )
    # The delegated customer token (customer scopes minus transfers:confirm,
    # azp=<this agent>) - see `make login` and docs/security.md. The MCP
    # server never sees a token with transfers:confirm.
    customer_token: str = field(default_factory=lambda: os.environ.get("CUSTOMER_TOKEN", ""))


mcp_settings = MCPSettings()
