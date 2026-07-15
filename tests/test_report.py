"""Unit tests for the pure report-building logic (report.py)."""

from data_report_segmenter import report as report_lib
from data_report_segmenter.report import VariableRef


# A realistic ui_state aggregate (crib shape from data-plane.md §3):
#   {"state": {"children": {<app_key>: {"children": {<var>: {...}}}}}}
# - "flow_sensor_1" has a top-level numeric var + a nested submodule var
# - "level_sensor_1" has an integer var and a text (non-numeric) var and a
#   currentValue that is an unresolved "$"-tag reference (live tag ref)
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
                        "currentValue": 12.5,
                    },
                    "pump_block": {
                        "type": "uiSubmodule",
                        "children": {
                            "pressure": {
                                "type": "uiVariable",
                                "varType": "float",
                                "currentValue": 3.2,
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
                        "currentValue": 7,
                    },
                    "status_text": {
                        "type": "uiVariable",
                        "varType": "text",
                        "currentValue": "OK",
                    },
                    "bound_value": {
                        "type": "uiVariable",
                        "varType": "float",
                        "currentValue": "$level_sensor_1.raw",
                    },
                },
            },
            "data_report_segmenter_1": {
                "type": "uiApplication",
                "children": {
                    "current_kind": {
                        "type": "uiVariable",
                        "varType": "float",
                        "currentValue": 1.0,
                    }
                },
            },
        }
    }
}


# --- variable-tree walk --------------------------------------------------


def test_walk_collects_numeric_vars_including_submodule():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    cols = [r.column for r in refs]
    # float + integer vars, including the nested submodule var; sorted by column
    assert cols == [
        "flow_sensor_1.flow_rate",
        "flow_sensor_1.pump_block.pressure",
        "level_sensor_1.bound_value",
        "level_sensor_1.level_count",
    ]


def test_walk_excludes_own_subtree():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    assert all(not r.column.startswith("data_report_segmenter_1") for r in refs)


def test_walk_excludes_text_vars():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    assert "level_sensor_1.status_text" not in [r.column for r in refs]


def test_walk_field_paths():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    by_col = {r.column: r.field_path for r in refs}
    assert (
        by_col["flow_sensor_1.pump_block.pressure"]
        == "state.children.flow_sensor_1.children.pump_block.children.pressure.currentValue"
    )


def test_walk_empty_state():
    assert report_lib.walk_numeric_variables({}, "x") == []
    assert report_lib.walk_numeric_variables({"state": {}}, "x") == []


# --- value extraction ----------------------------------------------------


def test_get_by_path():
    assert (
        report_lib.get_by_path(UI_STATE, "state.children.flow_sensor_1")
        is UI_STATE["state"]["children"]["flow_sensor_1"]
    )
    assert report_lib.get_by_path(UI_STATE, "state.nope.here") is None


def test_is_numeric():
    assert report_lib.is_numeric(1)
    assert report_lib.is_numeric(1.5)
    assert not report_lib.is_numeric(True)  # bool excluded
    assert not report_lib.is_numeric("1.5")
    assert not report_lib.is_numeric(None)


def test_extract_row_values_keeps_only_numerics():
    refs = report_lib.walk_numeric_variables(UI_STATE, "data_report_segmenter_1")
    values = report_lib.extract_row_values(UI_STATE, refs)
    # bound_value is a "$"-tag reference (non-numeric) -> dropped (TODO-verify)
    assert values == {
        "flow_sensor_1.flow_rate": 12.5,
        "flow_sensor_1.pump_block.pressure": 3.2,
        "level_sensor_1.level_count": 7,
    }


def test_extract_row_values_missing_message_fields():
    refs = [VariableRef("a.b", "state.children.a.children.b.currentValue")]
    assert report_lib.extract_row_values({"state": {"children": {}}}, refs) == {}


# --- CSV assembly --------------------------------------------------------


def _refs(*cols):
    return [VariableRef(c, f"state.children.{c}.currentValue") for c in cols]


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
