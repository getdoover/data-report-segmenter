"""Unit tests for the pure report-building logic (report.py)."""

from datetime import datetime, timezone

from data_report_segmenter import report as report_lib
from data_report_segmenter.report import VariableRef


# A realistic ui_state aggregate: NumericVariables carry their value as a
# $tag reference (never the literal), which is the location in tag_values the
# report follows to read value history.
#   {"state": {"children": {<app_key>: {"children": {<var>: {...}}}}}}
# - "flow_sensor_1" has a top-level numeric var + a nested submodule var
#   (app() resolves to the owning app even inside the submodule)
# - "level_sensor_1" has an integer var, a text (non-numeric) var, and a var
#   whose currentValue is a LITERAL (no $tag ref -> nothing to follow -> skip)
# - "data_report_segmenter_1" is our OWN subtree and must be excluded
UI_STATE = {
    "state": {
        "children": {
            "flow_sensor_1": {
                "type": "uiApplication",
                "children": {
                    "flow_rate": {
                        "type": "uiVariable",
                        "varType": "float",
                        "displayString": "Flow Rate",
                        "currentValue": "$tag.app().value:number:null",
                    },
                    "pump_block": {
                        "type": "uiSubmodule",
                        "children": {
                            "pressure": {
                                "type": "uiVariable",
                                "varType": "float",
                                # no displayString -> header falls back to the key
                                "currentValue": "$tag.app().pressure:number:0",
                            }
                        },
                    },
                },
            },
            "level_sensor_1": {
                "type": "uiApplication",
                "children": {
                    "level_count": {
                        "type": "uiVariable",
                        "varType": "integer",
                        "displayString": "Level Count",
                        "units": "%",
                        "currentValue": "$tag.app().count:number:0",
                    },
                    "status_text": {
                        "type": "uiVariable",
                        "varType": "text",
                        "currentValue": "$tag.app().status:string:OK",
                    },
                    "literal_value": {
                        "type": "uiVariable",
                        "varType": "float",
                        "currentValue": 42.0,
                    },
                },
            },
            "data_report_segmenter_1": {
                "type": "uiApplication",
                "children": {
                    "current_kind": {
                        "type": "uiVariable",
                        "varType": "float",
                        "currentValue": "$tag.app().current:number:0",
                    }
                },
            },
        }
    }
}


# A tag_values message (per-change diff) carrying the referenced tags.
TAG_MSG = {
    "flow_sensor_1": {"value": 12.5, "pressure": 3.2},
    "level_sensor_1": {"count": 7},
}


# --- variable-tree walk --------------------------------------------------


def test_walk_collects_numeric_vars_including_submodule():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    cols = [r.column for r in refs]
    # float + integer vars with a $tag ref, including the nested submodule
    # var; sorted by column. Literal-valued and text vars are excluded.
    assert cols == [
        "flow_sensor_1.flow_rate",
        "flow_sensor_1.pump_block.pressure",
        "level_sensor_1.level_count",
    ]


def test_walk_excludes_own_subtree():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    assert all(not r.column.startswith("data_report_segmenter_1") for r in refs)


def test_walk_excludes_text_vars():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    assert "level_sensor_1.status_text" not in [r.column for r in refs]


def test_walk_resolves_tag_paths():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    by_col = {r.column: r.path for r in refs}
    # app() resolved to the owning app, even inside the submodule.
    assert by_col["flow_sensor_1.flow_rate"] == ("flow_sensor_1", "value")
    assert by_col["flow_sensor_1.pump_block.pressure"] == ("flow_sensor_1", "pressure")
    assert by_col["level_sensor_1.level_count"] == ("level_sensor_1", "count")


def test_walk_uses_displaystring_as_label_with_key_fallback():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    by_col = {r.column: r.label for r in refs}
    # The header is the human displayString the operator reads in the widget...
    assert by_col["flow_sensor_1.flow_rate"] == "Flow Rate"
    assert by_col["level_sensor_1.level_count"] == "Level Count"
    # ...falling back to the variable's own key when it has no displayString.
    assert by_col["flow_sensor_1.pump_block.pressure"] == "pressure"


def test_walk_captures_units_attribute():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    by_col = {r.column: r.units for r in refs}
    # units come straight from the ui_state node when present...
    assert by_col["level_sensor_1.level_count"] == "%"
    # ...and default to "" for variables that carry none (4-20mA columns bake
    # their unit into displayString instead).
    assert by_col["flow_sensor_1.flow_rate"] == ""
    assert by_col["flow_sensor_1.pump_block.pressure"] == ""


def test_walk_skips_literal_currentvalue():
    # A numeric var whose currentValue is a literal (not a $tag ref) has no
    # tag history to follow -> excluded (tag-reference-native).
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    assert "level_sensor_1.literal_value" not in [r.column for r in refs]


def test_walk_empty_state():
    assert report_lib.walk_numeric_variables({}, "x") == []
    assert report_lib.walk_numeric_variables({"state": {}}, "x") == []


# --- tag reference resolution --------------------------------------------


def test_parse_tag_ref_app_macro():
    assert report_lib.parse_tag_ref(
        "$tag.app().value:number:null", "flow_sensor_1"
    ) == ("flow_sensor_1", "value")


def test_parse_tag_ref_no_type_or_default():
    assert report_lib.parse_tag_ref("$tag.app().value", "a") == ("a", "value")


def test_parse_tag_ref_dotted_path_and_no_app_macro():
    assert report_lib.parse_tag_ref("$tag.app().a.b:number:0", "x") == ("x", "a", "b")
    assert report_lib.parse_tag_ref("$tag.other.field:number:0", "x") == (
        "other",
        "field",
    )


def test_parse_tag_ref_non_references():
    assert report_lib.parse_tag_ref(42.0, "x") is None
    assert report_lib.parse_tag_ref("plain string", "x") is None
    assert report_lib.parse_tag_ref(None, "x") is None


# --- value extraction ----------------------------------------------------


def test_get_by_keys():
    assert (
        report_lib.get_by_keys(TAG_MSG, ("flow_sensor_1",)) is TAG_MSG["flow_sensor_1"]
    )
    assert report_lib.get_by_keys(TAG_MSG, ("flow_sensor_1", "value")) == 12.5
    assert report_lib.get_by_keys(TAG_MSG, ("flow_sensor_1", "nope")) is None
    assert report_lib.get_by_keys(TAG_MSG, ("nope", "value")) is None
    # non-dict traversal is safe
    assert report_lib.get_by_keys({"a": 5}, ("a", "b")) is None


def test_is_numeric():
    assert report_lib.is_numeric(1)
    assert report_lib.is_numeric(1.5)
    assert not report_lib.is_numeric(True)  # bool excluded
    assert not report_lib.is_numeric("1.5")
    assert not report_lib.is_numeric(None)


def test_extract_row_values_from_tag_message():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    values = report_lib.extract_row_values(TAG_MSG, refs)
    assert values == {
        "flow_sensor_1.flow_rate": 12.5,
        "flow_sensor_1.pump_block.pressure": 3.2,
        "level_sensor_1.level_count": 7,
    }


def test_extract_row_values_diff_message_partial():
    # tag_values messages are per-change diffs: a message with only one app's
    # tags yields only that app's columns; the rest are absent (blank cells).
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    values = report_lib.extract_row_values({"level_sensor_1": {"count": 9}}, refs)
    assert values == {"level_sensor_1.level_count": 9}


def test_extract_row_values_missing_message_fields():
    refs = [VariableRef("a.b", "B", ("a", "b"))]
    assert report_lib.extract_row_values({"other": {"x": 1}}, refs) == {}


# --- CSV assembly --------------------------------------------------------


def _refs(*specs):
    # Each spec is a (column, label) pair, or a bare column (label == column).
    out = []
    for spec in specs:
        col, label = spec if isinstance(spec, tuple) else (spec, spec)
        out.append(VariableRef(col, label, ("app", col)))
    return out


def test_render_csv_header_is_friendly_labels_and_ordering():
    refs = _refs(("app.x", "Flow Rate"), ("app.y", "Tank Level"))
    rows = [
        {
            "timestamp_utc": "2026-01-02T00:00:00+00:00",
            "segment_kind": "A",
            "values": {"app.x": 2, "app.y": 20},
        },
        {
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "segment_kind": "A",
            "values": {"app.x": 1, "app.y": 10},
        },
    ]
    out = report_lib.render_csv(refs, rows, segment_label="Pipeline").decode("utf-8")
    lines = out.splitlines()
    # human headers: friendly timestamp, the configured segment label, and each
    # variable's displayString (never the internal <app_key>.<var> column key).
    assert lines[0] == "Timestamp (UTC),Pipeline,Flow Rate,Tank Level"
    # rows sorted ascending by timestamp; values rounded to 2 decimals
    assert lines[1] == "2026-01-01T00:00:00+00:00,A,1.00,10.00"
    assert lines[2] == "2026-01-02T00:00:00+00:00,A,2.00,20.00"


def test_render_csv_segment_label_defaults_to_segment():
    out = report_lib.render_csv(_refs(("app.x", "Flow Rate")), []).decode("utf-8")
    assert out.splitlines() == ["Timestamp (UTC),Segment,Flow Rate"]


def test_render_csv_duplicate_labels_stay_data_correct():
    # Two distinct columns sharing a display name: the header repeats the label,
    # but each cell still maps by the unique internal column key, not the label.
    refs = _refs(("a.flow", "Flow"), ("b.flow", "Flow"))
    rows = [
        {
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "segment_kind": "A",
            "values": {"a.flow": 1, "b.flow": 2},
        },
    ]
    out = report_lib.render_csv(refs, rows, segment_label="Pipeline").decode("utf-8")
    lines = out.splitlines()
    assert lines[0] == "Timestamp (UTC),Pipeline,Flow,Flow"
    assert lines[1] == "2026-01-01T00:00:00+00:00,A,1.00,2.00"


def test_render_csv_sparse_cells_blank():
    refs = _refs(("app.x", "Flow Rate"), ("app.y", "Tank Level"))
    rows = [
        {
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "segment_kind": "A",
            "values": {"app.x": 1},
        },  # app.y missing
    ]
    out = report_lib.render_csv(refs, rows).decode("utf-8")
    # trailing empty cell for the missing app.y; present value rounded to 2 dp
    assert out.splitlines()[1] == "2026-01-01T00:00:00+00:00,A,1.00,"


# --- column header units -------------------------------------------------


def test_column_header_appends_units_when_present():
    assert (
        report_lib.column_header(VariableRef("a.x", "Tank Volume", ("a", "x"), "L"))
        == "Tank Volume (L)"
    )
    # no units -> bare label (4-20mA columns bake the unit into the label).
    assert (
        report_lib.column_header(VariableRef("a.y", "Flow (GPD)", ("a", "y")))
        == "Flow (GPD)"
    )


def test_render_csv_header_appends_units():
    refs = [
        VariableRef("a.level", "Level", ("a", "level"), "%"),
        VariableRef("a.vol", "Tank Volume", ("a", "vol"), "L"),
        VariableRef("a.flow", "Flow (GPD)", ("a", "flow")),  # units already in label
    ]
    out = report_lib.render_csv(refs, [], segment_label="Pipeline").decode("utf-8")
    assert out.splitlines()[0] == (
        "Timestamp (UTC),Pipeline,Level (%),Tank Volume (L),Flow (GPD)"
    )


# --- volume summary ------------------------------------------------------


def test_discover_volume_totals_single_app():
    data = {
        "offline_petronash_processor_1": {
            "total_volume": 180.42,
            "segment_totals_json": '{"None": 134.3, "Pipeline A": 46.12}',
            "flow_value": 12.5,
        },
        "some_other_app": {"value": 5},  # no segment_totals_json -> ignored
    }
    grand, per_kind = report_lib.discover_volume_totals(data)
    assert grand == 180.42
    assert per_kind == {"None": 134.3, "Pipeline A": 46.12}


def test_discover_volume_totals_sums_across_apps():
    data = {
        "skid_1": {
            "total_volume": 100.0,
            "segment_totals_json": '{"Pipeline A": 60.0, "None": 40.0}',
        },
        "skid_2": {
            "total_volume": 20.0,
            "segment_totals_json": '{"Pipeline A": 15.0, "Pipeline B": 5.0}',
        },
    }
    grand, per_kind = report_lib.discover_volume_totals(data)
    assert grand == 120.0
    assert per_kind == {"Pipeline A": 75.0, "Pipeline B": 5.0, "None": 40.0}


def test_discover_volume_totals_none_and_junk():
    assert report_lib.discover_volume_totals({}) == (None, {})
    # segment_totals_json present but unparseable, and no total_volume
    assert report_lib.discover_volume_totals({"app": {"segment_totals_json": "x"}}) == (
        None,
        {},
    )
    # non-numeric per-kind values are skipped
    data = {"app": {"segment_totals_json": '{"Pipeline A": "x", "Pipeline B": 3}'}}
    grand, per_kind = report_lib.discover_volume_totals(data)
    assert grand is None
    assert per_kind == {"Pipeline B": 3}


# --- totaliser discovery + endpoint snapshots ----------------------------


def test_totaliser_app_keys_discovers_and_sorts():
    data = {
        "skid_2": {"total_volume": 20.0, "segment_totals_json": "{}"},
        "skid_1": {"total_volume": 100.0, "segment_totals_json": "{}"},
        "flow_sensor": {"value": 5},  # no segment_totals_json -> not a totaliser
    }
    assert report_lib.totaliser_app_keys(data) == ["skid_1", "skid_2"]
    assert report_lib.totaliser_app_keys({}) == []
    assert report_lib.totaliser_app_keys("junk") == []


def test_totals_snapshot_from_block():
    grand, per_kind = report_lib.totals_snapshot_from_block(
        {
            "total_volume": 180.42,
            "segment_totals_json": '{"None": 134.3, "Pipeline A": 46.12}',
            "flow_value": 12.5,
        }
    )
    assert grand == 180.42
    assert per_kind == {"None": 134.3, "Pipeline A": 46.12}
    # missing total_volume -> grand None; non-numeric per-kind skipped
    grand, per_kind = report_lib.totals_snapshot_from_block(
        {"segment_totals_json": '{"Pipeline A": "x", "Pipeline B": 3}'}
    )
    assert grand is None
    assert per_kind == {"Pipeline B": 3}
    # non-dict block -> empty snapshot
    assert report_lib.totals_snapshot_from_block(None) == (None, {})


def test_period_volume_totals_normal_diff():
    baseline = (100.0, {"Pipeline A": 60.0, "None": 40.0})
    end = (180.0, {"Pipeline A": 110.0, "None": 70.0})
    grand, per_kind = report_lib.period_volume_totals(baseline, end)
    assert grand == 80.0
    assert per_kind == {"Pipeline A": 50.0, "None": 30.0}


def test_period_volume_totals_missing_baseline():
    # No baseline snapshot -> the whole end value counts for the period.
    grand, per_kind = report_lib.period_volume_totals(
        (None, {}), (180.0, {"Pipeline A": 110.0})
    )
    assert grand == 180.0
    assert per_kind == {"Pipeline A": 110.0}
    # end carries no grand -> grand stays None
    assert report_lib.period_volume_totals((None, {}), (None, {})) == (None, {})


def test_period_volume_totals_per_kind_negative_clamps_to_zero():
    # A retroactive repaint re-attributed volume away from Pipeline A: its per-
    # kind end < baseline, which must clamp to 0.0 rather than go negative.
    grand, per_kind = report_lib.period_volume_totals(
        (100.0, {"Pipeline A": 60.0}), (120.0, {"Pipeline A": 50.0})
    )
    assert grand == 20.0
    assert per_kind == {"Pipeline A": 0.0}


def test_period_volume_totals_grand_reset_uses_end():
    # Odometer wiped (end grand < baseline grand) -> restart-from-0: period is
    # the end value alone. Per-kind drops likewise clamp to 0.0.
    grand, per_kind = report_lib.period_volume_totals(
        (200.0, {"Pipeline A": 150.0}), (30.0, {"Pipeline A": 30.0})
    )
    assert grand == 30.0
    assert per_kind == {"Pipeline A": 0.0}


def test_merge_baseline_snapshot_fills_only_missing_keys():
    # Both keys present -> primary kept untouched (no fallback bleed-through).
    assert report_lib.merge_baseline_snapshot(
        (100.0, {"Pipeline A": 60.0}), (5.0, {"Pipeline A": 3.0})
    ) == (100.0, {"Pipeline A": 60.0})
    # Grand missing (total_volume logs only per N units) but per-kind found:
    # take the grand from the fallback, keep primary's per-kind.
    assert report_lib.merge_baseline_snapshot(
        (None, {"Pipeline A": 60.0}), (5.0, {"Pipeline A": 3.0})
    ) == (5.0, {"Pipeline A": 60.0})
    # Mirror case: per-kind missing (segment_totals older than the lookback) but
    # grand found -> take per-kind from the fallback, keep primary's grand.
    assert report_lib.merge_baseline_snapshot(
        (100.0, {}), (5.0, {"Pipeline A": 3.0})
    ) == (100.0, {"Pipeline A": 3.0})
    # Both missing -> wholly from the fallback (the earliest in-window sample).
    assert report_lib.merge_baseline_snapshot(
        (None, {}), (5.0, {"Pipeline A": 3.0})
    ) == (5.0, {"Pipeline A": 3.0})


def test_merge_baseline_snapshot_partial_fallback_still_zero():
    # Fallback also empty for a missing key -> that key stays missing (None/{}),
    # so period_volume_totals then treats the baseline as 0 for it (spec's
    # "... else 0" tail).
    assert report_lib.merge_baseline_snapshot((None, {}), (None, {})) == (None, {})
    assert report_lib.merge_baseline_snapshot((None, {"A": 1.0}), (None, {})) == (
        None,
        {"A": 1.0},
    )


def test_build_volume_summary_lists_all_kinds_with_zero_fallback():
    rows = report_lib.build_volume_summary(
        180.42,
        {"None": 134.3, "Pipeline A": 46.12},
        ["Pipeline A", "Pipeline B", "Pipeline C", "None"],
    )
    assert rows == [
        ("Grand Total Volume (report period)", 180.42),
        ("Pipeline A (report period)", 46.12),
        ("Pipeline B (report period)", 0.0),  # no data yet -> 0.0, still listed
        ("Pipeline C (report period)", 0.0),
        ("None (report period)", 134.3),
    ]


def test_build_volume_summary_blank_grand_when_absent():
    rows = report_lib.build_volume_summary(None, {}, ["Pipeline A", "None"])
    assert rows[0] == ("Grand Total Volume (report period)", "")
    assert rows[1] == ("Pipeline A (report period)", 0.0)


def test_render_csv_summary_block_precedes_table():
    refs = _refs(("app.x", "Flow"))
    rows = [
        {
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "segment_kind": "Pipeline A",
            "values": {"app.x": 12.523456},
        }
    ]
    # raw noisy floats in -> 2-decimal rounding out, in both summary and table
    summary = [
        ("Grand Total Volume (report period)", 180.42295585648148),
        ("Pipeline A (report period)", 46.127060856481485),
    ]
    out = report_lib.render_csv(
        refs, rows, segment_label="Pipeline", summary=summary
    ).decode("utf-8")
    lines = out.splitlines()
    assert lines[0] == "Grand Total Volume (report period),180.42"
    assert lines[1] == "Pipeline A (report period),46.13"
    assert lines[2] == ""  # blank separator between summary and table
    assert lines[3] == "Timestamp (UTC),Pipeline,Flow"
    assert lines[4] == "2026-01-01T00:00:00+00:00,Pipeline A,12.52"


def test_render_csv_summary_blank_grand_renders_empty():
    out = report_lib.render_csv(
        _refs(("a.x", "Flow")),
        [],
        summary=[
            ("Grand Total Volume (report period)", ""),
            ("Pipeline A (report period)", 0.0),
        ],
    ).decode("utf-8")
    lines = out.splitlines()
    assert lines[0] == "Grand Total Volume (report period),"
    assert lines[1] == "Pipeline A (report period),0.00"


# --- pipeline-total column (per-pipeline running total) ------------------


def test_find_total_volume_ref():
    refs = [
        VariableRef("app.flow", "Flow", ("app", "flow_value")),
        VariableRef("app.total", "Total Volume Pumped", ("app", "total_volume")),
    ]
    assert report_lib.find_total_volume_ref(refs) is refs[1]
    assert report_lib.find_total_volume_ref(refs[:1]) is None


def test_pipeline_total_value_reads_kind_from_segment_totals_json():
    msg = {
        "skid": {
            "flow_value": 12.5,
            "segment_totals_json": '{"None": 134.3, "Pipeline A": 46.12}',
        }
    }
    assert report_lib.pipeline_total_value(msg, "skid", "Pipeline A") == 46.12
    # a kind present in the block but with no volume yet -> 0.0
    assert report_lib.pipeline_total_value(msg, "skid", "Pipeline B") == 0.0


def test_pipeline_total_value_absent_returns_none():
    # message without segment_totals_json (a diff that didn't move it) -> blank
    assert (
        report_lib.pipeline_total_value({"skid": {"flow_value": 1}}, "skid", "A")
        is None
    )
    assert report_lib.pipeline_total_value({}, "skid", "A") is None


def test_render_csv_includes_pipeline_total_column():
    refs = [
        VariableRef("app.flow", "Flow", ("app", "flow_value")),
        VariableRef(report_lib.PIPELINE_TOTAL_COL, report_lib.PIPELINE_TOTAL_LABEL, ()),
    ]
    rows = [
        {
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "segment_kind": "Pipeline A",
            "values": {"app.flow": 12.5, report_lib.PIPELINE_TOTAL_COL: 46.127},
        }
    ]
    out = report_lib.render_csv(refs, rows, segment_label="Pipeline").decode("utf-8")
    lines = out.splitlines()
    assert lines[0] == "Timestamp (UTC),Pipeline,Flow,Total Injected Volume"
    assert lines[1] == "2026-01-01T00:00:00+00:00,Pipeline A,12.50,46.13"


def test_render_csv_pipeline_total_header_includes_units():
    # The synthetic column inherits the total_volume variable's units.
    refs = [
        VariableRef(
            report_lib.PIPELINE_TOTAL_COL, report_lib.PIPELINE_TOTAL_LABEL, (), "gal"
        ),
    ]
    out = report_lib.render_csv(refs, [], segment_label="Pipeline").decode("utf-8")
    assert out.splitlines()[0] == "Timestamp (UTC),Pipeline,Total Injected Volume (gal)"


# --- filename ------------------------------------------------------------


def test_build_report_filename_basic():
    # 2026-01-01T00:00:00Z .. 2026-01-03T00:00:00Z
    start = 1767225600000
    end = 1767398400000
    name = report_lib.build_report_filename(
        "data_report_segmenter", "Pipeline A", start, end
    )
    assert name == "data_report_segmenter_Pipeline_A_20260101-20260103.csv"


def test_build_report_filename_sanitises_kind():
    start = 1767225600000
    end = 1767225600000
    name = report_lib.build_report_filename("app", "A/B: weird*name", start, end)
    assert "/" not in name and ":" not in name and "*" not in name
    assert name.startswith("app_A_B_weird_name_")


def test_build_report_filename_empty_kind_falls_back():
    start = 1767225600000
    end = 1767225600000
    name = report_lib.build_report_filename("app", "!!!", start, end)
    assert "app_unnamed_" in name


def test_format_timestamp_utc():
    assert report_lib.format_timestamp_utc(1767225600000) == "2026-01-01T00:00:00+00:00"


# --- ms -> datetime (list_messages time bounds) ----------------------------
#
# pydoover's _to_snowflake passes ints through unchanged (treated as
# snowflake message IDs); only datetimes are converted. All list_messages
# TIME bounds must therefore go through ms_to_datetime.


def test_ms_to_datetime_is_utc_aware():
    dt = report_lib.ms_to_datetime(1767225600123)
    assert dt.tzinfo is timezone.utc


def test_ms_to_datetime_round_trip():
    ms = 1767225600123
    assert int(report_lib.ms_to_datetime(ms).timestamp() * 1000) == ms


def test_ms_to_datetime_value():
    assert report_lib.ms_to_datetime(1767225600000) == datetime(
        2026, 1, 1, tzinfo=timezone.utc
    )


def test_ms_to_datetime_agrees_with_format_timestamp_utc():
    ms = 1767225600000
    assert (
        report_lib.format_timestamp_utc(ms) == report_lib.ms_to_datetime(ms).isoformat()
    )


# --- pagination termination / cursor decision ------------------------------


def test_next_page_cursor_empty_page_terminates():
    assert report_lib.next_page_cursor([], None, 3) is None


def test_next_page_cursor_short_page_terminates():
    assert report_lib.next_page_cursor([30, 20], None, 3) is None


def test_next_page_cursor_full_first_page_returns_oldest_id():
    # First page is datetime-bounded (prev_cursor None); continue from the
    # oldest returned snowflake ID.
    assert report_lib.next_page_cursor([30, 20, 10], None, 3) == 10


def test_next_page_cursor_full_later_page_advances():
    assert report_lib.next_page_cursor([9, 8, 7], 10, 3) == 7


def test_next_page_cursor_stuck_cursor_terminates():
    # No progress: the oldest ID equals the cursor this page was fetched with.
    assert report_lib.next_page_cursor([30, 20, 10], 10, 3) is None
