"""Future Microsoft Graph adapters using the same application ports."""

from notification_service.providers.microsoft_graph.auth import AccessToken, ClientSecretToken
from notification_service.providers.microsoft_graph.outlook import GraphEmailProvider
from notification_service.providers.microsoft_graph.teams import GraphTeamsProvider, TeamsChannel

__all__ = [
    "AccessToken",
    "ClientSecretToken",
    "GraphEmailProvider",
    "GraphTeamsProvider",
    "TeamsChannel",
]
