"""Authentication port and an Entra client-credential implementation."""

from __future__ import annotations

from typing import Protocol


class AccessToken(Protocol):
    async def get(self) -> str: ...

    async def invalidate(self) -> None: ...

    async def aclose(self) -> None: ...


class ClientSecretToken:
    """Unattended Entra application credential for Microsoft Graph."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        from azure.identity.aio import ClientSecretCredential

        self._credential = ClientSecretCredential(tenant_id, client_id, client_secret)

    async def get(self) -> str:
        token = await self._credential.get_token("https://graph.microsoft.com/.default")
        return str(token.token)

    async def invalidate(self) -> None:
        await self._credential.close()

    async def aclose(self) -> None:
        await self._credential.close()
