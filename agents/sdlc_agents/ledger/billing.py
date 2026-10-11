"""
What Azure actually billed. Reads Azure Cost Management for the resource group (month to date, grouped by
meter category) with the ledger's own managed identity, which needs `Cost Management Reader` on the
group. Cost data lags by hours, so the figure carries its read time and is shown next to the ledger's
own estimate, never instead of it. Stdlib only.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from sdlc_agents.transport import HttpRequest, Transport, urllib_transport

SCOPE = "https://management.azure.com/.default"
API_VERSION = "2023-11-01"


class TokenCredential(Protocol):
    def get_token(self, *scopes: str, **kwargs: Any) -> Any: ...


class BillingPort(Protocol):
    def observe(self, now: str) -> dict[str, Any]: ...


class AzureBilling:
    def __init__(
        self,
        credential: TokenCredential,
        subscription_id: str,
        resource_group: str,
        *,
        transport: Transport = urllib_transport,
    ):
        self._credential = credential
        self._scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        self._transport = transport

    def observe(self, now: str) -> dict[str, Any]:
        token = self._credential.get_token(SCOPE).token
        body = {
            "type": "ActualCost",
            "timeframe": "MonthToDate",
            "dataset": {
                "granularity": "None",
                "aggregation": {"usd": {"name": "CostUSD", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "MeterCategory"}],
            },
        }
        resp = self._transport(
            HttpRequest(
                "POST",
                f"https://management.azure.com{self._scope}/providers/Microsoft.CostManagement/query?api-version={API_VERSION}",
                {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json.dumps(body).encode(),
                60.0,
            )
        )
        if resp.status != 200:
            raise RuntimeError(f"Cost Management returned HTTP {resp.status}")
        props = json.loads(resp.body)["properties"]
        names = [c["name"] for c in props["columns"]]
        usd, meter = names.index("CostUSD"), names.index("MeterCategory")
        meters = sorted(
            ({"name": str(r[meter]), "usd": round(float(r[usd]), 4)} for r in props["rows"]), key=lambda m: -m["usd"]
        )
        return {
            "source": "azure-cost-management",
            "billed_usd": round(sum(m["usd"] for m in meters), 4),
            "currency": "USD",
            "as_of": now,
            "by_meter": meters,
            "scope": self._scope.rsplit("/", 1)[-1],
        }
