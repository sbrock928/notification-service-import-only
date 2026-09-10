"""Bound structured tables without interpreting their values."""

from __future__ import annotations

from dataclasses import dataclass

from notification_service.domain.models import (
    MAX_BODY_BYTES,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    NotificationTable,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TableRenderPolicy:
    max_rows: int = 100
    max_columns: int = 12
    email_body_bytes: int = MAX_BODY_BYTES
    teams_payload_bytes: int = MAX_BODY_BYTES

    def __post_init__(self) -> None:
        if not 1 <= self.max_rows <= MAX_TABLE_ROWS:
            raise ValueError("max_rows must be between 1 and 1000")
        if not 1 <= self.max_columns <= MAX_TABLE_COLUMNS:
            raise ValueError("max_columns must be between 1 and 50")
        if not 1 <= self.email_body_bytes <= MAX_BODY_BYTES:
            raise ValueError("email_body_bytes must be between 1 and 1 MiB")
        if not 1 <= self.teams_payload_bytes <= MAX_BODY_BYTES:
            raise ValueError("teams_payload_bytes must be between 1 and 1 MiB")


@dataclass(frozen=True, slots=True)
class BoundedTable:
    caption: str | None
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    omitted_rows: int
    omitted_columns: int


def bound_tables(
    tables: tuple[NotificationTable, ...],
    policy: TableRenderPolicy,
    *,
    row_limits: tuple[int, ...] | None = None,
) -> tuple[BoundedTable, ...]:
    if row_limits is None:
        row_limits = tuple(policy.max_rows for _ in tables)
    return tuple(
        BoundedTable(
            caption=table.caption,
            columns=table.columns[: policy.max_columns],
            rows=tuple(tuple(row[: policy.max_columns]) for row in table.rows[: row_limits[index]]),
            omitted_rows=max(0, len(table.rows) - row_limits[index]),
            omitted_columns=max(0, len(table.columns) - policy.max_columns),
        )
        for index, table in enumerate(tables)
    )


def reduce_largest_row_limit(row_limits: list[int]) -> bool:
    candidates = [index for index, value in enumerate(row_limits) if value > 0]
    if not candidates:
        return False
    index = max(candidates, key=row_limits.__getitem__)
    row_limits[index] -= 1
    return True
