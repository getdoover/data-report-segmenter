/**
 * Data Report Segmenter cloud widget.
 *
 * Tracks a single always-open timeline segment for its install:
 *  - reads config from `deployment_config.applications[appKey]`
 *    (segment_kinds / show_none_segment / segments_label);
 *  - reads the open segment from `tag_values[appKey].current_segment`;
 *  - switches kinds by sending the `switch_segment` RPC on `dv-rpc`
 *    (doover-js useSendRpc → pydoover RPCManager wire shape — see README);
 *  - generates CSV reports by firing `generate_report` and watching the
 *    `segment_reports` channel for the job message (never blocks on the RPC).
 *
 * Auth, REST base URL and the gateway WebSocket are all inherited from the
 * host's DooverProvider/getDooverClient singleton across the shared-singleton
 * MF boundary — nothing to configure here.
 */
interface UiRemoteComponent {
    /** This install's app key — its config block lives under it. */
    app_key?: string;
}
interface UiElementProps {
    ui?: {
        id?: string;
    } | null;
    /** Host emotion/MUI theme. */
    theme?: unknown;
}
interface WidgetProps {
    uiElement?: UiRemoteComponent;
    ui_element_props?: UiElementProps;
}
declare const DataReportSegmenterWidget: (props: WidgetProps) => import("react").JSX.Element;
export default DataReportSegmenterWidget;
