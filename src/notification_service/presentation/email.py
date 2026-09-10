"""Safe Outlook-compatible email presentation."""

from __future__ import annotations

import html
from dataclasses import dataclass

from notification_service.domain.errors import ValidationError
from notification_service.domain.models import EmailNotification
from notification_service.presentation.tables import (
    BoundedTable,
    TableRenderPolicy,
    bound_tables,
    reduce_largest_row_limit,
)

_TABLE_STYLE = "border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:12px"
_CELL_STYLE = "border:1px solid #b7b7b7;padding:4px 6px;text-align:left;vertical-align:top"


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    text: str
    html: str | None


def _summary(table: BoundedTable) -> str | None:
    parts: list[str] = []
    if table.omitted_rows:
        parts.append(f"{table.omitted_rows} row(s)")
    if table.omitted_columns:
        parts.append(f"{table.omitted_columns} column(s)")
    return None if not parts else "Omitted from this presentation: " + " and ".join(parts) + "."


def _plain_table(table: BoundedTable) -> str:
    lines: list[str] = []
    if table.caption:
        lines.append(table.caption)
    lines.append(" | ".join(table.columns))
    lines.append(" | ".join("---" for _ in table.columns))
    lines.extend(
        " | ".join(cell.replace("\r", " ").replace("\n", " ") for cell in row) for row in table.rows
    )
    summary = _summary(table)
    if summary:
        lines.append(summary)
    return "\n".join(lines)


def _html_table(table: BoundedTable) -> str:
    values = [f'<table role="table" style="{_TABLE_STYLE}">']
    if table.caption:
        values.append(
            f'<caption style="font-weight:600;text-align:left;padding:4px 0">'
            f"{html.escape(table.caption)}</caption>"
        )
    values.append("<thead><tr>")
    values.extend(
        f'<th scope="col" style="{_CELL_STYLE}">{html.escape(value)}</th>'
        for value in table.columns
    )
    values.append("</tr></thead><tbody>")
    for row in table.rows:
        values.append("<tr>")
        values.extend(f'<td style="{_CELL_STYLE}">{html.escape(cell)}</td>' for cell in row)
        values.append("</tr>")
    values.append("</tbody></table>")
    summary = _summary(table)
    if summary:
        values.append(f'<p style="font-size:12px;color:#595959">{html.escape(summary)}</p>')
    return "".join(values)


def _render(notification: EmailNotification, tables: tuple[BoundedTable, ...]) -> RenderedEmail:
    table_text = "\n\n".join(_plain_table(table) for table in tables)
    text = notification.text if not table_text else f"{notification.text}\n\n{table_text}"
    if notification.html is None and not tables:
        rendered_html = None
    else:
        base_html = notification.html
        if base_html is None:
            base_html = (
                '<div style="font-family:Segoe UI,Arial,sans-serif">'
                + html.escape(notification.text).replace("\n", "<br>")
                + "</div>"
            )
        rendered_html = base_html + "".join(_html_table(table) for table in tables)
    return RenderedEmail(text, rendered_html)


def render_email(
    notification: EmailNotification,
    policy: TableRenderPolicy | None = None,
) -> RenderedEmail:
    policy = policy or TableRenderPolicy()
    row_limits = [min(policy.max_rows, len(table.rows)) for table in notification.tables]
    while True:
        rendered = _render(
            notification,
            bound_tables(notification.tables, policy, row_limits=tuple(row_limits)),
        )
        text_size = len(rendered.text.encode("utf-8"))
        html_size = len(rendered.html.encode("utf-8")) if rendered.html is not None else 0
        if text_size <= policy.email_body_bytes and html_size <= policy.email_body_bytes:
            return rendered
        if not reduce_largest_row_limit(row_limits):
            raise ValidationError("Email content cannot fit within the configured body limit")
