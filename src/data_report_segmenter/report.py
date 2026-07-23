"""Pure report-building logic: variable-tree walk, value extraction, CSV.

No pydoover / IO dependencies. The app is tag-reference-native: it reads the
ui_state aggregate to discover WHICH numeric variables exist, follows each
one's ``$tag`` reference to a location in tag_values, then reads the actual
value history from tag_values messages. Everything here operates on the plain
dicts the client returns so it can be unit-tested without a client.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import NamedTuple

NUMERIC_VAR_TYPES = ("float", "integer")
_TAG_LOOKUP_TYPES = ("string", "number", "boolean", "array", "object")

# Convention for the volume summary block: an upstream app (e.g. a
# per-segment volume totaliser) publishes a running grand total under
# VOLUME_TOTAL_KEY and a JSON object mapping segment kind -> cumulative volume
# under SEGMENT_TOTALS_KEY. A report scans tag_values for any app carrying both
# and summarises them (see discover_volume_totals).
VOLUME_TOTAL_KEY = "total_volume"
SEGMENT_TOTALS_KEY = "segment_totals_json"

# Synthetic column that replaces the grand-total ``total_volume`` column in a
# per-pipeline report: a running total scoped to the report's own kind, read
# from segment_totals_json (see find_total_volume_ref / pipeline_total_value).
PIPELINE_TOTAL_COL = "__pipeline_total__"
PIPELINE_TOTAL_LABEL = "Total Injected Volume"


class VariableRef(NamedTuple):
    """A NumericVariable discovered in ui_state, resolved to its tag source.

    - ``column`` is the internal, unique key for this variable
      (``<app_key>.<var...>``): it keys the extracted value map and fixes the
      CSV column *order*, but is never shown to the user.
    - ``label`` is the human CSV header — the variable's ui ``displayString``
      (exactly what the operator reads in the widget), falling back to the
      variable's own key when it carries no displayString.
    - ``path`` is the key path into a ``tag_values`` message/aggregate where
      the value actually lives, e.g. ``("4_20ma_sensor_1", "value")``.
      ui_state carries only the *reference* ($tag...) to this location, never
      the value history — so the report reads history from tag_values here.
    - ``units`` is the variable's ui ``units`` attribute (e.g. ``"%"``, ``"m"``,
      ``"L"``), appended to the CSV header as ``label (units)`` when non-empty
      (see column_header). Empty ``""`` when the node carries no units — 4-20mA
      columns bake their unit into ``displayString`` instead, so they render
      unchanged.
    """

    column: str
    label: str
    path: tuple[str, ...]
    units: str = ""


def parse_tag_ref(ref, context_app_key: str) -> tuple[str, ...] | None:
    """Resolve a ``$tag`` lookup string to a key path into ``tag_values``.

    ui_state NumericVariables carry their value as a tag reference in the
    compact lookup format (customer-site TAG_VALUE_LOOKUPS):

        ``$tag.<json_path>[:<type>[:<default>]]``

    e.g. ``$tag.app().value:number:null``. ``app()`` resolves to the owning
    application key (``context_app_key``); the remaining dotted path indexes
    into that app's tag_values block. A JSONPath never contains ``:``, so the
    optional ``:type``/``:default`` suffix is everything after the first
    ``:`` and is discarded — the report keeps genuinely-numeric values only,
    so coercion/defaulting is unnecessary. Returns the resolved key tuple
    (e.g. ``("4_20ma_sensor_1", "value")``), or ``None`` if ``ref`` is not a
    ``$tag`` reference.
    """
    if not isinstance(ref, str) or not ref.startswith("$tag."):
        return None
    body = ref[len("$tag.") :]
    path_str = body.split(":", 1)[0]  # json path is everything before ':'
    segments = [
        context_app_key if seg == "app()" else seg
        for seg in path_str.split(".")
        if seg != ""
    ]
    return tuple(segments) or None


def _walk_children(
    children: dict,
    column_prefix: str,
    context_app_key: str,
    out: list[VariableRef],
) -> None:
    for name, node in children.items():
        if not isinstance(node, dict):
            continue
        column = f"{column_prefix}.{name}"
        node_type = node.get("type")
        var_type = node.get("varType")
        if node_type == "uiVariable" and var_type in NUMERIC_VAR_TYPES:
            # ui_state holds only the tag *reference*; resolve it to the
            # tag_values location that actually carries the value history.
            path = parse_tag_ref(node.get("currentValue"), context_app_key)
            if path is not None:
                # The header is the variable's human displayString (what the
                # operator sees in the widget); fall back to its key if unset.
                display = node.get("displayString")
                label = (
                    display.strip()
                    if isinstance(display, str) and display.strip()
                    else name
                )
                # Units (if any) sit alongside displayString in ui_state; the
                # header appends them via column_header. Absent -> "".
                units_raw = node.get("units")
                units = (
                    units_raw.strip()
                    if isinstance(units_raw, str) and units_raw.strip()
                    else ""
                )
                out.append(
                    VariableRef(column=column, label=label, path=path, units=units)
                )
        # Recurse into submodules / containers regardless of this node's type;
        # app() still resolves to the owning application, so context is stable.
        grandchildren = node.get("children")
        if isinstance(grandchildren, dict) and grandchildren:
            _walk_children(grandchildren, column, context_app_key, out)


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
            context_app_key=app_key,
            out=out,
        )

    # Stable ordering by column name for deterministic CSV headers.
    out.sort(key=lambda r: r.column)
    return out


def get_by_keys(data: dict, keys: tuple[str, ...]):
    """Navigate a sequence of keys through nested dicts. None if absent."""
    node = data
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def is_numeric(value) -> bool:
    """True for int/float (excluding bool) values usable as report data."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def extract_row_values(
    message_data: dict, var_refs: list[VariableRef]
) -> dict[str, float]:
    """Extract each variable's numeric value from one tag_values message.

    ``message_data`` is a tag_values message payload (``{app_key: {tag:
    value}}``). tag_values messages are per-change diffs, so a message
    typically carries only the tags that moved — variables absent from this
    message are simply left out of the row (their cell renders blank). Only
    genuinely-numeric values are kept.
    """
    values: dict[str, float] = {}
    for ref in var_refs:
        raw = get_by_keys(message_data, ref.path)
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


def _format_number(value) -> str:
    """Render a numeric cell rounded to 2 decimal places; blank for non-numbers.

    Applied to every data cell and volume-summary value so the CSV never shows
    raw float noise (e.g. ``180.42295585648148`` -> ``180.42``). Non-numeric
    values (a missing cell, a blank grand total) render as an empty string.
    """
    if is_numeric(value):
        return f"{float(value):.2f}"
    return ""


def column_header(ref: VariableRef) -> str:
    """CSV header for a variable: its label, plus ``(units)`` when it has units.

    A variable whose ui_state node carries a non-empty ``units`` attribute
    renders as ``label (units)`` (e.g. ``Tank Volume (L)``); one without units
    renders as the bare label — 4-20mA flow/pressure columns already bake their
    unit into ``displayString``, so they stay unchanged.
    """
    return f"{ref.label} ({ref.units})" if ref.units else ref.label


def render_csv(
    var_refs: list[VariableRef],
    rows: list[dict],
    segment_label: str = "Segment",
    summary: list[tuple[str, object]] | None = None,
) -> bytes:
    """Render report rows to CSV bytes with the stdlib csv module.

    When ``summary`` is given (a list of ``(label, value)`` rows, e.g. the
    report-period volume totals), it is written first as a two-column block followed
    by a blank separator row, then the time-series table.

    Time-series headers are the labels the operator reads in the widget, not
    machine ids: ``Timestamp (UTC),<segment_label>,<var label>,...``, where each
    data-column header is a variable's ``VariableRef.label`` (its ui
    displayString), suffixed with ``(units)`` when it carries units (see
    column_header), and ``segment_label`` is the app's configured Segments Label.
    Column *order* and value matching still key off ``VariableRef.column``
    internally, so duplicate display names stay data-correct (only the header
    repeats).

    Each row dict is ``{"timestamp_utc": str, "segment_kind": str,
    "values": {column: number}}``. Rows are emitted in ascending timestamp
    order; missing cells render blank.
    """
    columns = [ref.column for ref in var_refs]
    header = [
        "Timestamp (UTC)",
        segment_label,
        *(column_header(ref) for ref in var_refs),
    ]

    ordered = sorted(rows, key=lambda r: r["timestamp_utc"])

    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    if summary:
        for label, value in summary:
            writer.writerow([label, _format_number(value)])
        writer.writerow([])  # blank row separating the summary from the table
    writer.writerow(header)
    for row in ordered:
        values = row.get("values", {})
        line = [row["timestamp_utc"], row["segment_kind"]]
        for col in columns:
            line.append(_format_number(values.get(col)))
        writer.writerow(line)

    return buf.getvalue().encode("utf-8")


def _parse_json_object(raw) -> dict:
    """``json.loads`` ``raw`` iff it yields a dict, else ``{}`` (junk-tolerant)."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def discover_volume_totals(
    tag_values_data: dict,
) -> tuple[float | None, dict[str, float]]:
    """Grand + per-kind volume totals discovered in a ``tag_values`` aggregate.

    Convention (see VOLUME_TOTAL_KEY / SEGMENT_TOTALS_KEY): an upstream app
    publishes a running ``total_volume`` (the grand total) and a
    ``segment_totals_json`` object mapping segment kind -> its cumulative
    volume. Every app block carrying ``segment_totals_json`` contributes; values
    sum across apps when more than one qualifies (e.g. multiple skids on a
    device). Returns ``(grand_or_None, {kind: volume})``; non-numeric/absent
    values are skipped, and grand is None when no block carries a numeric
    ``total_volume``.
    """
    grand: float | None = None
    per_kind: dict[str, float] = {}
    if not isinstance(tag_values_data, dict):
        return grand, per_kind
    for block in tag_values_data.values():
        if not isinstance(block, dict) or SEGMENT_TOTALS_KEY not in block:
            continue
        total = block.get(VOLUME_TOTAL_KEY)
        if is_numeric(total):
            grand = total if grand is None else grand + total
        for kind, vol in _parse_json_object(block.get(SEGMENT_TOTALS_KEY)).items():
            if is_numeric(vol):
                per_kind[kind] = per_kind.get(kind, 0.0) + vol
    return grand, per_kind


def totaliser_app_keys(tag_values_data: dict) -> list[str]:
    """App keys in a ``tag_values`` aggregate that publish the volume-totals
    convention (a ``segment_totals_json`` block; see discover_volume_totals).

    Sorted for deterministic iteration. These are the apps whose per-period
    volume the report sums from endpoint snapshots (see period_volume_totals).
    """
    if not isinstance(tag_values_data, dict):
        return []
    keys = [
        key
        for key, block in tag_values_data.items()
        if isinstance(block, dict) and SEGMENT_TOTALS_KEY in block
    ]
    keys.sort()
    return keys


def totals_snapshot_from_block(block) -> tuple[float | None, dict[str, float]]:
    """Grand + per-kind volume totals from ONE app's ``tag_values`` block.

    A single-app version of discover_volume_totals used to build endpoint
    snapshots (the last logged values at/before a report boundary): reads the
    numeric ``total_volume`` (the grand, None when absent/non-numeric) and the
    ``segment_totals_json`` object mapping kind -> cumulative volume. Only
    numeric per-kind values are kept.
    """
    grand: float | None = None
    per_kind: dict[str, float] = {}
    if not isinstance(block, dict):
        return grand, per_kind
    total = block.get(VOLUME_TOTAL_KEY)
    if is_numeric(total):
        grand = total
    for kind, vol in _parse_json_object(block.get(SEGMENT_TOTALS_KEY)).items():
        if is_numeric(vol):
            per_kind[kind] = vol
    return grand, per_kind


def period_volume_totals(
    baseline: tuple[float | None, dict[str, float]],
    end: tuple[float | None, dict[str, float]],
) -> tuple[float | None, dict[str, float]]:
    """One totaliser app's volume over the report period, from two snapshots.

    ``baseline`` (B, at/before start_ts) and ``end`` (E, at/before end_ts) are
    each ``(grand, per_kind)`` snapshots (see totals_snapshot_from_block). The
    period figure is the endpoint difference E - B:

    - grand: ``E - B`` (missing B treated as 0); when ``E < B`` the odometer was
      reset, so the drop is a restart-from-0 and the period is ``E`` alone.
      None when E carries no grand total.
    - per kind: ``E_k - B_k`` (missing ``B_k`` treated as 0), clamped at ``0.0``
      so a retroactive repaint that re-attributed volume away from a kind never
      reports negative.
    """
    base_grand, base_kind = baseline
    end_grand, end_kind = end
    if end_grand is None:
        grand: float | None = None
    else:
        base = base_grand if base_grand is not None else 0.0
        grand = end_grand - base if end_grand >= base else end_grand
    per_kind: dict[str, float] = {}
    for kind, e_val in end_kind.items():
        per_kind[kind] = max(0.0, e_val - base_kind.get(kind, 0.0))
    return grand, per_kind


def merge_baseline_snapshot(
    primary: tuple[float | None, dict[str, float]],
    fallback: tuple[float | None, dict[str, float]],
) -> tuple[float | None, dict[str, float]]:
    """Fill a partial baseline snapshot's missing keys from ``fallback``.

    A baseline snapshot's two keys are searched independently (``total_volume``
    logs only per N volume units; ``segment_totals_json`` republishes on a
    ~900 s timer), so a pre-window lookback on an idle device can find one key
    but not the other. Each key missing from ``primary`` — a ``None`` grand or
    an empty per-kind map — is taken from ``fallback`` (the earliest in-window
    sample) so period_volume_totals diffs against a real baseline instead of 0,
    which would otherwise report the odometer's lifetime value. A key already
    present in ``primary`` is kept as-is. This applies the spec's per-key
    "missing-baseline -> earliest in-window sample else 0" rule.
    """
    primary_grand, primary_kind = primary
    fb_grand, fb_kind = fallback
    grand = primary_grand if primary_grand is not None else fb_grand
    per_kind = primary_kind if primary_kind else fb_kind
    return grand, per_kind


def build_volume_summary(
    grand, per_kind: dict, kinds: list[str]
) -> list[tuple[str, object]]:
    """Summary rows ``(label, value)`` for the report-period volume block.

    One row for the grand total, then one per ``kind`` in order, each reading
    ``per_kind`` and rendering ``0.0`` when a kind has accrued no volume yet. A
    non-numeric/absent grand total renders blank. ``kinds`` is the caller's
    ordered kind list (configured kinds + "None"), so the breakdown lists every
    pipeline regardless of whether it has data yet.
    """
    totals = per_kind if isinstance(per_kind, dict) else {}
    rows: list[tuple[str, object]] = [
        ("Grand Total Volume (report period)", grand if is_numeric(grand) else "")
    ]
    for kind in kinds:
        vol = totals.get(kind)
        rows.append((f"{kind} (report period)", vol if is_numeric(vol) else 0.0))
    return rows


def find_total_volume_ref(var_refs: list[VariableRef]) -> VariableRef | None:
    """The discovered variable for the grand running totaliser, or None.

    That is the numeric variable whose tag key is ``total_volume`` — the grand
    cumulative across all pipelines. In a per-pipeline report its column is
    swapped for a pipeline-scoped running total (see pipeline_total_value), but
    only when the source app also publishes ``segment_totals_json``; otherwise
    the grand-total column is left as the caller found it.
    """
    for ref in var_refs:
        if ref.path and ref.path[-1] == VOLUME_TOTAL_KEY:
            return ref
    return None


def pipeline_total_value(message_data: dict, app_key: str, kind: str):
    """This message's cumulative volume for ``kind``, from segment_totals_json.

    Reads ``message_data[app_key][segment_totals_json]`` — the per-kind
    cumulative the totaliser publishes alongside ``total_volume`` — and returns
    the value for ``kind`` (0.0 when the kind has accrued nothing yet), or None
    when this (diff) message doesn't carry ``segment_totals_json`` so the cell
    stays blank, exactly as the grand-total cell did on such messages.
    """
    if not isinstance(message_data, dict):
        return None
    block = message_data.get(app_key)
    if not isinstance(block, dict) or SEGMENT_TOTALS_KEY not in block:
        return None
    value = _parse_json_object(block.get(SEGMENT_TOTALS_KEY)).get(kind)
    return value if is_numeric(value) else 0.0


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
