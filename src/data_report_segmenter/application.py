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
# Dedicated notification channel: one message per segment change (switch or
# retroactive add). Other apps subscribe HERE (not tag_values, which every app
# writes constantly) to learn when the segment timeline changed and re-derive.
# Created on deployment so subscribers exist before the first change.
DATA_SEGMENTS_CHANNEL = "data_segments"

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

# Endpoint-snapshot baseline lookback cap: how far before a report boundary to
# page tag_values for the last logged volume totals. Both keys log <=15 min
# apart (segment_totals_json every ~900 s; total_volume every 10 volume units),
# so the snapshot is almost always on page 1; the cap bounds paging on devices
# with sparse totaliser history instead of walking to the beginning of time.
_TOTALS_LOOKBACK_MS = 7 * 24 * 60 * 60 * 1000


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
        await self._ensure_data_segments_channel()

    async def _ensure_data_segments_channel(self) -> None:
        """Create the data_segments notification channel so subscribers can bind.

        Channels are otherwise created on first write; creating it on deploy
        means other apps can subscribe to segment-change notifications before
        the operator makes the first change. Idempotent — tolerate "exists".
        """
        try:
            await self.api.create_channel(DATA_SEGMENTS_CHANNEL)
            log.info("Ensured %s channel exists", DATA_SEGMENTS_CHANNEL)
        except Exception as e:  # noqa: BLE001 - already-exists or transient
            log.info("create_channel(%s): %s", DATA_SEGMENTS_CHANNEL, e)

    async def _notify_segment_change(
        self,
        change_type: str,
        kind: str,
        affected_start: int,
        affected_end: int,
        author_id=None,
    ) -> None:
        """Announce a segment-timeline change on the data_segments channel.

        One message per change so subscribed apps can re-derive whatever they
        maintain over the affected window. Best-effort: a failed notification
        must never fail the change itself.
        """
        payload = {
            "record_type": "segment_change",
            "change_type": change_type,  # "switch" | "retroactive_add"
            "kind": kind,
            "affected_start": int(affected_start),
            "affected_end": int(affected_end),
            "changed_at": _now_ms(),
            "app_key": self.app_key,
        }
        if author_id is not None:
            payload["author_id"] = author_id
        try:
            await self.api.create_message(DATA_SEGMENTS_CHANNEL, payload)
        except Exception as e:  # noqa: BLE001
            log.error("Failed to notify %s: %s", DATA_SEGMENTS_CHANNEL, e)

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

        # Tell other apps the timeline changed over [switch_ts, now].
        await self._notify_segment_change(
            "switch", kind, switch_ts, now_ts, author_id=author_id
        )

        log.info("Switched segment %s -> %s at %s", current["kind"], kind, switch_ts)
        return {"current_segment": new_segment}

    # -- RPC: add_segment (retroactive) --------------------------------------

    @handler("add_segment")
    async def add_segment(self, ctx, params):
        """Retroactively paint [start_ts, end_ts] as ``kind`` on the timeline.

        Overlap semantics (segments.paint_segment): same-kind overlaps extend /
        combine; other-kind segments fully covered are removed, partial ones
        truncated — every instant stays exactly one kind. Persisted as a minimal
        diff against the existing closed-segment messages + the open-segment
        aggregate, then announced on data_segments.
        """
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

        now_ts = _now_ms()
        end_ts = min(end_ts, now_ts)  # cannot paint the future
        if start_ts >= end_ts:
            raise RPCError("INVALID_RANGE", "range is entirely in the future")

        open_seg = await self._ensure_open_segment()

        # Fetch the closed segments that could be affected: everything ending
        # after (start_ts - 1) — i.e. the segment containing start_ts, its left
        # neighbour when start_ts is exactly on a boundary, and all segments
        # after it up to the open segment. Segments entirely before this window
        # are untouched. Closed segments all end < now (the open one covers now)
        # so no forward boundary-scan is needed here.
        closed_with_ids = await self._fetch_closed_with_ids(start_ts - 1, now_ts)

        # Build the effective timeline over the window (closed + open-as-end=now).
        window = sorted(
            (data for (_mid, data) in closed_with_ids),
            key=lambda d: int(d["start_ts"]),
        )
        window.append(
            {
                "kind": open_seg["kind"],
                "start_ts": int(open_seg["start_ts"]),
                "end_ts": now_ts,
            }
        )

        new_timeline = seg.paint_segment(window, start_ts, end_ts, kind, now_ts)

        # Diff & persist. Closed-segment messages are keyed by end_ts (their
        # message timestamp), which is unique in a contiguous timeline.
        new_closed = new_timeline[:-1]
        new_open = seg.make_open_segment(
            new_timeline[-1]["kind"], new_timeline[-1]["start_ts"]
        )

        old_by_end = {int(d["end_ts"]): (mid, d) for (mid, d) in closed_with_ids}
        new_by_end = {int(s["end_ts"]): s for s in new_closed}

        changed = False

        # Delete old closed-segment messages whose end vanished or whose
        # start/kind changed (delete-before-recreate avoids any reliance on
        # overwrite-by-timestamp).
        for end, (mid, old) in old_by_end.items():
            new = new_by_end.get(end)
            if new is None or _seg_differs(old, new):
                await self.api.delete_message(TAG_VALUES_CHANNEL, mid)
                changed = True

        # Create new / changed closed-segment records (backdated to their end).
        author_id = getattr(ctx.message, "author_id", None)
        for end, s in new_by_end.items():
            old = old_by_end.get(end)
            if old is not None and not _seg_differs(old[1], s):
                continue
            record = {
                "record_type": "segment",
                "kind": s["kind"],
                "start_ts": int(s["start_ts"]),
                "end_ts": int(end),
            }
            if author_id is not None:
                record["author_id"] = author_id
            await self.api.create_message(
                TAG_VALUES_CHANNEL, record, timestamp=int(end)
            )
            changed = True

        # Update the open-segment pointer if it moved.
        if new_open != {k: open_seg.get(k) for k in ("kind", "start_ts")}:
            await self._write_current_segment(new_open)
            changed = True

        if changed:
            await self._notify_segment_change(
                "retroactive_add", kind, start_ts, end_ts, author_id=author_id
            )

        log.info(
            "Retroactive add %s [%s, %s]: changed=%s", kind, start_ts, end_ts, changed
        )
        return {"current_segment": new_open, "changed": changed}

    async def _fetch_closed_with_ids(
        self, after_ts: int, before_ts: int
    ) -> list[tuple[int, dict]]:
        """(message_id, data) for every closed-segment record in (after, before].

        Same time-vs-snowflake convention as _page_segment_records: first page
        bounded by datetime, subsequent pages by int snowflake cursor.
        """
        after_dt = report_lib.ms_to_datetime(after_ts)
        out: list[tuple[int, dict]] = []
        seen: set[int] = set()
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
                    out.append((m.id, data))
            cursor_id = report_lib.next_page_cursor(
                [m.id for m in msgs], cursor_id, _PAGE_LIMIT
            )
            if cursor_id is None:
                break
            before_bound = cursor_id
        return out

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
            summary = await self._volume_summary_rows(start_ts, end_ts)
            csv_bytes = report_lib.render_csv(
                var_refs,
                rows,
                segment_label=self.config.segments_label.value,
                summary=summary,
            )
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

    async def _volume_summary_rows(
        self, start_ts, end_ts
    ) -> list[tuple[str, object]] | None:
        """Report-period volume summary rows for [start_ts, end_ts], or None.

        Discovers upstream totaliser apps from the tag_values aggregate (any
        block publishing the volume-totals convention; see
        report.discover_volume_totals), then computes each app's volume over the
        window from endpoint snapshots (the last logged values at/before each
        boundary; report.period_volume_totals does the E-minus-B arithmetic) and
        sums the per-app results. Differencing before summing keeps one app's
        missing baseline from skewing the others. Returns None when no app yields
        an end snapshot, so the CSV omits the block. The breakdown lists every
        configured kind plus "None".
        """
        aggregate = await self.api.fetch_channel_aggregate(TAG_VALUES_CHANNEL)
        app_keys = report_lib.totaliser_app_keys(aggregate.data or {})
        grand_total: float | None = None
        per_kind: dict[str, float] = {}
        produced = False
        for app_key in app_keys:
            # End snapshot: the last logged totals at/before end_ts with NO
            # lookback cap (that cap is a *baseline* bound only), so an app that
            # fell silent > _TOTALS_LOOKBACK_MS before end_ts still contributes
            # its in-window volume instead of vanishing from the summary.
            end_snap = await self._totals_snapshot(end_ts, app_key, lookback_ms=None)
            if end_snap[0] is None and not end_snap[1]:
                continue  # nothing ever logged at/before end for this app -> skip
            base_snap = await self._totals_snapshot(start_ts, app_key)
            if base_snap[0] is None or not base_snap[1]:
                # A baseline key is missing before start (app first logged inside
                # the window, the lookback cap was hit, or — since the two keys
                # log independently — only one of total_volume / segment_totals
                # was present in the lookback). Fill EACH missing key from the
                # earliest in-window sample so the diff is per-key against a real
                # baseline, not 0 (which would report the odometer's lifetime).
                fallback = await self._earliest_window_snapshot(
                    start_ts, end_ts, app_key
                )
                base_snap = report_lib.merge_baseline_snapshot(base_snap, fallback)
            p_grand, p_kind = report_lib.period_volume_totals(base_snap, end_snap)
            produced = True
            if p_grand is not None:
                grand_total = p_grand if grand_total is None else grand_total + p_grand
            for kind, vol in p_kind.items():
                per_kind[kind] = per_kind.get(kind, 0.0) + vol
        if not produced:
            return None
        kinds = self._segment_kinds() + [seg.NONE_KIND]
        return report_lib.build_volume_summary(grand_total, per_kind, kinds)

    async def _totals_snapshot(
        self, at_ts, app_key, lookback_ms: int | None = _TOTALS_LOOKBACK_MS
    ) -> tuple[float | None, dict[str, float]]:
        """Last logged ``(grand, per_kind)`` totals for ``app_key`` at/before ``at_ts``.

        Backward-pages tag_values (newest-first) for the most recent message
        whose block carries ``total_volume`` and — independently, since messages
        are per-change diffs that rarely move both at once — the most recent
        carrying ``segment_totals_json``. Stops once both are found or the
        lookback floor is reached. ``lookback_ms`` bounds how far before
        ``at_ts`` to page: ``_TOTALS_LOOKBACK_MS`` for a BASELINE snapshot (the
        spec's baseline lookback cap), ``None`` for an END snapshot so an app
        that fell silent well before ``at_ts`` still yields its last logged value
        rather than being dropped. Same time-vs-snowflake paging convention as
        _collect_window_rows: the first page is datetime-bounded, later pages by
        int snowflake cursor.
        """
        floor_dt = (
            report_lib.ms_to_datetime(at_ts - lookback_ms)
            if lookback_ms is not None
            else None
        )
        grand: float | None = None
        grand_found = False
        per_kind: dict[str, float] = {}
        kinds_found = False
        before_bound: datetime | int = report_lib.ms_to_datetime(at_ts)
        cursor_id: int | None = None
        while True:
            msgs = await self.api.list_messages(
                TAG_VALUES_CHANNEL,
                before=before_bound,
                after=floor_dt,
                limit=_PAGE_LIMIT,
                field_names=[app_key],
            )
            if not msgs:
                break
            # Newest-first so "first carrying X" is genuinely the most recent.
            for m in sorted(msgs, key=lambda msg: msg.id, reverse=True):
                block = (m.data or {}).get(app_key)
                if not isinstance(block, dict):
                    continue
                b_grand, b_kind = report_lib.totals_snapshot_from_block(block)
                if not grand_found and b_grand is not None:
                    grand = b_grand
                    grand_found = True
                if not kinds_found and report_lib.SEGMENT_TOTALS_KEY in block:
                    per_kind = b_kind
                    kinds_found = True
                if grand_found and kinds_found:
                    return grand, per_kind
            cursor_id = report_lib.next_page_cursor(
                [m.id for m in msgs], cursor_id, _PAGE_LIMIT
            )
            if cursor_id is None:
                break
            before_bound = cursor_id
        return grand, per_kind

    async def _earliest_window_snapshot(
        self, start_ts, end_ts, app_key
    ) -> tuple[float | None, dict[str, float]]:
        """Earliest in-window ``(grand, per_kind)`` totals for ``app_key``.

        The baseline fallback when nothing was logged before ``start_ts``: pages
        (start_ts, end_ts] and keeps the OLDEST message carrying ``total_volume``
        and the oldest carrying ``segment_totals_json`` (per-change diffs, so the
        two can differ). Returns ``(None, {})`` when the window has no totals, in
        which case period_volume_totals treats the baseline as zero.
        """
        after_dt = report_lib.ms_to_datetime(start_ts)
        grand: float | None = None
        grand_id: int | None = None
        per_kind: dict[str, float] = {}
        kinds_id: int | None = None
        before_bound: datetime | int = report_lib.ms_to_datetime(end_ts)
        cursor_id: int | None = None
        while True:
            msgs = await self.api.list_messages(
                TAG_VALUES_CHANNEL,
                before=before_bound,
                after=after_dt,
                limit=_PAGE_LIMIT,
                field_names=[app_key],
            )
            if not msgs:
                break
            for m in msgs:
                block = (m.data or {}).get(app_key)
                if not isinstance(block, dict):
                    continue
                b_grand, b_kind = report_lib.totals_snapshot_from_block(block)
                if b_grand is not None and (grand_id is None or m.id < grand_id):
                    grand = b_grand
                    grand_id = m.id
                if report_lib.SEGMENT_TOTALS_KEY in block and (
                    kinds_id is None or m.id < kinds_id
                ):
                    per_kind = b_kind
                    kinds_id = m.id
            cursor_id = report_lib.next_page_cursor(
                [m.id for m in msgs], cursor_id, _PAGE_LIMIT
            )
            if cursor_id is None:
                break
            before_bound = cursor_id
        return grand, per_kind

    async def _build_report(self, kind, start_ts, end_ts):
        current = await self._current_segment()
        closed_segments = await self._fetch_closed_segments(start_ts, end_ts)
        windows = seg.compute_windows(closed_segments, current, kind, start_ts, end_ts)

        # ui_state tells us WHICH numeric variables to report; each carries a
        # $tag reference that walk_numeric_variables resolves to the
        # tag_values location holding the actual value history.
        ui_state = await self.api.fetch_channel_aggregate(UI_STATE_CHANNEL)
        var_refs = report_lib.walk_numeric_variables(ui_state.data or {}, self.app_key)

        # In a per-pipeline report the grand-total (all-pipelines) total_volume
        # column is swapped for a running total scoped to THIS report's kind,
        # read from segment_totals_json — but only when the totaliser app
        # actually publishes it, so generic devices keep their total_volume.
        pipeline_total = None
        # The synthetic column inherits the total_volume variable's units so the
        # renamed header reads "Total Injected Volume (<units>)"; absent -> "".
        pipeline_total_units = ""
        total_ref = report_lib.find_total_volume_ref(var_refs)
        if total_ref is not None:
            tag_values = await self.api.fetch_channel_aggregate(TAG_VALUES_CHANNEL)
            block = (tag_values.data or {}).get(total_ref.path[0]) or {}
            if report_lib.SEGMENT_TOTALS_KEY in block:
                var_refs = [r for r in var_refs if r is not total_ref]
                pipeline_total = (report_lib.PIPELINE_TOTAL_COL, total_ref.path[0])
                pipeline_total_units = total_ref.units

        # tag_values messages are keyed by app_key at the top level; restrict
        # history reads to the app_keys our variables actually live under (plus
        # the totaliser app when a pipeline-total column is in play).
        source_app_keys = set(ref.path[0] for ref in var_refs if ref.path)
        if pipeline_total is not None:
            source_app_keys.add(pipeline_total[1])
        source_app_keys = sorted(source_app_keys)

        rows: list[dict] = []
        for win_start, win_end in windows:
            rows.extend(
                await self._collect_window_rows(
                    win_start, win_end, kind, var_refs, source_app_keys, pipeline_total
                )
            )

        report_refs = list(var_refs)
        if pipeline_total is not None:
            report_refs.append(
                report_lib.VariableRef(
                    report_lib.PIPELINE_TOTAL_COL,
                    report_lib.PIPELINE_TOTAL_LABEL,
                    (),
                    pipeline_total_units,
                )
            )
        return windows, rows, report_refs

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
        self,
        win_start: int,
        win_end: int,
        kind,
        var_refs,
        field_names,
        pipeline_total=None,
    ) -> list[dict]:
        """tag_values value rows in the window (win_start, win_end], epoch-ms.

        Reads the tag_values value history the ui_state variables reference.
        Same time-vs-snowflake convention as _page_segment_records: window
        bounds are epoch-ms ints converted to datetimes for ``list_messages``;
        subsequent-page cursors are int snowflake IDs. Messages that carry
        none of our variables (segment records, unrelated apps' tags) yield no
        row.

        ``pipeline_total`` is an optional ``(column, app_key)`` pair: when set,
        each message's per-kind cumulative volume (from that app's
        segment_totals_json) is added under ``column`` — the running total for
        this report's pipeline that replaces the grand total_volume column.
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
                data = m.data or {}
                values = report_lib.extract_row_values(data, var_refs)
                if pipeline_total is not None:
                    pt_col, pt_app_key = pipeline_total
                    pt_value = report_lib.pipeline_total_value(data, pt_app_key, kind)
                    if pt_value is not None:
                        values[pt_col] = pt_value
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


def _seg_differs(old: dict, new: dict) -> bool:
    """True if two closed segments with the same end differ in kind or start."""
    return old.get("kind") != new.get("kind") or int(old.get("start_ts", 0)) != int(
        new.get("start_ts", 0)
    )


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _snowflake_ms(message) -> int:
    """Epoch-ms of a message from its snowflake-derived timestamp."""
    return int(message.timestamp.timestamp() * 1000)
