"""Graph token port and an optional client-secret implementation."""

from __future__ import annotations

from typing import Protocol


class AccessToken(Protocol):
    async def get(self) -> str: ...

    async def invalidate(self) -> None: ...

    async def aclose(self) -> None: ...


class ClientSecretToken:
    """Lazy Entra client credential for global Microsoft Graph."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        if not tenant_id or not client_id or not client_secret:
            raise ValueError("Tenant, client, and secret values are required")
        self._configuration = (tenant_id, client_id, client_secret)
        self._credential: object | None = None

    def _get_credential(self) -> object:
        if self._credential is None:
            from azure.identity.aio import ClientSecretCredential

            self._credential = ClientSecretCredential(*self._configuration)
        return self._credential

    async def get(self) -> str:
        credential = self._get_credential()
        token = await credential.get_token("https://graph.microsoft.com/.default")  # type: ignore[attr-defined]
        return str(token.token)

    async def invalidate(self) -> None:
        return None

    async def aclose(self) -> None:
        if self._credential is not None:
            await self._credential.close()  # type: ignore[attr-defined]
