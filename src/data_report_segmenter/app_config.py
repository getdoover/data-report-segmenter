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
    show_timeline_chart = config.Boolean(
        "Show Timeline Chart",
        default=True,
        description="Show the segment timeline Gantt chart + range selector in the widget.",
    )

    # --- processor plumbing ---------------------------------------------
    # dv_proc_subscriptions MUST include "dv-rpc" or no RPC (switch_segment /
    # generate_report) ever reaches the processor: the widget posts both RPCs
    # on the dv-rpc channel (doover-js useSendRpc), so the processor only wakes
    # for them if subscribed to it.
    #
    # required=True is LOAD-BEARING, not cosmetic: the processor deployer only
    # emits the SNS subscription bindings for a subscription field that exports
    # as a *required* array (`type: "array"`, `x-required: true`) — matching the
    # working doover-agents app. A bare `default=[...]` makes the field nullable
    # (`type: ["array","null"]`, `x-required: false`), which the deployer SKIPS,
    # so no trigger is ever wired and the lambda is never invoked. Keep both:
    # required=True restores the wired shape, default pre-fills "dv-rpc" so fresh
    # installs work out of the box. The app uses no other channel subscription
    # (ui_state / tag_values are read on demand).
    subscriptions = ManySubscriptionConfig(default=["dv-rpc"], required=True)
    # dv_proc_schedules / dv_proc_timezone: reserved for future scheduled
    # reports; present now, unused in v1.
    schedules = ScheduleConfig()
    timezone = TimezoneConfig()


def export():
    DataReportSegmenterConfig.export(
        Path(__file__).parents[2] / "doover_config.json",
        "data_report_segmenter",
    )
