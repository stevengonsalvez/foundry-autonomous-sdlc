"""
Key Vault secrets adapter for SecretsPort (REST over urllib, Entra token from azure-identity).

The vault URL must be an https *.vault.azure.net host; secret names are validated before they go
into a URL. Values are cached for the life of the process and never logged or put in errors.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Protocol

from sdlc_agents.transport import HttpRequest, Transport, urllib_transport

API_VERSION = "7.4"
SCOPE = "https://vault.azure.net/.default"
_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,127}$")


class TokenCredential(Protocol):
    def get_token(self, *scopes: str, **kwargs: Any) -> Any: ...


class SecretError(RuntimeError):
    pass


class KeyVaultSecrets:
    def __init__(self, vault_url: str, credential: TokenCredential, *, transport: Transport = urllib_transport):
        parsed = urllib.parse.urlparse(vault_url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".vault.azure.net"):
            raise ValueError(f"not a Key Vault URL: {vault_url!r}")
        self._base = f"https://{parsed.hostname}"
        self._credential = credential
        self._transport = transport
        self._cache: dict[str, str] = {}

    def __repr__(self) -> str:
        return f"KeyVaultSecrets({self._base})"

    def get_secret(self, name: str) -> str:
        if not _NAME_RE.match(name):
            raise ValueError(f"invalid secret name: {name!r}")
        if name in self._cache:
            return self._cache[name]
        token = self._credential.get_token(SCOPE).token
        resp = self._transport(HttpRequest(
            "GET", f"{self._base}/secrets/{name}?api-version={API_VERSION}",
            {"Authorization": f"Bearer {token}", "Accept": "application/json"},
        ))
        if resp.status != 200:
            raise SecretError(f"Key Vault returned {resp.status} for secret {name}")
        value = json.loads(resp.body).get("value")
        if not isinstance(value, str) or not value:
            raise SecretError(f"secret {name} is empty")
        self._cache[name] = value
        return value
