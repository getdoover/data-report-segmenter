"""Smoke tests: modules import, classes wire up, config/UI schemas export."""

from pydoover.config import Schema
from pydoover.ui import UI


def test_import_application():
    from data_report_segmenter.application import DataReportSegmenterApp

    assert DataReportSegmenterApp.config_cls is not None
    assert DataReportSegmenterApp.tags_cls is not None
    assert DataReportSegmenterApp.ui_cls is not None


def test_handler_entrypoint_exists():
    import data_report_segmenter

    assert callable(data_report_segmenter.handler)


def test_rpc_handlers_registered():
    from data_report_segmenter.application import DataReportSegmenterApp

    # The @handler decorator stamps methods; confirm both RPC methods exist.
    for method in ("switch_segment", "generate_report"):
        func = getattr(DataReportSegmenterApp, method)
        assert getattr(func, "_is_rpc_handler", False) is True
        assert func._rpc_method == method


def test_config_schema():
    from data_report_segmenter.app_config import DataReportSegmenterConfig

    assert issubclass(DataReportSegmenterConfig, Schema)
    schema = DataReportSegmenterConfig.to_schema()
    assert isinstance(schema, dict)
    props = schema["properties"]
    for key in ("segment_kinds", "show_none_segment", "segments_label"):
        assert key in props, f"missing config key {key}"
    # dv_proc_subscriptions is what carries the mandatory dv-rpc subscription.
    assert "dv_proc_subscriptions" in props


def test_ui_class():
    from data_report_segmenter.app_ui import DataReportSegmenterUI

    assert issubclass(DataReportSegmenterUI, UI)
