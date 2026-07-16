import { useEffect, useMemo, useState } from "react";

import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";

import { useAgentChannel } from "doover-js/react";

import { extractAppConfig, extractCurrentSegment } from "./lib/config.ts";
import { deriveReportOptions, deriveSegmentOptions } from "./lib/options.ts";
import { sortReportsDesc } from "./lib/reports.ts";
import { resolveTheme } from "./lib/theme.ts";
import {
  CONTROL_BUTTON_WIDTH,
  DEFAULT_APP_KEY,
  type Timespan,
} from "./lib/types.ts";
import { DEFAULT_FETCH_WINDOW_MS, defaultTimespan } from "./lib/timeline.ts";
import { useSwitchSegment } from "./hooks/useSwitchSegment.ts";
import { useGenerateReport } from "./hooks/useGenerateReport.ts";
import { useReportsWatch } from "./hooks/useReportsWatch.ts";
import { useSegmentHistory } from "./hooks/useSegmentHistory.ts";
import { useAddSegment } from "./hooks/useAddSegment.ts";
import { SegmentHeader } from "./components/SegmentHeader.tsx";
import { TimelineSection } from "./components/TimelineSection.tsx";
import { GenerateReportPanel } from "./components/GenerateReportPanel.tsx";
import { AddSegmentPanel } from "./components/AddSegmentPanel.tsx";
import { ReportList } from "./components/ReportList.tsx";
import { Button, Card } from "./components/ui.tsx";

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
  ui?: { id?: string } | null;
  /** Host emotion/MUI theme. */
  theme?: unknown;
}

interface WidgetProps {
  uiElement?: UiRemoteComponent;
  ui_element_props?: UiElementProps;
}

function usePrefersDark(): boolean {
  const [dark, setDark] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return false;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return dark;
}

function DataReportSegmenterInner({
  uiElement,
  ui_element_props,
}: WidgetProps) {
  const params = useRemoteParams();
  const agentId = params?.agentId ?? ui_element_props?.ui?.id ?? undefined;
  const appKey = uiElement?.app_key ?? DEFAULT_APP_KEY;

  const prefersDark = usePrefersDark();
  const tokens = useMemo(
    () => resolveTheme(ui_element_props?.theme, prefersDark),
    [ui_element_props?.theme, prefersDark],
  );

  const { data: deploymentConfig } = useAgentChannel(
    agentId,
    "deployment_config",
  );
  const { data: tagValues } = useAgentChannel(agentId, "tag_values");
  // Update-aware watch: useChannelMessages alone drops MessageUpdate events,
  // which is how job messages flip Generating -> Complete/Failed. See
  // hooks/useReportsWatch.ts.
  const { messages, refetch } = useReportsWatch(agentId);

  const config = useMemo(
    () => extractAppConfig(deploymentConfig, appKey),
    [deploymentConfig, appKey],
  );
  const current = useMemo(
    () => extractCurrentSegment(tagValues, appKey),
    [tagValues, appKey],
  );

  const switchOptions = useMemo(
    () =>
      deriveSegmentOptions(config.segmentKinds, config.showNone, current.kind),
    [config.segmentKinds, config.showNone, current.kind],
  );
  const reportOptions = useMemo(
    () => deriveReportOptions(config.segmentKinds, current.kind),
    [config.segmentKinds, current.kind],
  );

  const recentReports = useMemo(() => sortReportsDesc(messages), [messages]);

  const switcher = useSwitchSegment(agentId, appKey, current.kind);
  const reporter = useGenerateReport(agentId, appKey, messages, refetch);

  const [showReport, setShowReport] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const now = Date.now();

  // Visible timeline window — the single source of truth shared by the Gantt,
  // the brush, the date picker, and (as a pre-fill) the report range.
  const [span, setSpan] = useState<Timespan>(() => defaultTimespan(Date.now()));
  const history = useSegmentHistory(
    agentId,
    appKey,
    DEFAULT_FETCH_WINDOW_MS,
    now,
  );

  // Retroactive add: on success, refetch the segment history (the add
  // deletes/recreates segment messages the live subscription can't reconcile).
  const adder = useAddSegment(agentId, appKey, history.refetch);

  return (
    <Card tokens={tokens}>
      <SegmentHeader
        tokens={tokens}
        label={config.segmentsLabel}
        currentKind={current.kind}
        startTs={current.startTs}
        options={switchOptions}
        pendingKind={switcher.pendingKind}
        disabled={switcher.isPending || !agentId}
        error={switcher.error}
        now={now}
        onSelect={switcher.switchTo}
      />

      {config.showTimeline && (
        <TimelineSection
          tokens={tokens}
          segments={history.segments}
          dataExtent={history.extent}
          span={span}
          onSpanChange={setSpan}
          now={now}
          loading={history.loading}
        />
      )}

      {/* Reports + Add toggles: centred column, equal width. */}
      <div
        style={{
          marginTop: 12,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 8,
        }}
      >
        <Button
          tokens={tokens}
          variant="primary"
          onClick={() => setShowReport((v) => !v)}
          style={{ width: CONTROL_BUTTON_WIDTH }}
        >
          {showReport ? "Hide Reports" : "Reports"}
        </Button>
        <Button
          tokens={tokens}
          variant="primary"
          onClick={() => setShowAdd((v) => !v)}
          style={{ width: CONTROL_BUTTON_WIDTH }}
        >
          {showAdd ? `Hide Add` : `Add ${config.segmentsLabel}`}
        </Button>
      </div>

      {/* Collapsible retroactive-add panel. */}
      <div
        style={{
          display: "grid",
          gridTemplateRows: showAdd ? "1fr" : "0fr",
          transition: "grid-template-rows 0.3s ease",
        }}
      >
        <div style={{ overflow: "hidden", minHeight: 0 }}>
          <AddSegmentPanel
            tokens={tokens}
            options={reportOptions}
            segmentsLabel={config.segmentsLabel}
            pending={adder.pending}
            error={adder.error}
            defaultRange={{ startTs: span.after, endTs: span.before }}
            onSave={async (kind, startTs, endTs) => {
              const ok = await adder.add(kind, startTs, endTs);
              if (ok) {
                setShowAdd(false);
              }
            }}
            onCancel={() => setShowAdd(false)}
          />
        </div>
      </div>

      {/* Collapsible reports section: generate form (left) + recent reports
          (right). Animated open/close via a 0fr<->1fr grid-row transition. */}
      <div
        style={{
          display: "grid",
          gridTemplateRows: showReport ? "1fr" : "0fr",
          transition: "grid-template-rows 0.3s ease",
        }}
      >
        <div style={{ overflow: "hidden", minHeight: 0 }}>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 12,
              alignItems: "flex-start",
            }}
          >
            <div style={{ flex: "2 1 280px", minWidth: 0 }}>
              <GenerateReportPanel
                tokens={tokens}
                options={reportOptions}
                active={reporter.active}
                fireError={reporter.fireError}
                onGenerate={reporter.generate}
                defaultRange={{ startTs: span.after, endTs: span.before }}
              />
            </div>
            <div style={{ flex: "1 1 200px", minWidth: 0 }}>
              <ReportList tokens={tokens} reports={recentReports} />
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}

const DataReportSegmenterWidget = (props: WidgetProps) => (
  <RemoteComponentWrapper>
    <DataReportSegmenterInner {...props} />
  </RemoteComponentWrapper>
);

export default DataReportSegmenterWidget;
