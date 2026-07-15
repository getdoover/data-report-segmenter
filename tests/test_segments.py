"""Unit tests for the pure segment-timeline logic (segments.py)."""

from data_report_segmenter import segments as seg


# --- kind rules / options ------------------------------------------------


def test_valid_kinds_includes_none():
    assert seg.valid_kinds(["A", "B"]) == {"A", "B", "None"}
    assert seg.valid_kinds([]) == {"None"}


def test_derive_options_hides_none_by_default():
    assert seg.derive_kind_options(["A", "B"], show_none=False) == ["A", "B"]


def test_derive_options_shows_none_when_enabled():
    assert seg.derive_kind_options(["A", "B"], show_none=True) == ["None", "A", "B"]


def test_derive_options_empty_kinds_forces_none_regardless():
    assert seg.derive_kind_options([], show_none=False) == ["None"]
    assert seg.derive_kind_options([], show_none=True) == ["None"]


def test_default_open_kind_is_none():
    assert seg.default_open_kind([]) == "None"
    assert seg.default_open_kind(["A"]) == "None"


# --- switch instant clamping ---------------------------------------------


def test_clamp_none_client_ts_uses_now():
    assert seg.clamp_switch_instant(None, current_start_ts=100, now_ts=500) == 500


def test_clamp_future_client_ts_clamped_to_now():
    assert seg.clamp_switch_instant(9999, current_start_ts=100, now_ts=500) == 500


def test_clamp_past_client_ts_clamped_to_segment_start():
    # Can't open a new segment before the current one started.
    assert seg.clamp_switch_instant(50, current_start_ts=100, now_ts=500) == 100


def test_clamp_valid_client_ts_passes_through():
    assert seg.clamp_switch_instant(300, current_start_ts=100, now_ts=500) == 300


# --- open / close records ------------------------------------------------


def test_make_open_segment_shape():
    assert seg.make_open_segment("A", 123) == {"kind": "A", "start_ts": 123}


def test_close_segment_shape():
    opened = {"kind": "A", "start_ts": 100}
    closed = seg.close_segment(opened, 400)
    assert closed == {
        "record_type": "segment",
        "kind": "A",
        "start_ts": 100,
        "end_ts": 400,
    }


# --- switch transition (compose clamp + close + open) --------------------


def _switch(current, kind, client_ts, now_ts, valid):
    """Mirror the processor's switch_segment decision logic for testing."""
    if kind not in valid:
        return "INVALID", None, None
    if kind == current["kind"]:
        return "NOOP", current, None
    switch_ts = seg.clamp_switch_instant(client_ts, current["start_ts"], now_ts)
    closed = seg.close_segment(current, switch_ts)
    new = seg.make_open_segment(kind, switch_ts)
    return "SWITCH", new, closed


def test_switch_same_kind_is_noop():
    current = {"kind": "A", "start_ts": 100}
    result, new, closed = _switch(current, "A", 300, 500, {"A", "None"})
    assert result == "NOOP"
    assert new == current
    assert closed is None


def test_switch_invalid_kind():
    current = {"kind": "A", "start_ts": 100}
    result, _, _ = _switch(current, "Z", 300, 500, {"A", "None"})
    assert result == "INVALID"


def test_switch_closes_and_opens_with_clamped_ts():
    current = {"kind": "None", "start_ts": 100}
    result, new, closed = _switch(current, "A", 300, 500, {"A", "None"})
    assert result == "SWITCH"
    assert new == {"kind": "A", "start_ts": 300}
    assert closed["end_ts"] == 300
    assert closed["start_ts"] == 100
    assert closed["kind"] == "None"


# --- window intersection -------------------------------------------------


def test_windows_single_closed_segment_fully_inside():
    closed = [{"kind": "A", "start_ts": 200, "end_ts": 300}]
    assert seg.compute_windows(closed, None, "A", 100, 500) == [(200, 300)]


def test_windows_clamped_to_range():
    closed = [{"kind": "A", "start_ts": 50, "end_ts": 600}]
    assert seg.compute_windows(closed, None, "A", 100, 500) == [(100, 500)]


def test_windows_ignores_other_kinds():
    closed = [
        {"kind": "A", "start_ts": 100, "end_ts": 200},
        {"kind": "B", "start_ts": 200, "end_ts": 300},
    ]
    assert seg.compute_windows(closed, None, "A", 0, 1000) == [(100, 200)]


def test_windows_discontinuous():
    closed = [
        {"kind": "A", "start_ts": 100, "end_ts": 200},
        {"kind": "B", "start_ts": 200, "end_ts": 300},
        {"kind": "A", "start_ts": 300, "end_ts": 400},
    ]
    # Two separate A windows with a gap where B was active.
    assert seg.compute_windows(closed, None, "A", 0, 1000) == [(100, 200), (300, 400)]


def test_windows_include_open_segment_clamped_to_end():
    open_seg = {"kind": "A", "start_ts": 400}
    # Open segment has no end; it is treated as running to end_ts (450).
    assert seg.compute_windows([], open_seg, "A", 0, 450) == [(400, 450)]


def test_windows_open_segment_wrong_kind_excluded():
    open_seg = {"kind": "B", "start_ts": 400}
    assert seg.compute_windows([], open_seg, "A", 0, 450) == []


def test_windows_closed_plus_open_sorted():
    closed = [{"kind": "A", "start_ts": 100, "end_ts": 200}]
    open_seg = {"kind": "A", "start_ts": 400}
    assert seg.compute_windows(closed, open_seg, "A", 0, 500) == [
        (100, 200),
        (400, 500),
    ]


def test_windows_zero_length_overlap_excluded():
    # A closed segment ending exactly at the range start contributes nothing.
    closed = [{"kind": "A", "start_ts": 0, "end_ts": 100}]
    assert seg.compute_windows(closed, None, "A", 100, 500) == []


# --- end-boundary-crossing segment (fetch-side gap) -----------------------
#
# Closed-segment messages are timestamped at their END, so a segment that
# starts inside the report range but closes after end_ts is NOT returned by
# a before=end_ts fetch. select_boundary_crossing_segment picks the (at most
# one) such record out of a forward scan past end_ts; compute_windows then
# clamps it.

# Coordinator's concrete scenario, in epoch-ms-like ints:
# A[1000->1100], B[1100->1300], C open from 1300; report range [1030, 1200].
_A = {"record_type": "segment", "kind": "A", "start_ts": 1000, "end_ts": 1100}
_B = {"record_type": "segment", "kind": "B", "start_ts": 1100, "end_ts": 1300}


def test_crossing_segment_selected_when_started_inside_range():
    # B's message (ts 1300) lies beyond end_ts=1200; forward scan finds it.
    assert seg.select_boundary_crossing_segment([_B], 1200) == _B


def test_crossing_segment_picks_earliest_candidate():
    later = {"record_type": "segment", "kind": "C", "start_ts": 1300, "end_ts": 1500}
    assert seg.select_boundary_crossing_segment([later, _B], 1200) == _B


def test_crossing_segment_none_when_first_starts_at_or_after_end():
    # The earliest record past end_ts starts exactly at end_ts -> no overlap,
    # and contiguity means no later record can cross either.
    at_boundary = {
        "record_type": "segment",
        "kind": "B",
        "start_ts": 1200,
        "end_ts": 1400,
    }
    assert seg.select_boundary_crossing_segment([at_boundary], 1200) is None


def test_crossing_segment_no_candidates():
    assert seg.select_boundary_crossing_segment([], 1200) is None


def test_crossing_segment_ignores_non_segment_records():
    tag_log = {"some_tag": 42}
    assert seg.select_boundary_crossing_segment([tag_log], 1200) is None
    assert seg.select_boundary_crossing_segment([tag_log, _B], 1200) == _B


def test_windows_coordinator_boundary_scenario():
    # Report kind B over [1030, 1200]: the before=end_ts fetch returns only A;
    # the forward scan contributes B; expect B clamped to [1100, 1200].
    fetched = [_A]  # what the backward page over (1030, 1200] yields
    crossing = seg.select_boundary_crossing_segment([_B], 1200)
    assert crossing is not None
    closed = fetched + [crossing]
    open_seg = {"kind": "C", "start_ts": 1300}
    assert seg.compute_windows(closed, open_seg, "B", 1030, 1200) == [(1100, 1200)]


def test_windows_boundary_scenario_without_crossing_record_loses_window():
    # Regression guard documenting the original bug: without the crossing
    # record the B window silently vanishes.
    assert (
        seg.compute_windows([_A], {"kind": "C", "start_ts": 1300}, "B", 1030, 1200)
        == []
    )
