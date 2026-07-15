from typing import Any


def handler(event: dict[str, Any], context):
    """AWS Lambda entry point for the Data Report Segmenter processor.

    Mirrors the dra_dashboard PRO-app handler: import lazily (so cold-start
    import cost is only paid once the Lambda is invoked) and drive one event
    to completion via ``pydoover.processor.run_app``.
    """
    from pydoover.processor import run_app

    from .application import DataReportSegmenterApp

    run_app(
        DataReportSegmenterApp(),
        event,
        context,
    )
