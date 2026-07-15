# data-report-segmenter — widget

Module Federation remote component (rsbuild + rspack) for the Doover cloud UI.
Mirrors the `petronash-hmi/widget` build skeleton. It tracks a single
always-open timeline **segment** for its install and generates CSV reports over
segment windows.

- MF scope (`name`): `DataReportSegmenterWidget`
- Exposed module: `./DataReportSegmenterWidget`
- Built artifact (single file, served as one channel attachment):
  `widget/assets/DataReportSegmenterWidget.js`

The rsbuild `name` / `exposes` key MUST stay in sync with the `scope` / `module`
fields of the `uiRemoteComponent` in `doover_config.json` (owned by the
processor/scaffold side).

## Commands

```bash
npm install            # install deps
npm run build          # rsbuild build -> assets/DataReportSegmenterWidget.js
npm run watch          # rsbuild build --watch --mode development
npm run serve          # serve -s assets/ -l 8003  (host the built asset)
npm test               # node --test tests/*.test.mjs  (pure-logic unit tests)
```

The `ConcatenatePlugin` flattens every MF chunk emitted under `./dist` into the
one servable `assets/DataReportSegmenterWidget.js` (the platform serves a widget
as a single channel attachment, so it must stay one file).

## Local iteration flow

(from `.planning/research/widget-contract.md` §6)

1. `npm run watch` to rebuild on change, and `npm run serve` to host the built
   asset at `http://localhost:8003/DataReportSegmenterWidget.js`.
2. Point a running (staging) customer-site's remote-component URL override at
   that local URL. `interpreterV2/elements/remoteComponent/uiRemoteComponent.tsx`
   treats any `componentUrl` starting with `http` / containing `localhost` as a
   **direct script URL** (scope defaults to the filename), so overriding
   `dv_widget_url` with `http://localhost:8003/DataReportSegmenterWidget.js`
   loads the local build without republishing.
3. The host injects the remote base URLs via
   `window.dooverCustomerSite_remoteUrl` / `window.dooverAdminSite_remoteUrl`, so
   the local widget still resolves its `customer_site/*` imports against the
   staging host it is loaded inside.
4. Auth, REST base URL and the gateway WebSocket are inherited from the host's
   `DooverProvider` / `getDooverClient` singleton across the shared-singleton MF
   boundary — nothing to configure in the widget.

To publish for real, the processor/scaffold side runs `doover app publish`
(`build_widget_command` + `widget:` fields upload `assets/*.js`).

> **Deployment prerequisite (screams from the contract):** the install's
> `deployment_config.dv_proc_subscriptions` MUST include **`dv-rpc`** or the
> processor never receives `switch_segment` / `generate_report` and the widget
> silently does nothing.

## What it reads / writes

| Purpose | Channel | Hook | Shape |
|---|---|---|---|
| Config | `deployment_config` | `useAgentChannel` | `applications[appKey]` → `segment_kinds`, `show_none_segment`, `segments_label` |
| Open segment | `tag_values` | `useAgentChannel` | `[appKey].current_segment = { kind, start_ts }` |
| Switch kind | `dv-rpc` | `useSendRpc` | `switch_segment` `{ kind, client_ts }` |
| Generate report | `dv-rpc` | `useSendRpc` | `generate_report` `{ kind, start_ts, end_ts }` (response ignored) |
| Report jobs | `segment_reports` | `useChannelMessages` | `record_type:"report"` lifecycle + attachment CSV |

Pure logic (option derivation, config/segment extraction, RPC payloads, report
matching, filename/date helpers, theme tokens) lives in `src/lib/` and is
unit-tested with `node --test` (no browser). Presentation components in
`src/components/` are deliberately small/swappable — the UX will be iterated on.

## Wire-shape decision — `useSendRpc` vs manual `useSendMessage`

**Decision: use doover-js `useSendRpc` directly.** Its posted wire shape is
accepted by pydoover's `RPCManager` unchanged; the manual `useSendMessage` +
`useChannelSubscription` fallback is **not needed**.

**Evidence.** `useSendRpc` calls `client.rpc.send(identifier, { method, request,
app_key })`
(`node_modules/doover-js/dist/react/useSendRpc.js:109-123`), and the dispatcher
posts the request as:

```js
// node_modules/doover-js/dist/rpc/rpc-dispatcher.js:32-38
this.messages.postMessage(agentId, channelName, {
  data: { type: "rpc", ...request },   // => { type:"rpc", method, request, app_key? }
});
```

pydoover's `RPCManager._handle_request` reads **only** `type` (must be `"rpc"`),
`method`, `app_key` (optional; if present must match the processor's app_key),
and `request` — it never reads `status` or `response` from the incoming request
(`~/pydoover/pydoover/rpc.py:307-338`). So the two extra keys pydoover's own
`RPCManager.call()` adds (`status:{code:"sent"}`, `response:{}`,
`rpc.py:248-254`) are cosmetic; their absence in the doover-js message is
irrelevant. Request path ✔.

The **response** path also lines up. pydoover replies via `update_message`
(PATCH-merge, not replace) with `{ status:{code:"success"...}, response:{...} }`
(`rpc.py:422-430`), so the original `type`/`method`/`request` fields survive the
merge. The dispatcher subscribes with `onMessageUpdate` and routes on the
updated message, requiring `status` + `method` + `request` to be present
(`rpc-dispatcher.js:5-11, 82-112`) — all present — then resolves on
`status.code === "success"` with `msg.data.response` (or rejects on `"error"`).
Response path ✔.

**Consequences we rely on:**

- We pass `app_key: <install appKey>` on both RPCs so pydoover's app_key filter
  (`rpc.py:324-332`) routes them to the right processor.
- This build of `useSendRpc` passes **no `timeoutMs`** to `rpc.send`
  (`useSendRpc.js:121-123`), so there is no client-side RPC timeout — the promise
  stays pending until a terminal status arrives. For `switch_segment` that
  resolves quickly; for `generate_report` we **do not await the RPC at all** —
  per the contract we watch `segment_reports` for the job message reaching
  Complete/Failed (30 s JS wait would otherwise lose to a 300 s lambda). The
  switch flow additionally uses a ~15 s safety timeout to re-enable the dropdown.

## Open items for verification (against a live host)

- Whether a non-admin customer-site user's inherited client is permitted to
  post to `dv-rpc` (RBAC / `ChannelMessageWrite`) — writes from a widget have no
  in-repo precedent (`widget-contract.md` "Open questions").
- Cross-origin auto-download: the S3 signed URL is cross-origin, so the anchor
  `download` attribute may be ignored by the browser (it still opens the file).
  A manual "Download CSV" button is always shown as the reliable path.
- That `segment_reports` job messages carry the exact `record_type:"report"` +
  `kind`/`start_ts`/`end_ts` params the matcher keys on (processor-owned
  contract) — confirm against a real generated report.
- Live-host confirmation that `useRemoteParams().agentId` (or
  `ui_element_props.ui.id`) is populated when the widget mounts.
