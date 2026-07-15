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

# Key of the open-segment pointer in the tag_values aggregate (namespaced
# under this app_key automatically by set_tag).
CURRENT_SEGMENT_TAG = "current_segment"

APP_NAME = "data_report_segmenter"

# History-fetch page size (REST list route caps this at 1500).
_PAGE_LIMIT = 1500


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

    def _current_segment(self) -> dict | None:
        """Read the open segment, distinguishing genuinely-absent from default.

        ``current_segment`` is stored as a plain aggregate value (no typed-tag
        default), so a KeyError here means it has never been seeded.
        """
        try:
            value = self.tag_manager.get_tag(CURRENT_SEGMENT_TAG, raise_key_error=True)
        except KeyError:
            return None
        if not isinstance(value, dict):
            return None
        return value

    async def _ensure_open_segment(self) -> dict:
        """Idempotently seed a "None" open segment if none exists yet."""
        current = self._current_segment()
        if current is not None:
            return current
        now_ts = _now_ms()
        seeded = seg.make_open_segment(
            seg.default_open_kind(self._segment_kinds()), now_ts
        )
        await self.set_tag(CURRENT_SEGMENT_TAG, seeded)
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
        await self.api.create_message(TAG_VALUES_CHANNEL, closed, timestamp=switch_ts)

        # Open the new segment (aggregate pointer).
        new_segment = seg.make_open_segment(kind, switch_ts)
        await self.set_tag(CURRENT_SEGMENT_TAG, new_segment)

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
        current = self._current_segment()
        closed_segments = await self._fetch_closed_segments(start_ts, end_ts)
        windows = seg.compute_windows(closed_segments, current, kind, start_ts, end_ts)

        ui_state = await self.api.fetch_channel_aggregate(UI_STATE_CHANNEL)
        var_refs = report_lib.walk_numeric_variables(ui_state.data or {}, self.app_key)
        field_names = [ref.field_path for ref in var_refs]

        rows: list[dict] = []
        for win_start, win_end in windows:
            rows.extend(
                await self._collect_window_rows(
                    win_start, win_end, kind, var_refs, field_names
                )
            )
        return windows, rows, var_refs

    async def _fetch_closed_segments(self, start_ts, end_ts) -> list[dict]:
        """All closed-segment records overlapping [start_ts, end_ts].

        Closed segments are stored with ``timestamp == end_ts``; a segment can
        start before ``start_ts`` yet still overlap, so we page from the range
        start (a little conservatism at the low end is harmless because
        compute_windows clamps).
        """
        segments: list[dict] = []
        seen: set[int] = set()
        before_cursor: int | None = end_ts
        while True:
            msgs = await self.api.list_messages(
                TAG_VALUES_CHANNEL,
                before=before_cursor,
                after=start_ts,
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
            oldest = min(m.id for m in msgs)
            if oldest == before_cursor or len(msgs) < _PAGE_LIMIT:
                break
            before_cursor = oldest
        return segments

    async def _collect_window_rows(
        self, win_start, win_end, kind, var_refs, field_names
    ) -> list[dict]:
        rows_by_id: dict[int, dict] = {}
        before_cursor: int | None = win_end
        while True:
            msgs = await self.api.list_messages(
                UI_STATE_CHANNEL,
                before=before_cursor,
                after=win_start,
                limit=_PAGE_LIMIT,
                field_names=field_names,
            )
            if not msgs:
                break
            for m in msgs:
                if m.id in rows_by_id:
                    continue
                values = report_lib.extract_row_values(m.data or {}, var_refs)
                rows_by_id[m.id] = {
                    "timestamp_utc": report_lib.format_timestamp_utc(_snowflake_ms(m)),
                    "segment_kind": kind,
                    "values": values,
                }
            oldest = min(m.id for m in msgs)
            if oldest == before_cursor or len(msgs) < _PAGE_LIMIT:
                break
            before_cursor = oldest
        return list(rows_by_id.values())


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _snowflake_ms(message) -> int:
    """Epoch-ms of a message from its snowflake-derived timestamp."""
    return int(message.timestamp.timestamp() * 1000)
