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

# State-column seed lookback: how far before a window start to page tag_values
# for each state variable's last logged value (a pump left off for weeks logs
# nothing in between, so this is deliberately much longer than the totals
# cap). Bounded so a device that never logged the tag does not walk history
# to the beginning of time; a variable not found within it starts blank.
_STATE_LOOKBACK_MS = 30 * 24 * 60 * 60 * 1000

# One endpoint snapshot of a totaliser app: (grand_or_None, {kind: cumulative}).
# See report.totals_snapshot_from_block.
Snapshot = tuple[float | None, dict[str, float]]
# The per-report snapshot map: app_key -> (baseline snapshot, end snapshot).
SnapshotMap = dict[str, tuple[Snapshot, Snapshot]]


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

    def _device_name(self) -> str:
        """This device's display name (e.g. "Solar Skid 11"), for report filenames.

        The deployer lists the processor's own device in the install's
        DEVICE_MAP; falls back to APP_NAME when it is absent.
        """
        deployment = self.received_deployment_config or {}
        device = (deployment.get("DEVICE_MAP") or {}).get(str(self.agent_id)) or {}
        for key in ("display_name", "name"):
            value = device.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return APP_NAME

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
            # Endpoint snapshots are computed ONCE and shared: the summary
            # differences them, and the pipeline-total column re-bases every row
            # against the same baseline, so both report the same quantity
            # (E_k - B_k) rather than a period figure beside a lifetime one.
            # With one totaliser app the column's last cell IS the kind's
            # summary row (closed windows get a closing row, bounded by the next
            # window and capped at E_k - B_k; see _build_report).
            snapshots = await self._period_snapshots(start_ts, end_ts)
            windows, rows, var_refs = await self._build_report(
                kind, start_ts, end_ts, snapshots
            )
            summary = self._volume_summary_rows(snapshots)
            csv_bytes = report_lib.render_csv(
                var_refs,
                rows,
                segment_label=self.config.segments_label.value,
                summary=summary,
            )
            filename = report_lib.build_report_filename(
                self._device_name(),
                start_ts,
                end_ts,
                report_lib.resolve_timezone(params.get("tz")),
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

    async def _period_snapshots(self, start_ts, end_ts) -> SnapshotMap:
        """Per-totaliser-app ``(baseline, end)`` snapshots for [start_ts, end_ts].

        The single IO pass behind BOTH volume figures in a report — the summary
        block and the per-pipeline running-total column — so the two can never
        disagree about what the period's baseline is. They agree at the other
        endpoint too, closed windows getting a closing row for the totaliser's
        post-close republish, capped against this same map's end snapshot
        (see _build_report / _closing_row).

        Discovers upstream totaliser apps from the tag_values aggregate (any
        block publishing the volume-totals convention; see
        report.discover_volume_totals) and, for each, reads the endpoint
        snapshots (the last logged totals at/before each boundary). An app with
        no end snapshot at all is skipped (it never logged totals at/before
        end_ts). Returns ``{app_key: (base_snap, end_snap)}``, keyed in sorted
        app-key order; empty when no app follows the convention.
        """
        aggregate = await self.api.fetch_channel_aggregate(TAG_VALUES_CHANNEL)
        app_keys = report_lib.totaliser_app_keys(aggregate.data or {})
        snapshots: SnapshotMap = {}
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
            snapshots[app_key] = (base_snap, end_snap)
        return snapshots

    def _volume_summary_rows(
        self, snapshots: SnapshotMap
    ) -> list[tuple[str, object]] | None:
        """Report-period volume summary rows from _period_snapshots, or None.

        Pure over the snapshot map: computes each app's volume over the window
        from its ``(baseline, end)`` endpoint pair (report.period_volume_totals
        does the E-minus-B arithmetic) and sums the per-app results.
        Differencing before summing keeps one app's missing baseline from
        skewing the others. Returns None when no app yielded a snapshot, so the
        CSV omits the block. The breakdown lists every configured kind plus
        "None".
        """
        grand_total: float | None = None
        per_kind: dict[str, float] = {}
        for base_snap, end_snap in snapshots.values():
            p_grand, p_kind = report_lib.period_volume_totals(base_snap, end_snap)
            if p_grand is not None:
                grand_total = p_grand if grand_total is None else grand_total + p_grand
            for kind, vol in p_kind.items():
                per_kind[kind] = per_kind.get(kind, 0.0) + vol
        if not snapshots:
            return None
        kinds = self._segment_kinds() + [seg.NONE_KIND]
        return report_lib.build_volume_summary(grand_total, per_kind, kinds)

    async def _totals_snapshot(
        self, at_ts, app_key, lookback_ms: int | None = _TOTALS_LOOKBACK_MS
    ) -> Snapshot:
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

    async def _earliest_window_snapshot(self, start_ts, end_ts, app_key) -> Snapshot:
        """Earliest in-window ``(grand, per_kind)`` totals for ``app_key``.

        The baseline fallback when nothing was logged before ``start_ts``: pages
        (start_ts, end_ts] and keeps the OLDEST message carrying ``total_volume``
        and the oldest carrying ``segment_totals_json`` (per-change diffs, so the
        two can differ). Returns ``(None, {})`` when the window has no totals, in
        which case period_volume_totals treats the baseline as zero.
        """
        grand, per_kind, _found = await self._earliest_window_totals(
            start_ts, end_ts, app_key
        )
        return grand, per_kind

    async def _earliest_window_totals(
        self, start_ts, end_ts, app_key, require_kind: str | None = None
    ) -> tuple[float | None, dict[str, float], bool]:
        """_earliest_window_snapshot plus "did a message carry the per-kind key".

        Same scan, one extra fact: the third element is True iff some message in
        (start_ts, end_ts] actually carried ``segment_totals_json``. The
        snapshot alone cannot say — ``per_kind == {}`` means both "no such
        message" and "the JSON was empty" — and _closing_kind_total must tell
        those apart to know whether it found the frozen post-close total.

        ``require_kind`` narrows what counts as carrying the key: a message
        qualifies only when its parsed map holds a numeric value for THAT kind.
        Mere presence of ``segment_totals_json`` is not enough for a caller
        after one kind's figure — _parse_json_object is junk-tolerant, so an
        empty/malformed map (or one that simply omits this kind) would
        otherwise read as "found, value 0.0". The baseline fallback passes None
        and keeps the looser "any totals message" rule.
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
                carries_kinds = report_lib.SEGMENT_TOTALS_KEY in block and (
                    require_kind is None or require_kind in b_kind
                )
                if carries_kinds and (kinds_id is None or m.id < kinds_id):
                    per_kind = b_kind
                    kinds_id = m.id
            cursor_id = report_lib.next_page_cursor(
                [m.id for m in msgs], cursor_id, _PAGE_LIMIT
            )
            if cursor_id is None:
                break
            before_bound = cursor_id
        return grand, per_kind, kinds_id is not None

    async def _closing_kind_total(self, we, scan_end, app_key, kind) -> float | None:
        """``kind``'s frozen cumulative published just after its window closed at ``we``.

        The upstream totaliser freezes a segment's total at the switch instant
        but only publishes that frozen figure in its NEXT ``segment_totals_json``
        log (the ~900 s republish timer, or the first message of an offline
        device's reconnect backlog) — i.e. in a message *after* the window
        closed, which _collect_window_rows can never emit as a row. This finds
        it: forward-scans (we, scan_end] in growing chunks (like
        _find_boundary_crossing_segment, pydoover having no ascending order) and
        returns the kind's value in the EARLIEST message that actually carries a
        figure for ``kind``, or None when none was logged in that range.

        ``scan_end`` is the instant the frozen figure stops being frozen: the
        NEXT window of this kind (the kind accrues again from there, so a later
        message is not this window's closing figure), or ``end_ts`` for the last
        window. It is never beyond ``end_ts``. A window with no totals message
        in its range gets no closing row at all — the frozen figure is genuinely
        unknown there, which is better said with a blank cell than invented.
        """
        cursor = we
        chunk = _CROSS_SCAN_INITIAL_MS
        while cursor < scan_end:
            upper = min(cursor + chunk, scan_end)
            _grand, per_kind, found = await self._earliest_window_totals(
                cursor, upper, app_key, require_kind=kind
            )
            if found:
                return float(per_kind[kind])
            cursor = upper
            chunk *= _CROSS_SCAN_GROWTH
        return None

    async def _closing_row(
        self,
        win_end,
        scan_end,
        kind,
        pipeline_total,
        pipeline_baseline,
        pipeline_cap,
        win_rows,
    ) -> dict | None:
        """The synthetic last row of a CLOSED window, or None.

        Carries only the pipeline-total cell (same shape as a diff message that
        happened to carry just the totaliser key), timestamped at the window's
        end, so a closed segment's column ends on the accrual the device
        published after the switch rather than at its last in-window sample.
        ``scan_end`` bounds the search for that accrual (see
        _closing_kind_total).

        Two bounds keep the row honest. ``pipeline_cap`` is this app's own
        summary figure ``E_k - B_k``, and the value is capped at it: the scan
        returns the EARLIEST post-close sample while the summary takes the LAST
        one at/before end_ts, so on a series that is non-monotone between them
        (an odometer reset, or a retroactive repaint re-attributing volume away
        from this kind) the raw figure could otherwise sit ABOVE the summary.
        And the row is emitted only when it is strictly above every pipeline
        value already in the window AND above zero — the column stays monotone
        and never invents movement the totaliser did not report.
        """
        pt_col, pt_app_key = pipeline_total
        closing_total = await self._closing_kind_total(
            win_end, scan_end, pt_app_key, kind
        )
        if closing_total is None:
            return None
        period_value = report_lib.pipeline_period_value(
            closing_total, pipeline_baseline
        )
        if pipeline_cap is not None:
            period_value = min(period_value, pipeline_cap)
        seen = [r["values"][pt_col] for r in win_rows if pt_col in r["values"]]
        if period_value <= max(seen, default=0.0):
            return None
        return {
            "timestamp_utc": report_lib.format_timestamp_utc(win_end),
            "segment_kind": kind,
            "values": {pt_col: period_value},
        }

    async def _build_report(self, kind, start_ts, end_ts, snapshots: SnapshotMap):
        """Windows, rows and column refs for one report.

        ``snapshots`` is the _period_snapshots map; the pipeline-total column
        re-bases every row against the totaliser app's baseline per-kind value
        taken from it, which is exactly what the summary differences against.
        Each CLOSED window then gets a closing row (_closing_row) carrying the
        frozen total the totaliser published after the switch, so the column's
        final value equals the "<kind> (report period)" summary row whenever one
        app publishes the convention. Each closing scan is bounded by the NEXT
        window of this kind (``end_ts`` for the last one), so an intermediate
        window is never credited with a later window's accrual, and every row is
        capped at the app's own ``E_k - B_k`` so the column can never exceed the
        summary. With more than one totaliser app the summary sums them all
        while the column tracks the single app owning the total_volume variable,
        and equality is not claimed.
        """
        current = await self._current_segment()
        closed_segments = await self._fetch_closed_segments(start_ts, end_ts)
        windows = seg.compute_windows(closed_segments, current, kind, start_ts, end_ts)

        # ui_state tells us WHICH variables to report (numeric AND state-like);
        # each carries a $tag reference that walk_variables resolves to the
        # tag_values location holding the actual value history.
        ui_state = await self.api.fetch_channel_aggregate(UI_STATE_CHANNEL)
        var_refs = report_lib.walk_variables(ui_state.data or {}, self.app_key)
        state_refs = [r for r in var_refs if r.kind == report_lib.STATE_KIND]

        # In a per-pipeline report the grand-total (all-pipelines) total_volume
        # column is swapped for a running total scoped to THIS report's kind,
        # read from segment_totals_json — but only when the totaliser app
        # actually publishes it, so generic devices keep their total_volume.
        pipeline_total = None
        # The synthetic column inherits the total_volume variable's units so the
        # renamed header reads "Total Injected Volume (<units>)"; absent -> "".
        pipeline_total_units = ""
        # Baseline this report's kind started the period at, so each row is a
        # period figure rather than the odometer's lifetime one (0.0 when the
        # totaliser app has no snapshot, or the kind is absent from its
        # baseline — i.e. the kind had accrued nothing before the window).
        pipeline_baseline = 0.0
        # Ceiling for a closing row: this app's own summary figure E_k - B_k.
        # None when the app has no snapshot, in which case there is no summary
        # figure to stay under either.
        pipeline_cap: float | None = None
        total_ref = report_lib.find_total_volume_ref(var_refs)
        if total_ref is not None:
            tag_values = await self.api.fetch_channel_aggregate(TAG_VALUES_CHANNEL)
            pt_app_key = total_ref.path[0]
            block = (tag_values.data or {}).get(pt_app_key) or {}
            if report_lib.SEGMENT_TOTALS_KEY in block:
                var_refs = [r for r in var_refs if r is not total_ref]
                pipeline_total = (report_lib.PIPELINE_TOTAL_COL, pt_app_key)
                pipeline_total_units = total_ref.units
                snapshot = snapshots.get(pt_app_key)
                if snapshot is not None:
                    pipeline_baseline = snapshot[0][1].get(kind, 0.0)
                    pipeline_cap = report_lib.pipeline_period_value(
                        snapshot[1][1].get(kind, 0.0), pipeline_baseline
                    )

        # tag_values messages are keyed by app_key at the top level; restrict
        # history reads to the app_keys our variables actually live under (plus
        # the totaliser app when a pipeline-total column is in play).
        source_app_keys = set(ref.path[0] for ref in var_refs if ref.path)
        if pipeline_total is not None:
            source_app_keys.add(pipeline_total[1])
        source_app_keys = sorted(source_app_keys)

        rows: list[dict] = []
        for i, (win_start, win_end) in enumerate(windows):
            win_rows = await self._collect_window_rows(
                win_start,
                win_end,
                kind,
                var_refs,
                source_app_keys,
                pipeline_total,
                pipeline_baseline,
            )
            # A window that closed before end_ts stops short of the totaliser's
            # post-close republish, which the summary's end snapshot DOES see;
            # a closing row carries that frozen figure so the two agree. A
            # window ending AT end_ts needs none: its last in-window message is
            # already the summary's end snapshot.
            #
            # The scan for that figure stops where this window's total stops
            # being frozen — the next window of this kind, or end_ts for the
            # last one. Without that bound a window whose off-period is shorter
            # than the ~900 s republish would take its "frozen" figure from a
            # message logged inside the NEXT window, crediting this one with
            # volume it never pumped.
            if pipeline_total is not None and win_end < end_ts:
                scan_end = windows[i + 1][0] if i + 1 < len(windows) else end_ts
                closing = await self._closing_row(
                    win_end,
                    scan_end,
                    kind,
                    pipeline_total,
                    pipeline_baseline,
                    pipeline_cap,
                    win_rows,
                )
                if closing is not None:
                    win_rows.append(closing)
            # State columns (pump running, mode strings) persist between
            # changes: fill every row of the window with the last known value,
            # seeded from the value each variable last logged before the
            # window opened so the first rows are not blank either.
            if state_refs and win_rows:
                seed = await self._state_seed(win_start, state_refs)
                report_lib.forward_fill_state(win_rows, state_refs, seed)
            rows.extend(win_rows)

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

    async def _state_seed(
        self, at_ts, state_refs: list[report_lib.VariableRef]
    ) -> dict[str, object]:
        """Each state variable's last logged value at/before ``at_ts``.

        Backward-pages tag_values (newest-first, one scan per source app key,
        ``field_names`` filtered to it) within _STATE_LOOKBACK_MS and keeps
        the FIRST bool/str value seen per column — i.e. the most recent — so
        forward_fill_state can carry it into a window whose own messages never
        mention the variable (a pump that stayed off all day). Stops paging an
        app as soon as all its columns are found. Returns ``{column: value}``;
        a column not logged within the lookback is simply absent.
        """
        by_app: dict[str, list[report_lib.VariableRef]] = {}
        for ref in state_refs:
            if ref.path:
                by_app.setdefault(ref.path[0], []).append(ref)
        floor_dt = report_lib.ms_to_datetime(at_ts - _STATE_LOOKBACK_MS)
        seed: dict[str, object] = {}
        for app_key, refs in by_app.items():
            pending = {ref.column: ref for ref in refs}
            before_bound: datetime | int = report_lib.ms_to_datetime(at_ts)
            cursor_id: int | None = None
            while pending:
                msgs = await self.api.list_messages(
                    TAG_VALUES_CHANNEL,
                    before=before_bound,
                    after=floor_dt,
                    limit=_PAGE_LIMIT,
                    field_names=[app_key],
                )
                if not msgs:
                    break
                for m in sorted(msgs, key=lambda msg: msg.id, reverse=True):
                    found = report_lib.extract_row_values(
                        m.data or {}, list(pending.values())
                    )
                    for col, value in found.items():
                        seed[col] = value
                        pending.pop(col, None)
                    if not pending:
                        break
                cursor_id = report_lib.next_page_cursor(
                    [m.id for m in msgs], cursor_id, _PAGE_LIMIT
                )
                if cursor_id is None:
                    break
                before_bound = cursor_id
        return seed

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
        pipeline_baseline: float = 0.0,
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
        That cumulative is the odometer's LIFETIME figure, so it is re-based
        against ``pipeline_baseline`` (the kind's value in the report's baseline
        snapshot) by report.pipeline_period_value: the column is then scoped to
        the report period and reads on the summary's scale.

        Rows here are message-exact within (win_start, win_end], so a window
        that closed before ``end_ts`` stops at its last in-window sample while
        the summary's end snapshot also sees the totaliser's post-close
        republish. _build_report closes that gap with a synthetic closing row
        (_closing_row); with a single totaliser app the column's final value is
        then the summary's "<kind> (report period)" value. Only that synthetic
        row is bounded by the summary — a real cell reports what the device
        published at that instant, even where a repaint later moved the figure.
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
                        values[pt_col] = report_lib.pipeline_period_value(
                            pt_value, pipeline_baseline
                        )
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
