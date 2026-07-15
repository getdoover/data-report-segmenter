from pathlib import Path

from pydoover import ui


class DataReportSegmenterUI(
    ui.UI,
    # Default to the top of the device page, expanded; both remain
    # per-install overridable via dv_app_position / dv_app_default_open.
    position="$config.app().dv_app_position:number:0",
    default_open="$config.app().dv_app_default_open:boolean:true",
):
    """Cloud UI: a single Module Federation remote component.

    The widget (widget/ - built to a single JS asset and uploaded via the
    ``widget:`` field in doover_config.json) renders the segment header,
    kind dropdown and Generate Report panel. ``dv_widget_url`` is injected
    into this install's deployment config by the platform on every deploy.
    """

    segmenter_widget = ui.RemoteComponent(
        "Data Report Segmenter",
        "$config.app().dv_widget_url",
        name="data_report_segmenter_widget",
        scope="DataReportSegmenterWidget",
        module="./DataReportSegmenterWidget",
        app_key="$config.app().APP_KEY",
    )


def export():
    DataReportSegmenterUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json",
        "data_report_segmenter",
    )


if __name__ == "__main__":
    export()
