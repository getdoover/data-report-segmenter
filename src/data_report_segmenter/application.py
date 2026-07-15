import logging
from datetime import datetime, timezone

from pydoover.processor import Application
from pydoover.models import (
    AggregateUpdateEvent,
    DeploymentEvent,
    File,
    MessageCreateEvent,
)
from pydoover.rpc import handler, RPCError
from pydoover.tags import Tags

from . import report as report_lib
from . import segments as seg
from .app_config import DataReportSegmenterConfig
from .app_ui import DataReportSegmenterUI

log = logging.getLogger(__name__)

# Channels (created on first write; see data-plane.md §1).
TAG_VALUES_CHANNEL = "tag_values"
UI_STATE_CHANNEL = "ui_state"
REPORTS_CHANNEL = "segment_reports"

# Key of the open-segment pointer in the tag_values aggregate, stored under
# this app_key. We read/write it via the data client directly rather than the
# tag manager: pydoover 1.9.1's tag-commit path passes return_aggregate= to
# ProcessorDataClient.update_channel_aggregate, which does not accept it
# (TypeError). See _read_current_segment / _write_current_segment.
CURRENT_SEGMENT_TAG = "current_segment"

APP_NAME = "data_report_segmenter"

# History-fetch page size (REST list route caps this at 1500).
_PAGE_LIMIT = 1500

# Forward scan for the boundary-crossing segment record: first chunk size and
# per-iteration growth factor (1 h, then 4 h, 16 h, ... until "now").
_CROSS_SCAN_INITIAL_MS = 60 * 60 * 1000
_CROSS_SCAN_GROWTH = 4


class DataReportSegmenterApp(Application):
    """Processor: the single authoritative writer of segment state.

    - Open segment lives in the tag_values aggregate under this app_key.
    - Closed segments are append-only, backdated messages on tag_values with
      a ``record_type: "segment"`` discriminator.
    - Reports are CSVs attached to a job message on the segment_reports
      channel, whose status the widget watches (RPC response is best-effort).
    """

    config_cls = DataReportSegmenterConfig
    tags_cls = Tags
    ui_cls = DataReportSegmenterUI

    # -- lifecycle -----------------------------------------------------------

    async def setup(self):
        # setup() runs before RPC dispatch and every on_* handler, so seeding
        # here covers on_deployment *and* opportunistically covers every other
        # event (on_deployment has historically been unreliable - see
        # pro-app-anatomy §8 "idempotent init").
        await self._ensure_open_segment()

    async def on_deployment(self, event: DeploymentEvent):
        # Explicit belt-and-suspenders seeding on deploy (also done in setup()).
        await self._ensure_open_segment()

    async def on_message_create(self, event: MessageCreateEvent):
        # Opportunistic re-seed; the RPC managers have already dispatched any
        # switch_segment / generate_report handler for this same event.
        await self._ensure_open_segment()

    async def on_aggregate_update(self, event: AggregateUpdateEvent):
        # deployment_config aggregate updates are the fallback path DRA used
        # when on_deployment did not fire - re-seed opportunistically.
        await self._ensure_open_segment()

    # -- config helpers ------------------------------------------------------

    def _segment_kinds(self) -> list[str]:
        return [e.value for e in self.config.segment_kinds.elements]

    def _valid_kinds(self) -> set[str]:
        return seg.valid_kinds(self._segment_kinds())

    # -- open-segment state --------------------------------------------------

    async def _current_segment(self) -> dict | None:
        """Read the open segment straight from the tag_values aggregate.

        Deliberately NOT via the tag manager: pydoover 1.9.1's tag-commit path
        passes ``return_aggregate=`` to ``ProcessorDataClient`` (which rejects
        it), so we read and write ``current_segment`` directly. A missing key
        means it has genuinely never been seeded -> caller seeds "None".
        """
        aggregate = await self.api.fetch_channel_aggregate(TAG_VALUES_CHANNEL)
        block = (aggregate.data or {}).get(self.app_key) or {}
        value = block.get(CURRENT_SEGMENT_TAG)
        return value if isinstance(value, dict) else None

    async def _write_current_segment(self, segment: dict) -> None:
        """PATCH-merge the open-segment pointer into ``tag_values.<app_key>``.

        Replaces ``set_tag``: the tag manager's commit path is unusable on a
        processor in pydoover 1.9.1 (return_aggregate= TypeError). A bare
        aggregate PATCH under our app_key keeps the exact same on-the-wire
        shape the widget reads (``tag_values[app_key].current_segment``).
        """
        await self.api.update_channel_aggregate(
            TAG_VALUES_CHANNEL, {self.app_key: {CURRENT_SEGMENT_TAG: segment}}
        )

    async def _ensure_open_segment(self) -> dict:
        """Idempotently seed a "None" open segment if none exists yet."""
        current = await self._current_segment()
        if current is not None:
            return current
        now_ts = _now_ms()
        seeded = seg.make_open_segment(
            seg.default_open_kind(self._segment_kinds()), now_ts
        )
        await self._write_current_segment(seeded)
        log.info("Seeded open segment: %s", seeded)
        return seeded

    # -- RPC: switch_segment -------------------------------------------------

    @handler("switch_segment")
    async def switch_segment(self, ctx, params):
        kind = params.get("kind")
        client_ts = params.get("client_ts")

        if not isinstance(kind, str) or kind not in self._valid_kinds():
            raise RPCError(
                "INVALID_KIND",
                f"kind {kind!r} is not one of {sorted(self._valid_kinds())}",
            )

        current = await self._ensure_open_segment()

        # Switch-to-same-kind is an idempotent no-op (still success).
        if kind == current["kind"]:
            return {"current_segment": current}

        now_ts = _now_ms()
        switch_ts = seg.clamp_switch_instant(client_ts, current["start_ts"], now_ts)

        # Close the current segment: append-only message backdated to the
        # switch instant (timestamp == segment end).
        closed = seg.close_segment(current, switch_ts)
        author_id = getattr(ctx.message, "author_id", None)
        if author_id is not None:
            closed["author_id"] = author_id
        # NB two int-time conventions that look identical at call sites:
        # create_message(timestamp=) takes an epoch-MS int (the API sends it
        # as `ts`), whereas list_messages(before=/after=) treats an int as a
        # SNOWFLAKE message ID - time bounds there must be datetimes.
        await self.api.create_message(TAG_VALUES_CHANNEL, closed, timestamp=switch_ts)

        # Open the new segment (aggregate pointer).
        new_segment = seg.make_open_segment(kind, switch_ts)
        await self._write_current_segment(new_segment)

        log.info("Switched segment %s -> %s at %s", current["kind"], kind, switch_ts)
        return {"current_segment": new_segment}

    # -- RPC: generate_report ------------------------------------------------

    @handler("generate_report")
    async def generate_report(self, ctx, params):
        kind = params.get("kind")
        start_ts = params.get("start_ts")
        end_ts = params.get("end_ts")

        if not isinstance(kind, str) or kind not in self._valid_kinds():
            raise RPCError(
                "INVALID_KIND",
                f"kind {kind!r} is not one of {sorted(self._valid_kinds())}",
            )
        if not isinstance(start_ts, int) or not isinstance(end_ts, int):
            raise RPCError("INVALID_RANGE", "start_ts and end_ts must be epoch-ms ints")
        if start_ts >= end_ts:
            raise RPCError("INVALID_RANGE", "start_ts must be before end_ts")

        # FIRST create the job message so the widget can watch it regardless of
        # whether the (30s) RPC response outlives the (300s) lambda.
        meta = {
            "record_type": "report",
            "status": "Generating",
            "kind": kind,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "requested_ts": _now_ms(),
        }
        author_id = getattr(ctx.message, "author_id", None)
        if author_id is not None:
            meta["author_id"] = author_id
        job = await self.api.create_message(REPORTS_CHANNEL, meta)
        job_id = job.id

        try:
            windows, rows, var_refs = await self._build_report(kind, start_ts, end_ts)
            csv_bytes = report_lib.render_csv(var_refs, rows)
            filename = report_lib.build_report_filename(
                APP_NAME, kind, start_ts, end_ts
            )
            csv_file = File(
                filename=filename,
                content_type="text/csv",
                size=len(csv_bytes),
                data=csv_bytes,
            )
            meta.update(
                {"status": "Complete", "windows": len(windows), "rows": len(rows)}
            )
            await self.api.update_message(
                REPORTS_CHANNEL, job_id, meta, files=[csv_file]
            )
            log.info(
                "Report %s complete: %d windows, %d rows",
                job_id,
                len(windows),
                len(rows),
            )
        except Exception as e:  # noqa: BLE001 - report failure to the job message
            log.error("Report %s failed: %s", job_id, e, exc_info=e)
            meta.update({"status": "Failed", "error": str(e)})
            try:
                await self.api.update_message(REPORTS_CHANNEL, job_id, meta)
            except Exception as e2:  # noqa: BLE001
                log.error("Failed to mark report %s as Failed: %s", job_id, e2)

        # Best-effort pointer; the widget relies on the channel watch.
        return {"message_id": job_id, "channel": REPORTS_CHANNEL}

    # -- report engine (impure orchestration around pure report_lib) --------

    async def _build_report(self, kind, start_ts, end_ts):
        current = await self._current_segment()
        closed_segments = await self._fetch_closed_segments(start_ts, end_ts)
        windows = seg.compute_windows(closed_segments, current, kind, start_ts, end_ts)

        # ui_state tells us WHICH numeric variables to report; each carries a
        # $tag reference that walk_numeric_variables resolves to the
        # tag_values location holding the actual value history.
        ui_state = await self.api.fetch_channel_aggregate(UI_STATE_CHANNEL)
        var_refs = report_lib.walk_numeric_variables(ui_state.data or {}, self.app_key)
        # tag_values messages are keyed by app_key at the top level; restrict
        # history reads to the app_keys our variables actually live under.
        source_app_keys = sorted({ref.path[0] for ref in var_refs if ref.path})

        rows: list[dict] = []
        for win_start, win_end in windows:
            rows.extend(
                await self._collect_window_rows(
                    win_start, win_end, kind, var_refs, source_app_keys
                )
            )
        return windows, rows, var_refs

    async def _fetch_closed_segments(self, start_ts, end_ts) -> list[dict]:
        """All closed-segment records overlapping [start_ts, end_ts].

        Closed-segment messages are timestamped at their END, so:

        - LOW boundary is safe as-is: a segment crossing ``start_ts`` was
          closed *inside* the range, so its message timestamp falls within
          (start_ts, end_ts] and the backward page below fetches it
          (compute_windows clamps its start to the range).
        - HIGH boundary is NOT: a segment that starts inside the range but is
          closed after ``end_ts`` has its message timestamp beyond
          ``before=end_ts``. A bounded forward scan past ``end_ts`` finds the
          first segment record there; segment contiguity means only that
          first record can cross the boundary
          (see segments.select_boundary_crossing_segment).
        """
        segments = await self._page_segment_records(start_ts, end_ts)
        crossing = await self._find_boundary_crossing_segment(end_ts)
        if crossing is not None:
            segments.append(crossing)
        return segments

    async def _find_boundary_crossing_segment(self, end_ts) -> dict | None:
        """The segment record straddling ``end_ts``, if any.

        Forward-scans (end_ts, now] in growing chunks until a chunk contains
        a segment record; the earliest record found is the only possible
        boundary-crosser (contiguity), kept iff it started before ``end_ts``.
        pydoover's list_messages has no ascending-order option, so each chunk
        is paged with the same backward-paging helper.
        """
        now_ts = _now_ms()
        cursor = end_ts
        chunk = _CROSS_SCAN_INITIAL_MS
        while cursor < now_ts:
            upper = min(cursor + chunk, now_ts)
            candidates = await self._page_segment_records(cursor, upper)
            if candidates:
                return seg.select_boundary_crossing_segment(candidates, end_ts)
            cursor = upper
            chunk *= _CROSS_SCAN_GROWTH
        return None

    async def _page_segment_records(self, after_ts: int, before_ts: int) -> list[dict]:
        """All ``record_type == "segment"`` messages in (after_ts, before_ts].

        ``after_ts``/``before_ts`` are epoch-ms ints; they are converted to
        aware datetimes for ``list_messages`` because its ``before``/``after``
        treat ints as snowflake message IDs (see report.ms_to_datetime).
        Subsequent-page cursors ARE genuine int snowflake IDs and stay ints.
        """
        after_dt = report_lib.ms_to_datetime(after_ts)
        segments: list[dict] = []
        seen: set[int] = set()
        # First page bounded by time (datetime); later pages by int snowflake.
        before_bound: datetime | int = report_lib.ms_to_datetime(before_ts)
        cursor_id: int | None = None
        while True:
            msgs = await self.api.list_messages(
                TAG_VALUES_CHANNEL,
                before=before_bound,
                after=after_dt,
                limit=_PAGE_LIMIT,
                field_names=["record_type", "kind", "start_ts", "end_ts"],
            )
            if not msgs:
                break
            for m in msgs:
                if m.id in seen:
                    continue
                seen.add(m.id)
                data = m.data or {}
                if data.get("record_type") == "segment":
                    segments.append(data)
            cursor_id = report_lib.next_page_cursor(
                [m.id for m in msgs], cursor_id, _PAGE_LIMIT
            )
            if cursor_id is None:
                break
            before_bound = cursor_id
        return segments

    async def _collect_window_rows(
        self, win_start: int, win_end: int, kind, var_refs, field_names
    ) -> list[dict]:
        """tag_values value rows in the window (win_start, win_end], epoch-ms.

        Reads the tag_values value history the ui_state variables reference.
        Same time-vs-snowflake convention as _page_segment_records: window
        bounds are epoch-ms ints converted to datetimes for ``list_messages``;
        subsequent-page cursors are int snowflake IDs. Messages that carry
        none of our variables (segment records, unrelated apps' tags) yield no
        row.
        """
        after_dt = report_lib.ms_to_datetime(win_start)
        rows_by_id: dict[int, dict] = {}
        # First page bounded by time (datetime); later pages by int snowflake.
        before_bound: datetime | int = report_lib.ms_to_datetime(win_end)
        cursor_id: int | None = None
        while True:
            msgs = await self.api.list_messages(
                TAG_VALUES_CHANNEL,
                before=before_bound,
                after=after_dt,
                limit=_PAGE_LIMIT,
                field_names=field_names,
            )
            if not msgs:
                break
            for m in msgs:
                if m.id in rows_by_id:
                    continue
                values = report_lib.extract_row_values(m.data or {}, var_refs)
                if not values:
                    continue  # diff message with none of our tags -> no row
                rows_by_id[m.id] = {
                    "timestamp_utc": report_lib.format_timestamp_utc(_snowflake_ms(m)),
                    "segment_kind": kind,
                    "values": values,
                }
            cursor_id = report_lib.next_page_cursor(
                [m.id for m in msgs], cursor_id, _PAGE_LIMIT
            )
            if cursor_id is None:
                break
            before_bound = cursor_id
        return list(rows_by_id.values())


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _snowflake_ms(message) -> int:
    """Epoch-ms of a message from its snowflake-derived timestamp."""
    return int(message.timestamp.timestamp() * 1000)
