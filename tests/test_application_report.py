"""Application-level report test over a fake data client (no network).

Reproduces the live Skid 9 case that exposed the baseline mismatch: the
running "Total Injected Volume" column showed the on-device odometer's
LIFETIME per-pipeline cumulative (ending at 67.22) while the summary block
quoted the report-period figure (40.11), so the report read as wrong. Both
must be period-scoped against the SAME baseline snapshot, which puts the column
on the summary's scale.

The second half pins the OTHER endpoint. With one totaliser app the column's
last value equals the "<kind> (report period)" row for every segment shape: a
segment still open at end_ts ends on the summary's own end message, and a
segment that closed earlier gets a synthetic closing row carrying the frozen
total the totaliser republished after the switch (application._closing_row).
The final test pins the one documented non-equality: a second totaliser app,
which the summary sums but the column does not track.
"""

import json
from datetime import datetime

import pytest

from data_report_segmenter import report as report_lib
from data_report_segmenter.application import DataReportSegmenterApp

APP_KEY = "data_report_segmenter_1"
TOTALISER_KEY = "petronash_pump_controller_1"
KIND = "Pipeline A"

# The live report's bounds: 2026-09-07T12:51Z .. 2026-09-08T12:51Z.
START_TS = 1788785460000
END_TS = 1788871860000

# Live values, verified on device Skid 9 (agent 162764132012063503).
BASE_GRAND = 95.21265356217064
BASE_KIND = 27.10944344343592
FIRST_KIND = 33.618647713965274  # first in-window sample (device back online)
END_GRAND = 135.31848527571444
END_KIND = 67.21527515697971
NONE_KIND_VOLUME = 68.10321011873472  # unchanged across the window


def _totals(kind_volume: float) -> str:
    return json.dumps({"None": NONE_KIND_VOLUME, KIND: kind_volume})


class FakeMessage:
    """Minimal stand-in for a pydoover message: id, data, snowflake timestamp."""

    def __init__(self, message_id: int, ts_ms: int, data: dict):
        self.id = message_id
        self.data = data
        # Same epoch-ms -> aware-datetime conversion the app uses for bounds.
        self.timestamp = report_lib.ms_to_datetime(ts_ms)


class FakeAggregate:
    def __init__(self, data: dict):
        self.data = data


class FakeApi:
    """Fake ProcessorDataClient: aggregates by channel + a message log.

    ``list_messages`` honours the app's time-vs-snowflake bound convention —
    a ``datetime`` ``before``/``after`` filters on message time, an int
    ``before`` is a snowflake cursor — and returns newest-first.
    """

    def __init__(self, aggregates: dict, messages: dict):
        self.aggregates = aggregates
        self.messages = messages
        self.calls: list[tuple] = []

    async def fetch_channel_aggregate(self, channel):
        self.calls.append(("fetch_channel_aggregate", channel))
        return FakeAggregate(self.aggregates.get(channel, {}))

    async def list_messages(
        self, channel, before=None, after=None, limit=None, field_names=None
    ):
        self.calls.append(("list_messages", channel))
        out = []
        for msg in self.messages.get(channel, []):
            if isinstance(before, datetime):
                if msg.timestamp > before:
                    continue
            elif before is not None and msg.id >= before:
                continue
            if after is not None and msg.timestamp <= after:
                continue
            out.append(msg)
        out.sort(key=lambda m: m.id, reverse=True)
        return out[:limit] if limit else out


def _make_app() -> DataReportSegmenterApp:
    app = DataReportSegmenterApp()
    app.app_key = APP_KEY
    app.config._inject_deployment_config(
        {
            "segment_kinds": [KIND],
            "segments_label": "Pipeline",
            "dv_proc_subscriptions": ["dv-rpc"],
            "dv_proc_schedules": [],
            "dv_proc_timezone": "UTC",
        }
    )
    tag_values_aggregate = {
        TOTALISER_KEY: {
            "total_volume": END_GRAND,
            "segment_totals_json": _totals(END_KIND),
        },
        APP_KEY: {
            # Open segment covering the whole report window.
            "current_segment": {"kind": KIND, "start_ts": START_TS - 86_400_000}
        },
    }
    ui_state_aggregate = {
        "state": {
            "children": {
                TOTALISER_KEY: {
                    "type": "uiApplication",
                    "children": {
                        # 4-20mA style: units published as " (GPH)".
                        "flow_value": {
                            "type": "uiVariable",
                            "varType": "float",
                            "displayString": "AI Value",
                            "units": " (GPH)",
                            "currentValue": "$tag.app().flow_value:number:null",
                        },
                        "total_volume": {
                            "type": "uiVariable",
                            "varType": "float",
                            "displayString": "Total Volume Pumped",
                            "units": "L",
                            "currentValue": "$tag.app().total_volume:number:0",
                        },
                    },
                }
            }
        }
    }
    messages = [
        # Baseline: last tag_values message BEFORE start_ts.
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        # First in-window sample: the device was offline across the boundary,
        # but the on-device odometer kept integrating while it was away.
        FakeMessage(
            200,
            1788840960000,  # 2026-09-08T04:16Z
            {
                TOTALISER_KEY: {
                    "flow_value": 12.5,
                    "segment_totals_json": _totals(FIRST_KIND),
                }
            },
        ),
        FakeMessage(
            300,
            END_TS - 60_000,
            {
                TOTALISER_KEY: {
                    "flow_value": 11.0,
                    "total_volume": END_GRAND,
                    "segment_totals_json": _totals(END_KIND),
                }
            },
        ),
    ]
    app.api = FakeApi(
        {"tag_values": tag_values_aggregate, "ui_state": ui_state_aggregate},
        {"tag_values": messages},
    )
    return app


def _totals_msg(
    message_id: int, ts_ms: int, kind_volume: float, extra: dict | None = None
):
    """A tag_values message carrying the totaliser's segment_totals_json."""
    block = {"segment_totals_json": _totals(kind_volume)}
    if extra:
        block.update(extra)
    return FakeMessage(message_id, ts_ms, {TOTALISER_KEY: block})


def _segment_record(message_id: int, end_ts: int, kind: str, start_ts: int):
    """A closed-segment record; timestamped at the segment's END, as on device."""
    return FakeMessage(
        message_id,
        end_ts,
        {
            "record_type": "segment",
            "kind": kind,
            "start_ts": start_ts,
            "end_ts": end_ts,
        },
    )


def _set_messages(app, *msgs) -> None:
    """Replace the fake tag_values log (ids kept monotone in time, as on device)."""
    app.api.messages["tag_values"] = list(msgs)


def _close_segment_at(app, closed_at: int) -> None:
    """Point the open segment at "None" from ``closed_at``, closing KIND there."""
    app.api.aggregates["tag_values"][APP_KEY]["current_segment"] = {
        "kind": "None",
        "start_ts": closed_at,
    }


def _pipeline_column(rows) -> list[float]:
    ordered = sorted(rows, key=lambda r: r["timestamp_utc"])
    return [
        r["values"][report_lib.PIPELINE_TOTAL_COL]
        for r in ordered
        if report_lib.PIPELINE_TOTAL_COL in r["values"]
    ]


def _assert_column_ends_on_summary(summary, rows) -> list[float]:
    """The invariant: the column's last cell IS the kind's report-period total.

    Checked both as the operator sees it (2-dp rendered) and on the raw floats.
    """
    period_total = dict(summary)[f"{KIND} (report period)"]
    column = _pipeline_column(rows)
    assert float(f"{column[-1]:.2f}") == float(f"{period_total:.2f}")
    assert column[-1] == pytest.approx(period_total, abs=1e-9)
    return column


async def _run_report(app):
    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    windows, rows, refs = await app._build_report(KIND, START_TS, END_TS, snapshots)
    csv_text = report_lib.render_csv(
        refs,
        rows,
        segment_label=app.config.segments_label.value,
        summary=summary,
    ).decode("utf-8")
    return snapshots, summary, windows, rows, refs, csv_text


@pytest.mark.asyncio
async def test_skid9_summary_and_column_share_one_baseline():
    app = _make_app()
    _snap, summary, _windows, rows, refs, csv_text = await _run_report(app)

    # Summary: E - B on both the grand and the per-kind figure -> 40.11.
    by_label = dict(summary)
    assert round(by_label["Grand Total Volume (report period)"], 2) == 40.11
    assert round(by_label[f"{KIND} (report period)"], 2) == 40.11
    assert by_label["None (report period)"] == 0.0

    # The running column is period-scoped: it starts from the pre-window
    # baseline (33.62 - 27.11 = 6.51) and ENDS on the summary's figure rather
    # than the odometer's lifetime 67.22.
    ordered = sorted(rows, key=lambda r: r["timestamp_utc"])
    column = [r["values"][report_lib.PIPELINE_TOTAL_COL] for r in ordered]
    assert [round(v, 2) for v in column] == [6.51, 40.11]
    assert column[-1] == pytest.approx(by_label[f"{KIND} (report period)"])

    # The grand total_volume column is gone, replaced by the pipeline column,
    # which inherits total_volume's units; the 4-20mA header is not
    # double-wrapped ("AI Value ((GPH))" was the live rendering).
    headers = [report_lib.column_header(ref) for ref in refs]
    assert headers == ["AI Value (GPH)", "Total Injected Volume (L)"]

    lines = csv_text.splitlines()
    assert lines[0] == "Grand Total Volume (report period),40.11"
    assert lines[1] == f"{KIND} (report period),40.11"
    assert lines[2] == "None (report period),0.00"
    assert lines[3] == ""
    assert lines[4] == (
        "Timestamp (UTC),Pipeline,AI Value (GPH),Total Injected Volume (L)"
    )
    assert lines[5].endswith(",Pipeline A,12.50,6.51")
    assert lines[6].endswith(",Pipeline A,11.00,40.11")
    # The lifetime figure never reaches a cell.
    assert "67.22" not in csv_text


@pytest.mark.asyncio
async def test_snapshots_are_fetched_once_and_shared():
    app = _make_app()
    snapshots, _summary, _w, _rows, _refs, _csv = await _run_report(app)

    # One (baseline, end) pair for the single totaliser app, and the baseline
    # per-kind value is exactly what the column re-bases against.
    assert list(snapshots) == [TOTALISER_KEY]
    base_snap, end_snap = snapshots[TOTALISER_KEY]
    assert base_snap == (BASE_GRAND, {"None": NONE_KIND_VOLUME, KIND: BASE_KIND})
    assert end_snap == (END_GRAND, {"None": NONE_KIND_VOLUME, KIND: END_KIND})

    # _volume_summary_rows does no IO: it is a plain function of the snapshots.
    calls_before = len(app.api.calls)
    app._volume_summary_rows(snapshots)
    assert len(app.api.calls) == calls_before


@pytest.mark.asyncio
async def test_no_totaliser_app_leaves_column_and_summary_alone():
    # A device without the totaliser convention: no summary block, and the
    # plain total_volume column stays exactly as discovered.
    app = _make_app()
    app.api.aggregates["tag_values"][TOTALISER_KEY].pop("segment_totals_json")

    snapshots = await app._period_snapshots(START_TS, END_TS)
    assert snapshots == {}
    assert app._volume_summary_rows(snapshots) is None

    _windows, rows, refs = await app._build_report(KIND, START_TS, END_TS, snapshots)
    headers = [report_lib.column_header(ref) for ref in refs]
    assert headers == ["AI Value (GPH)", "Total Volume Pumped (L)"]
    assert all(report_lib.PIPELINE_TOTAL_COL not in r["values"] for r in rows)


# --- the column always ends on the summary (single totaliser app) ---------
#
# Four segment shapes, one invariant. The upstream totaliser freezes a
# segment's total at the switch instant and publishes it only in its NEXT
# segment_totals_json log (~900 s timer, or an offline device's backlog), i.e.
# after the window closed — which is why a closed window needs a closing row.


@pytest.mark.asyncio
async def test_open_segment_last_row_is_the_summary():
    # (a) KIND still open at end_ts: no closing row is needed or emitted, the
    # last in-window message being the summary's end snapshot itself.
    app = _make_app()
    _snap, summary, windows, rows, _refs, _csv = await _run_report(app)

    assert windows == [(START_TS, END_TS)]
    column = _assert_column_ends_on_summary(summary, rows)
    assert [round(v, 2) for v in column] == [6.51, 40.11]
    # Every row came from a real message; nothing synthetic was appended.
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_closed_segment_closing_row_carries_the_frozen_total():
    # (b) KIND closed 2 h before end_ts, the frozen figure republished 15 min
    # later — outside any KIND window. The closing row puts it at the window's
    # end, so the column lands exactly on the summary instead of 2 h short.
    app = _make_app()
    closed_at = END_TS - 7_200_000
    _close_segment_at(app, closed_at)
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(200, 1788840960000, FIRST_KIND, {"flow_value": 12.5}),
        _segment_record(250, closed_at, KIND, START_TS - 86_400_000),
        # The post-close republish: KIND's total is frozen at its switch value.
        _totals_msg(260, closed_at + 900_000, END_KIND, {"total_volume": END_GRAND}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    assert windows == [(START_TS, closed_at)]
    column = _assert_column_ends_on_summary(summary, rows)
    assert [round(v, 2) for v in column] == [6.51, 40.11]
    # The closing row sits at the window's end and carries ONLY that cell.
    closing = max(rows, key=lambda r: r["timestamp_utc"])
    assert closing["timestamp_utc"] == report_lib.format_timestamp_utc(closed_at)
    assert list(closing["values"]) == [report_lib.PIPELINE_TOTAL_COL]


@pytest.mark.asyncio
async def test_kind_switched_away_and_back_closes_only_the_first_window():
    # (c) A -> B -> A across the period: the first A window is closed (closing
    # row from the first totals message after it), the second is open at end_ts
    # (no closing row). The report's final row is still the summary's figure.
    app = _make_app()
    a1_end = START_TS + 3_600_000
    a2_start = a1_end + 3_600_000
    app.api.aggregates["tag_values"][APP_KEY]["current_segment"] = {
        "kind": KIND,
        "start_ts": a2_start,
    }
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(150, START_TS + 1_800_000, 30.0, {"flow_value": 9.0}),
        _segment_record(160, a1_end, KIND, START_TS - 86_400_000),
        # Frozen first-window total, republished while B is the live segment.
        _totals_msg(170, a1_end + 900_000, 31.0),
        _segment_record(180, a2_start, "None", a1_end),
        _totals_msg(200, 1788840960000, FIRST_KIND, {"flow_value": 12.5}),
        _totals_msg(300, END_TS - 60_000, END_KIND, {"total_volume": END_GRAND}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    assert windows == [(START_TS, a1_end), (a2_start, END_TS)]
    column = _assert_column_ends_on_summary(summary, rows)
    # window 1 sample, window 1 closing row, then the two window 2 samples.
    assert [round(v, 2) for v in column] == [2.89, 3.89, 6.51, 40.11]
    at_a1_end = [
        r for r in rows if r["timestamp_utc"] == report_lib.format_timestamp_utc(a1_end)
    ]
    assert len(at_a1_end) == 1


@pytest.mark.asyncio
async def test_closed_segment_with_no_later_totals_needs_no_closing_row():
    # (d) KIND closed 10 min before end_ts and the device logged no totals
    # after the switch. Nothing to add — and nothing missing: the summary's
    # E_k is then that same last in-window message.
    app = _make_app()
    closed_at = END_TS - 600_000
    _close_segment_at(app, closed_at)
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(200, 1788840960000, FIRST_KIND, {"flow_value": 12.5}),
        _totals_msg(300, closed_at - 60_000, END_KIND, {"total_volume": END_GRAND}),
        _segment_record(310, closed_at, KIND, START_TS - 86_400_000),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    assert windows == [(START_TS, closed_at)]
    column = _assert_column_ends_on_summary(summary, rows)
    assert [round(v, 2) for v in column] == [6.51, 40.11]
    assert len(rows) == 2  # both real messages; no closing row


@pytest.mark.asyncio
async def test_offline_backlog_after_close_still_closes_the_column():
    # (e) KIND closed, then the device is offline: no messages at all for over
    # an hour, then a reconnect burst before end_ts carrying the frozen total.
    # The closing scan grows its chunks past the silence and finds it.
    app = _make_app()
    closed_at = END_TS - 7_200_000
    _close_segment_at(app, closed_at)
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(200, 1788840960000, FIRST_KIND, {"flow_value": 12.5}),
        _segment_record(250, closed_at, KIND, START_TS - 86_400_000),
        # Reconnect burst, 1.5 h of silence later.
        _totals_msg(400, END_TS - 1_800_000, END_KIND, {"total_volume": END_GRAND}),
        _totals_msg(410, END_TS - 1_500_000, END_KIND, {"flow_value": 0.0}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    assert windows == [(START_TS, closed_at)]
    column = _assert_column_ends_on_summary(summary, rows)
    assert [round(v, 2) for v in column] == [6.51, 40.11]


# --- the closing row never overstates ------------------------------------
#
# The closing scan finds the EARLIEST totals message after the close, while
# the summary's E_k is the LAST one at/before end_ts. Those coincide only
# while the kind's series is monotone between them, which it need not be (an
# odometer reset, a retroactive repaint re-attributing volume away from the
# kind). The row is therefore capped at the app's own E_k - B_k, and a chunk
# only counts as "found" when it actually carries a figure for this kind.


def _closing_rows_at(rows, at_ts):
    """Synthetic rows sitting on a window's end instant."""
    stamp = report_lib.format_timestamp_utc(at_ts)
    return [
        r
        for r in rows
        if r["timestamp_utc"] == stamp
        and list(r["values"]) == [report_lib.PIPELINE_TOTAL_COL]
    ]


@pytest.mark.asyncio
async def test_closing_row_capped_when_volume_is_reattributed_later():
    # The frozen republish says 67.22, but a LATER message before end_ts
    # re-attributes most of it away (30.0), so the summary is only 2.89. The
    # closing row must not carry the stale higher figure past the summary.
    app = _make_app()
    closed_at = END_TS - 7_200_000
    _close_segment_at(app, closed_at)
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(200, 1788840960000, FIRST_KIND, {"flow_value": 12.5}),
        _segment_record(250, closed_at, KIND, START_TS - 86_400_000),
        _totals_msg(260, closed_at + 900_000, END_KIND, {"total_volume": END_GRAND}),
        _totals_msg(270, END_TS - 600_000, 30.0, {"total_volume": END_GRAND}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    _windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    period_total = dict(summary)[f"{KIND} (report period)"]
    assert round(period_total, 2) == 2.89
    for row in _closing_rows_at(rows, closed_at):
        assert row["values"][report_lib.PIPELINE_TOTAL_COL] <= period_total + 1e-9
    # The stale 40.11 never reaches a cell.
    assert all(
        v <= period_total + 1e-9 or v == pytest.approx(6.509204270529352)
        for v in _pipeline_column(rows)
    )


@pytest.mark.asyncio
async def test_odometer_reset_after_close_emits_no_closing_row():
    # The device restarted its odometer before end_ts, so E_k (0.5) is below
    # the baseline and the kind's period figure is 0.0. A closing row carrying
    # the pre-reset frozen 67.22 would sit 40 L above the summary.
    app = _make_app()
    closed_at = END_TS - 7_200_000
    _close_segment_at(app, closed_at)
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(200, 1788840960000, FIRST_KIND, {"flow_value": 12.5}),
        _segment_record(250, closed_at, KIND, START_TS - 86_400_000),
        _totals_msg(260, closed_at + 900_000, END_KIND, {"total_volume": END_GRAND}),
        _totals_msg(270, END_TS - 600_000, 0.5, {"total_volume": 0.5}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    _windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    assert dict(summary)[f"{KIND} (report period)"] == 0.0
    assert _closing_rows_at(rows, closed_at) == []


@pytest.mark.asyncio
async def test_empty_totals_map_after_close_is_not_the_frozen_figure():
    # A message carrying segment_totals_json but no usable map ("{}") must not
    # end the scan at 0.0 — the real republish is the next message along.
    app = _make_app()
    closed_at = END_TS - 7_200_000
    _close_segment_at(app, closed_at)
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(200, 1788840960000, FIRST_KIND, {"flow_value": 12.5}),
        _segment_record(250, closed_at, KIND, START_TS - 86_400_000),
        FakeMessage(
            255, closed_at + 60_000, {TOTALISER_KEY: {"segment_totals_json": "{}"}}
        ),
        _totals_msg(260, closed_at + 900_000, END_KIND, {"total_volume": END_GRAND}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    _windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    column = _assert_column_ends_on_summary(summary, rows)
    assert [round(v, 2) for v in column] == [6.51, 40.11]


@pytest.mark.asyncio
async def test_kind_absent_from_totals_map_is_not_the_frozen_figure():
    # Same, but the map is well-formed and simply omits this kind.
    app = _make_app()
    closed_at = END_TS - 7_200_000
    _close_segment_at(app, closed_at)
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(200, 1788840960000, FIRST_KIND, {"flow_value": 12.5}),
        _segment_record(250, closed_at, KIND, START_TS - 86_400_000),
        FakeMessage(
            255,
            closed_at + 60_000,
            {
                TOTALISER_KEY: {
                    "segment_totals_json": json.dumps({"None": NONE_KIND_VOLUME})
                }
            },
        ),
        _totals_msg(260, closed_at + 900_000, END_KIND, {"total_volume": END_GRAND}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    _windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    column = _assert_column_ends_on_summary(summary, rows)
    assert [round(v, 2) for v in column] == [6.51, 40.11]


@pytest.mark.asyncio
async def test_no_synthetic_zero_closing_row_in_an_empty_window():
    # A closed window with no totals message of its own, whose post-close
    # republish lands BELOW the baseline (the odometer restarted), so the
    # period figure clamps to 0.0. A 0.00 row here states the pipeline pumped
    # nothing all window; a blank cell is the honest answer.
    app = _make_app()
    closed_at = END_TS - 7_200_000
    _close_segment_at(app, closed_at)
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _segment_record(250, closed_at, KIND, START_TS - 86_400_000),
        _totals_msg(260, closed_at + 900_000, 0.5, {"total_volume": 0.5}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    _summary = app._volume_summary_rows(snapshots)
    _windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    assert _pipeline_column(rows) == []


@pytest.mark.asyncio
async def test_reopen_inside_the_republish_interval_gets_no_closing_row():
    # A -> None (5 min) -> A, with the first post-close totals message landing
    # 14 min INTO the second window. That figure includes the second window's
    # accrual, so it is not window 1's frozen total and must not be used: the
    # scan stops at the second window's start and finds nothing.
    app = _make_app()
    a1_end = START_TS + 3_600_000
    a2_start = a1_end + 300_000
    app.api.aggregates["tag_values"][APP_KEY]["current_segment"] = {
        "kind": KIND,
        "start_ts": a2_start,
    }
    _set_messages(
        app,
        FakeMessage(
            100,
            START_TS - 3_600_000,
            {
                TOTALISER_KEY: {
                    "total_volume": BASE_GRAND,
                    "segment_totals_json": _totals(BASE_KIND),
                }
            },
        ),
        _totals_msg(150, START_TS + 1_800_000, 30.0, {"flow_value": 9.0}),
        _segment_record(160, a1_end, KIND, START_TS - 86_400_000),
        _segment_record(180, a2_start, "None", a1_end),
        _totals_msg(200, a2_start + 840_000, 50.0, {"flow_value": 9.0}),
        _totals_msg(300, END_TS - 60_000, END_KIND, {"total_volume": END_GRAND}),
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    assert windows == [(START_TS, a1_end), (a2_start, END_TS)]
    assert _closing_rows_at(rows, a1_end) == []
    # Window 1 ends on its own last sample; the equality at the end still holds.
    column = _assert_column_ends_on_summary(summary, rows)
    assert [round(v, 2) for v in column] == [2.89, 22.89, 40.11]


# --- documented limit of the column/summary agreement ----------------------
#
# Equality is claimed for a SINGLE totaliser app. This test pins the shape
# where it does not hold, so the README/docstring qualification is checked.


@pytest.mark.asyncio
async def test_second_totaliser_app_sums_into_summary_only():
    # The summary sums every app publishing the convention; the column tracks
    # the single app owning the total_volume variable (find_total_volume_ref
    # returns the first match), so with two skids the column is a subset.
    app = _make_app()
    other_key = "petronash_pump_controller_2"
    app.api.aggregates["tag_values"][other_key] = {
        "total_volume": 30.0,
        "segment_totals_json": _totals(30.0),
    }
    app.api.messages["tag_values"].extend(
        [
            FakeMessage(
                101,
                START_TS - 3_600_000,
                {
                    other_key: {
                        "total_volume": 10.0,
                        "segment_totals_json": _totals(10.0),
                    }
                },
            ),
            FakeMessage(
                301,
                END_TS - 60_000,
                {
                    other_key: {
                        "total_volume": 30.0,
                        "segment_totals_json": _totals(30.0),
                    }
                },
            ),
        ]
    )

    snapshots = await app._period_snapshots(START_TS, END_TS)
    summary = app._volume_summary_rows(snapshots)
    _windows, rows, _refs = await app._build_report(KIND, START_TS, END_TS, snapshots)

    assert list(snapshots) == [TOTALISER_KEY, other_key]
    period_total = dict(summary)[f"{KIND} (report period)"]
    # 40.11 from skid 1 + 20.00 from skid 2.
    assert round(period_total, 2) == 60.11
    ordered = sorted(rows, key=lambda r: r["timestamp_utc"])
    column = [r["values"][report_lib.PIPELINE_TOTAL_COL] for r in ordered]
    # The column is skid 1's contribution alone.
    assert [round(v, 2) for v in column] == [6.51, 40.11]
    assert column[-1] < period_total


# --- report filename device name -------------------------------------------


def test_device_name_comes_from_own_device_map_entry():
    app = _make_app()
    app.agent_id = 162752502318562052
    app.received_deployment_config = {
        "DEVICE_MAP": {
            "162752502318562052": {
                "display_name": "Solar Skid 11",
                "name": "doovit-a0418e",
            }
        }
    }
    assert app._device_name() == "Solar Skid 11"

    # Blank display name -> the device's machine name.
    app.received_deployment_config["DEVICE_MAP"]["162752502318562052"][
        "display_name"
    ] = " "
    assert app._device_name() == "doovit-a0418e"


def test_device_name_falls_back_to_app_name():
    app = _make_app()
    app.agent_id = 1
    assert app._device_name() == "data_report_segmenter"  # no deployment config
    app.received_deployment_config = {"DEVICE_MAP": {"2": {"display_name": "X"}}}
    assert app._device_name() == "data_report_segmenter"  # not our device
