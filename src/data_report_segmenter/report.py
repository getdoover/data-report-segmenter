"""Pure report-building logic: variable-tree walk, value extraction, CSV.

No pydoover / IO dependencies. The processor fetches the ui_state aggregate
and ui_state history messages; everything here operates on the plain dicts
those return so it can be unit-tested without a client.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import NamedTuple

NUMERIC_VAR_TYPES = ("float", "integer")


class VariableRef(NamedTuple):
    """A NumericVariable discovered in the ui_state tree.

    - ``column`` is the CSV header for this variable: ``<app_key>.<var...>``.
    - ``field_path`` is the dotted path (rooted at ``state``) at which the
      value lives in both the ui_state aggregate and each ui_state message,
      e.g. ``state.children.<app_key>.children.<var>.currentValue``.
    """

    column: str
    field_path: str


def _walk_children(
    children: dict,
    column_prefix: str,
    path_prefix: str,
    out: list[VariableRef],
) -> None:
    for name, node in children.items():
        if not isinstance(node, dict):
            continue
        column = f"{column_prefix}.{name}"
        node_path = f"{path_prefix}.children.{name}"
        node_type = node.get("type")
        var_type = node.get("varType")
        if node_type == "uiVariable" and var_type in NUMERIC_VAR_TYPES:
            out.append(
                VariableRef(column=column, field_path=f"{node_path}.currentValue")
            )
        # Recurse into submodules / containers regardless of this node's type.
        grandchildren = node.get("children")
        if isinstance(grandchildren, dict) and grandchildren:
            _walk_children(grandchildren, column, node_path, out)


def walk_numeric_variables(
    ui_state_aggregate: dict, own_app_key: str
) -> list[VariableRef]:
    """All NumericVariables in the ui_state aggregate, excluding our own subtree.

    Walks ``state.children.<app_key>.children.*`` recursively (into
    submodules) and collects nodes with ``type == "uiVariable"`` and
    ``varType in ("float", "integer")``. The app's own ``own_app_key``
    subtree is skipped so the report never reports on itself.
    """
    out: list[VariableRef] = []
    state = ui_state_aggregate.get("state")
    if not isinstance(state, dict):
        return out
    app_children = state.get("children")
    if not isinstance(app_children, dict):
        return out

    for app_key, app_node in app_children.items():
        if app_key == own_app_key:
            continue
        if not isinstance(app_node, dict):
            continue
        children = app_node.get("children")
        if not isinstance(children, dict):
            continue
        _walk_children(
            children,
            column_prefix=app_key,
            path_prefix=f"state.children.{app_key}",
            out=out,
        )

    # Stable ordering by column name for deterministic CSV headers.
    out.sort(key=lambda r: r.column)
    return out


def get_by_path(data: dict, dotted_path: str):
    """Navigate a dotted path through nested dicts. Returns None if absent."""
    node = data
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def is_numeric(value) -> bool:
    """True for int/float (excluding bool) values usable as report data."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def extract_row_values(
    message_data: dict, var_refs: list[VariableRef]
) -> dict[str, float]:
    """Extract the numeric currentValue of each variable from one ui_state message.

    Only genuinely-numeric values are kept; a variable whose value is absent
    or a non-numeric string (e.g. an unresolved ``$``-tag reference) is left
    out of the row so its cell renders blank.

    TODO-verify (see PLAN "Report semantics" / data-plane.md §3): some apps
    publish ``currentValue`` as a *live tag reference* string rather than a
    literal number. When that is detected for a variable across a report, the
    verification phase should add a fallback that sources that variable's
    history from ``tag_values`` messages (``<app_key>.<tag>``) instead of
    ui_state. This function keeps only literal numerics; the fallback is not
    yet wired.
    """
    values: dict[str, float] = {}
    for ref in var_refs:
        raw = get_by_path(message_data, ref.field_path)
        if is_numeric(raw):
            values[ref.column] = raw
    return values


def ms_to_datetime(epoch_ms: int) -> datetime:
    """Timezone-aware UTC datetime for an epoch-ms timestamp.

    TIME bounds passed to ``list_messages`` MUST be datetimes: pydoover's
    ``_to_snowflake`` (api/data/_base.py) converts only ``datetime`` values
    via ``generate_snowflake_id_at`` and passes ints through UNCHANGED —
    an int is treated as an already-formed snowflake message ID, so an
    epoch-ms int (~1.8e12, vs real snowflakes ~2e17) silently selects an
    empty window near the Doover epoch.
    """
    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)


def format_timestamp_utc(epoch_ms: int) -> str:
    """ISO-8601 UTC string for an epoch-ms timestamp."""
    return ms_to_datetime(epoch_ms).isoformat()


def next_page_cursor(
    message_ids: list[int], prev_cursor: int | None, page_limit: int
) -> int | None:
    """Backward-paging termination / next-cursor decision.

    ``message_ids`` are the snowflake message IDs returned for the current
    page; ``prev_cursor`` is the int snowflake cursor this page was fetched
    with (None on the first page, whose ``before`` bound is a datetime).

    Returns the int snowflake ID to pass as the next ``before=`` cursor
    (genuine message IDs ARE ints to ``list_messages``), or None when paging
    is complete: an empty or short page means the range is exhausted, and an
    unchanged cursor means no progress (guards against re-fetch loops). The
    int-vs-datetime asymmetry of the first page never reaches the equality
    check because ``prev_cursor`` is None there.
    """
    if not message_ids or len(message_ids) < page_limit:
        return None
    oldest = min(message_ids)
    if prev_cursor is not None and oldest == prev_cursor:
        return None
    return oldest


def render_csv(var_refs: list[VariableRef], rows: list[dict]) -> bytes:
    """Render report rows to CSV bytes with the stdlib csv module.

    Header: ``timestamp_utc,segment_kind,<col>,...`` in ``var_refs`` order.
    Each row dict is ``{"timestamp_utc": str, "segment_kind": str,
    "values": {col: number}}``. Rows are emitted in ascending timestamp
    order; missing cells render blank.
    """
    columns = [ref.column for ref in var_refs]
    header = ["timestamp_utc", "segment_kind", *columns]

    ordered = sorted(rows, key=lambda r: r["timestamp_utc"])

    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in ordered:
        values = row.get("values", {})
        line = [row["timestamp_utc"], row["segment_kind"]]
        for col in columns:
            cell = values.get(col)
            line.append("" if cell is None else cell)
        writer.writerow(line)

    return buf.getvalue().encode("utf-8")


def _sanitize(part: str) -> str:
    """Filename-safe token: alnum runs kept, everything else -> single '_'."""
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", part).strip("_")
    return cleaned or "unnamed"


def build_report_filename(app_name: str, kind: str, start_ts: int, end_ts: int) -> str:
    """``{app_name}_{kind}_{YYYYMMDD}-{YYYYMMDD}.csv``, sanitised."""
    start = datetime.fromtimestamp(start_ts / 1000.0, tz=timezone.utc)
    end = datetime.fromtimestamp(end_ts / 1000.0, tz=timezone.utc)
    return (
        f"{_sanitize(app_name)}_{_sanitize(kind)}_"
        f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}.csv"
    )
