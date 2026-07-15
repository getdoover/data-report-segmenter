import { useEffect, useMemo, useState } from "react";

import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";

import { useAgentChannel, useChannelMessages } from "doover-js/react";

import { extractAppConfig, extractCurrentSegment } from "./lib/config.ts";
import {
  deriveReportOptions,
  deriveSegmentOptions,
} from "./lib/options.ts";
import { sortReportsDesc, type ReportMessage } from "./lib/reports.ts";
import { resolveTheme } from "./lib/theme.ts";
import {
  DEFAULT_APP_KEY,
  REPORTS_CHANNEL,
  type ReportRecord,
} from "./lib/types.ts";
import { useSwitchSegment } from "./hooks/useSwitchSegment.ts";
import { useGenerateReport } from "./hooks/useGenerateReport.ts";
import { SegmentHeader } from "./components/SegmentHeader.tsx";
import { GenerateReportPanel } from "./components/GenerateReportPanel.tsx";
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
  const { messages: reportMessages } = useChannelMessages<ReportRecord>(
    { agentId, channelName: REPORTS_CHANNEL },
    { limit: 25, liveUpdates: true },
  );

  const config = useMemo(
    () => extractAppConfig(deploymentConfig, appKey),
    [deploymentConfig, appKey],
  );
  const current = useMemo(
    () => extractCurrentSegment(tagValues, appKey),
    [tagValues, appKey],
  );

  const switchOptions = useMemo(
    () => deriveSegmentOptions(config.segmentKinds, config.showNone, current.kind),
    [config.segmentKinds, config.showNone, current.kind],
  );
  const reportOptions = useMemo(
    () => deriveReportOptions(config.segmentKinds, current.kind),
    [config.segmentKinds, current.kind],
  );

  const messages = reportMessages as ReportMessage[];
  const recentReports = useMemo(() => sortReportsDesc(messages), [messages]);

  const switcher = useSwitchSegment(agentId, appKey, current.kind);
  const reporter = useGenerateReport(agentId, appKey, messages);

  const [showReport, setShowReport] = useState(false);
  const now = Date.now();

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

      <div style={{ marginTop: 10 }}>
        <Button
          tokens={tokens}
          variant="ghost"
          onClick={() => setShowReport((v) => !v)}
        >
          {showReport ? "Hide Report" : "Generate Report"}
        </Button>
      </div>

      {showReport && (
        <GenerateReportPanel
          tokens={tokens}
          options={reportOptions}
          active={reporter.active}
          fireError={reporter.fireError}
          onGenerate={reporter.generate}
        />
      )}

      <ReportList tokens={tokens} reports={recentReports} />
    </Card>
  );
}

const DataReportSegmenterWidget = (props: WidgetProps) => (
  <RemoteComponentWrapper>
    <DataReportSegmenterInner {...props} />
  </RemoteComponentWrapper>
);

export default DataReportSegmenterWidget;
