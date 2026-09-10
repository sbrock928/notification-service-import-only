"""Pure, channel-specific presentation helpers."""

from notification_service.presentation.email import RenderedEmail, render_email
from notification_service.presentation.tables import BoundedTable, TableRenderPolicy, bound_tables

__all__ = ["BoundedTable", "RenderedEmail", "TableRenderPolicy", "bound_tables", "render_email"]
