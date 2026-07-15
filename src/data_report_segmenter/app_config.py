from pathlib import Path

from pydoover import config
from pydoover.processor.config import (
    ManySubscriptionConfig,
    ScheduleConfig,
    TimezoneConfig,
)


class DataReportSegmenterConfig(config.Schema):
    """Deployment config for the Data Report Segmenter.

    Display names are chosen so they sanitise (lowercase, spaces -> ``_``,
    punctuation stripped) to the exact runtime keys the widget reads back:
    ``segment_kinds``, ``show_none_segment``, ``segments_label``.
    """

    # --- app-specific fields --------------------------------------------
    segment_kinds = config.Array(
        "Segment Kinds",
        element=config.String("Kind"),
        default=[],
        description=(
            "Operator-defined segment-kind labels selectable in the widget. "
            'The built-in "None" kind is always implicit and is NOT listed here.'
        ),
    )
    show_none_segment = config.Boolean(
        "Show None Segment",
        default=False,
        description=(
            'Whether "None" appears in the widget dropdown. Ignored (treated as '
            "true) when Segment Kinds is empty."
        ),
    )
    segments_label = config.String(
        "Segments Label",
        default="Segment",
        description="The word rendered before the current kind, e.g. 'Segment: Pipeline A'.",
    )

    # --- processor plumbing ---------------------------------------------
    # dv_proc_subscriptions MUST include "dv-rpc" in every install's
    # deployment config or no RPC (switch_segment / generate_report) ever
    # fires. See README + simulators/deployment_config.json.
    subscriptions = ManySubscriptionConfig()
    # dv_proc_schedules / dv_proc_timezone: reserved for future scheduled
    # reports; present now, unused in v1.
    schedules = ScheduleConfig()
    timezone = TimezoneConfig()


def export():
    DataReportSegmenterConfig.export(
        Path(__file__).parents[2] / "doover_config.json",
        "data_report_segmenter",
    )
