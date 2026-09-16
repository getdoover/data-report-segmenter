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
# per-pipeline report: a running total scoped to the report's own kind AND to
# the report period, read from segment_totals_json and re-based against the
# pre-window baseline (see find_total_volume_ref / pipeline_total_value /
# pipeline_period_value).
PIPELINE_TOTAL_COL = "__pipeline_total__"
PIPELINE_TOTAL_LABEL = "Total Injected Volume"

# Joins a variable's ancestor displayStrings to its own in the CSV header.
LABEL_SEPARATOR = " - "

# ui_state subtrees (by node key) never reported on: apps group device-health
# readouts (e.g. HMI Engine's display "Restarts" counter) under a
# "diagnostics" submodule, which is noise in a customer process report.
EXCLUDED_SUBTREE_KEYS = frozenset({"diagnostics"})


class VariableRef(NamedTuple):
    """A NumericVariable discovered in ui_state, resolved to its tag source.

    - ``column`` is the internal, unique key for this variable
      (``<app_key>.<var...>``): it keys the extracted value map and fixes the
      CSV column *order*, but is never shown to the user.
    - ``label`` is the human CSV header — the variable's ui ``displayString``
      (falling back to its own key when it carries none), qualified by the
      displayStrings of the app and any submodules it sits under, joined with
      LABEL_SEPARATOR (e.g. ``Flow Sensor - AI Value``). That is the card
      title + row the operator reads in the widget; without the qualifier two
      4-20mA apps both render as a bare ``AI Value``. Ancestors with a blank
      displayString contribute nothing.
    - ``path`` is the key path into a ``tag_values`` message/aggregate where
      the value actually lives, e.g. ``("4_20ma_sensor_1", "value")``.
      ui_state carries only the *reference* ($tag...) to this location, never
      the value history — so the report reads history from tag_values here.
    - ``units`` is the variable's ui ``units`` attribute (e.g. ``"%"``, ``"m"``,
      ``"L"``) after clean_units has stripped whitespace and any enclosing
      parentheses, appended to the CSV header as ``label (units)`` when
      non-empty (see column_header). Empty ``""`` when the node carries no
      units — 4-20mA columns bake their unit into ``displayString`` instead, so
      they render unchanged.
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


def clean_units(raw) -> str:
    """Normalise a ui_state ``units`` attribute to a bare unit token.

    Apps publish units inconsistently: a plain ``"%"``, a padded ``" (GPH)"``
    (leading space, already wrapped in parentheses), or ``"(mm)"``. Since
    column_header renders ``label (units)``, an already-wrapped value would
    render as ``AI Value ((GPH))``. This strips surrounding whitespace, ONE
    enclosing pair of parentheses, then any whitespace left inside them.
    Non-string or blank input yields ``""`` (no units).
    """
    if not isinstance(raw, str):
        return ""
    units = raw.strip()
    if len(units) >= 2 and units.startswith("(") and units.endswith(")"):
        units = units[1:-1]
    return units.strip()


def _display_string(node: dict) -> str:
    """A ui_state node's stripped ``displayString``, or ``""`` when absent/blank."""
    display = node.get("displayString")
    return display.strip() if isinstance(display, str) else ""


def _walk_children(
    children: dict,
    column_prefix: str,
    context_app_key: str,
    out: list[VariableRef],
    label_prefix: tuple[str, ...] = (),
) -> None:
    for name, node in children.items():
        if not isinstance(node, dict) or name in EXCLUDED_SUBTREE_KEYS:
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
                # operator sees in the widget; its key if unset), qualified by
                # the app/submodule it sits under — a bare "AI Value" can't say
                # whether it is the flow or the pressure sensor.
                label = LABEL_SEPARATOR.join(
                    (*label_prefix, _display_string(node) or name)
                )
                # Units (if any) sit alongside displayString in ui_state; the
                # header appends them via column_header. Normalised by
                # clean_units (apps publish " (GPH)" as readily as "GPH");
                # absent/blank -> "".
                units = clean_units(node.get("units"))
                out.append(
                    VariableRef(column=column, label=label, path=path, units=units)
                )
        # Recurse into submodules / containers regardless of this node's type;
        # app() still resolves to the owning application, so context is stable.
        grandchildren = node.get("children")
        if isinstance(grandchildren, dict) and grandchildren:
            display = _display_string(node)
            _walk_children(
                grandchildren,
                column,
                context_app_key,
                out,
                (*label_prefix, display) if display else label_prefix,
            )


def walk_numeric_variables(
    ui_state_aggregate: dict, own_app_key: str
) -> list[VariableRef]:
    """All NumericVariables in the ui_state aggregate, excluding our own subtree.

    Walks ``state.children.<app_key>.children.*`` recursively (into
    submodules) and collects nodes with ``type == "uiVariable"`` and
    ``varType in ("float", "integer")``. The app's own ``own_app_key``
    subtree is skipped so the report never reports on itself, as is any
    ``diagnostics`` submodule (see EXCLUDED_SUBTREE_KEYS).
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
        app_display = _display_string(app_node)
        _walk_children(
            children,
            column_prefix=app_key,
            context_app_key=app_key,
            out=out,
            label_prefix=(app_display,) if app_display else (),
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
    unit into ``displayString``, so they stay unchanged. A label that ALREADY
    ends with ``(units)`` is left alone rather than suffixed twice: apps that
    bake the unit into ``displayString`` and *also* publish it as ``units``
    would otherwise render ``AI Value (GPH) (GPH)``.
    """
    if not ref.units:
        return ref.label
    if ref.label.endswith(f"({ref.units})"):
        return ref.label
    return f"{ref.label} ({ref.units})"


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
    displayString, qualified by its app/submodule displayStrings), suffixed with ``(units)`` when it carries units (see
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

    The value is the on-device odometer's LIFETIME cumulative for the kind; the
    report re-bases it against the period baseline via pipeline_period_value
    before it reaches a cell.
    """
    if not isinstance(message_data, dict):
        return None
    block = message_data.get(app_key)
    if not isinstance(block, dict) or SEGMENT_TOTALS_KEY not in block:
        return None
    value = _parse_json_object(block.get(SEGMENT_TOTALS_KEY)).get(kind)
    return value if is_numeric(value) else 0.0


def pipeline_period_value(cumulative, baseline) -> float:
    """One cell of the running pipeline total, scoped to the report period.

    ``cumulative`` is a message's LIFETIME per-kind total (pipeline_total_value)
    and ``baseline`` is the same kind's value in the report's baseline snapshot
    (the last logged totals at/before start_ts, ``0.0`` when the kind is absent
    from it). The cell is ``cumulative - baseline``, clamped at ``0.0``.

    Re-basing is what puts the column on the summary's scale: both are
    ``E_k - B_k`` against the same baseline. Without it a column ending at the
    odometer's lifetime figure sits above a summary quoting the period figure
    and the report reads as wrong.

    The last row *equals* the ``<kind> (report period)`` summary value whenever
    a single app publishes the totaliser convention. A window still open at
    end_ts ends on the same message the summary's ``E_k`` came from; a window
    that closed earlier gets a synthetic closing row carrying the frozen total
    the totaliser republished after the switch (application._closing_row), which
    is capped at ``E_k - B_k`` so it can never exceed the summary. A real
    in-window cell is message-exact and is NOT capped: on a non-monotone series
    (odometer reset, retroactive repaint) a sample can read above the final
    summary figure, that being what the device published at the time. With more
    than one totaliser app the summary sums them all while the column tracks
    one, and the column is a subset.

    The clamp covers an odometer reset (or a retroactive repaint away from this
    kind) mid-period, matching period_volume_totals' per-kind clamp.
    """
    return max(0.0, float(cumulative) - float(baseline))


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
