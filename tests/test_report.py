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
                        "currentValue": "$tag.app().value:number:null",
                    },
                    "pump_block": {
                        "type": "uiSubmodule",
                        "children": {
                            "pressure": {
                                "type": "uiVariable",
                                "varType": "float",
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
        report_lib.get_by_keys(TAG_MSG, ("flow_sensor_1",))
        is TAG_MSG["flow_sensor_1"]
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
    refs = [VariableRef("a.b", ("a", "b"))]
    assert report_lib.extract_row_values({"other": {"x": 1}}, refs) == {}


# --- CSV assembly --------------------------------------------------------


def _refs(*cols):
    return [VariableRef(c, ("app", c)) for c in cols]


def test_render_csv_header_and_ordering():
    refs = _refs("app.x", "app.y")
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
    out = report_lib.render_csv(refs, rows).decode("utf-8")
    lines = out.splitlines()
    assert lines[0] == "timestamp_utc,segment_kind,app.x,app.y"
    # rows sorted ascending by timestamp
    assert lines[1].startswith("2026-01-01T00:00:00+00:00,A,1,10")
    assert lines[2].startswith("2026-01-02T00:00:00+00:00,A,2,20")


def test_render_csv_sparse_cells_blank():
    refs = _refs("app.x", "app.y")
    rows = [
        {
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "segment_kind": "A",
            "values": {"app.x": 1},
        },  # app.y missing
    ]
    out = report_lib.render_csv(refs, rows).decode("utf-8")
    # trailing empty cell for the missing app.y
    assert out.splitlines()[1] == "2026-01-01T00:00:00+00:00,A,1,"


def test_render_csv_no_rows():
    refs = _refs("app.x")
    out = report_lib.render_csv(refs, []).decode("utf-8")
    assert out.splitlines() == ["timestamp_utc,segment_kind,app.x"]


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
