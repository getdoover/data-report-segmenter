# Data Report Segmenter

A Doover **cloud processor app (type PRO)** with a Module Federation widget.
It labels a single timeline into operator-chosen *segment kinds*, and generates
CSV reports of every numeric value on the device over the windows where a
chosen kind was active.

There is no hardware dependency — the app runs entirely as an always-on cloud
lambda plus a browser widget, so it works on virtual agents with no physical
device.

## ⚠️ The one thing you must get right: `dv-rpc`

The widget talks to the processor over the **`dv-rpc`** channel. A processor
only receives events for channels listed in its install's
`dv_proc_subscriptions` deployment-config field. **If `dv-rpc` is not in that
list, nothing happens** — switching kinds and generating reports both silently
do nothing.

Every install's deployment config MUST contain:

```json
"dv_proc_subscriptions": ["dv-rpc"]
```

See `simulators/deployment_config.json` for a complete sample. (Note: the
`@handler(..., channel="dv-rpc")` decorator *looks* like it subscribes, but
runtime subscription is a no-op on a processor — the deployment-config list is
the only thing that matters.)

## Segment model

- Config defines a list of **segment kinds** (strings). A built-in kind
  **"None"** always exists implicitly and is never stored in config.
- **Exactly one segment is open at all times** — no gaps, no overlaps. On the
  first deploy the open segment is `None`, starting at deploy time.
- The widget shows `"{Segments Label}: {current kind}"` plus a dropdown of
  kinds. Picking a *different* kind **closes** the current segment and **opens**
  a new one at the switch instant. Picking the *same* kind is a no-op.
- **"None"** appears in the dropdown only when `show_none_segment` is true —
  except when `segment_kinds` is empty, in which case "None" is used regardless.

### Where segment state lives

The processor is the **single authoritative writer**; the widget only sends
RPCs, never writes segment state directly.

- **Open segment** — a `current_segment` value in the **`tag_values`
  aggregate**, under this app's key:

  ```json
  "current_segment": {"kind": "None", "start_ts": 1789000000000}
  ```

  `start_ts` is an epoch-**ms** int. It is seeded idempotently (only when
  genuinely absent) on deploy and re-checked on every other invocation.

- **Closed segments** — append-only messages on the **`tag_values`** channel,
  each backdated so its own timestamp equals the segment's **end**:

  ```json
  {"record_type": "segment", "kind": "Pipeline A",
   "start_ts": 1789000000000, "end_ts": 1789100000000, "author_id": 123}
  ```

  Append-only messages avoid the aggregate read-modify-write race that a
  mutable segment list would suffer (processors are not serialized per app).

## Config

| Key | Element | Default | Notes |
|---|---|---|---|
| `segment_kinds` | Array of String | `[]` | Operator-defined kind labels; "None" is implicit, not stored here |
| `show_none_segment` | Boolean | `false` | Dropdown visibility of "None"; treated as true when `segment_kinds` is empty |
| `segments_label` | String | `"Segment"` | Word rendered before the current kind |
| `dv_proc_subscriptions` | Subscriptions | — | **MUST include `dv-rpc`** (see above) |
| `dv_proc_schedules`, `dv_proc_timezone` | Schedule / Timezone | disabled | Reserved for future scheduled reports; unused in v1 |

Config display names are chosen so they sanitise to the exact runtime keys the
widget reads (`segment_kinds`, `show_none_segment`, `segments_label`).

## RPC contract

Requests are messages on `dv-rpc` in pydoover's `RPCManager` wire shape:

```json
{"type": "rpc", "method": "<m>", "request": {...},
 "status": {"code": "sent"}, "response": {}, "app_key": "<install app_key>"}
```

The response arrives as an `update_message` on the same message:
`{"status": {"code": "success"}, "response": {...}}` (or `code: "error"`).

### `switch_segment`
Request `{"kind": "<str>", "client_ts": <ms|null>}`.

- Validates `kind ∈ segment_kinds ∪ {"None"}` (else `INVALID_KIND`).
- Switch-to-same-kind is an idempotent no-op (still success).
- Effective switch instant = `client_ts` clamped to
  `[current_segment.start_ts, now]`, or `now` when `client_ts` is null.
- Closes the current segment (backdated message) and opens the new one
  (aggregate).
- Response: `{"current_segment": {...}}`.

### `generate_report`
Request `{"kind": "<str>", "start_ts": <ms>, "end_ts": <ms>}`.

- Creates the job message on `segment_reports` **first**, then generates, then
  updates the job to a terminal status.
- Response `{"message_id": <id>, "channel": "segment_reports"}` — **best-effort
  only.** The RPC caller times out after 30 s while the lambda has up to 300 s,
  so the widget must track completion via the `segment_reports` channel, not the
  RPC response.

## Report semantics

- **Windows** = closed-segment messages of the chosen `kind` intersected with
  `[start_ts, end_ts]`, plus the open segment if it matches (clamped to
  `end_ts`). Partial overlaps are clamped; discontinuous windows are expected.
- **Variables** = walk the `ui_state` aggregate
  `state.children.<app_key>.children.*` recursively (including submodules),
  collecting nodes with `type == "uiVariable"` and `varType in ("float",
  "integer")`. This app's own subtree is excluded.
- **History** = per window, page `list_messages("ui_state", after=<start>,
  before=<end>, field_names=[...])` and extract each variable's
  `...currentValue`.
  - **Known caveat (TODO-verify):** some apps publish `currentValue` as a live
    tag *reference* string rather than a literal number. When a variable's
    values are non-numeric, the true history lives in `tag_values` messages
    (`<app_key>.<tag>`). v1 keeps only literal numerics; the tag_values fallback
    is deferred to the verification phase.
- **CSV** (stdlib `csv`): header `Timestamp (UTC),<Segments Label>,<var
  displayString>,…` — the labels the operator reads in the widget, not machine
  ids (column *order* and value-matching still key off the internal
  `<app_key>.<var>` reference, so duplicate display names stay data-correct).
  One row per contributing ui_state message (sparse cells blank); ascending;
  windows concatenated. Filename
  `{app_name}_{kind}_{YYYYMMDD}-{YYYYMMDD}.csv`, sanitised.

### `segment_reports` job lifecycle

```json
create:  {"record_type": "report", "status": "Generating", "kind": k, "start_ts": s, "end_ts": e, "requested_ts": <ms>}
success: update_message(..., {"status": "Complete", "windows": <n>, "rows": <n>}, files=[File(csv)])
failure: update_message(..., {"status": "Failed", "error": "<msg>"})
```

The CSV is attached as a `File` (served via a signed S3 URL); the widget
downloads it once the job reaches `Complete`.

## Development

```bash
uv sync                              # create the venv
uv run pytest                        # run the test suite
uv run ruff check && uv run ruff format --check   # lint + format
uv run export-config && uv run export-ui          # regenerate schema into doover_config.json
./build.sh                           # produce package.zip (processor bundle)
doover app publish --profile dv2     # publish (see the doover-cli docs)
```

The widget lives under `widget/` and is built separately
(`npm --prefix widget run build`) to
`widget/assets/DataReportSegmenterWidget.js`, uploaded by `doover app publish`
via the `widget:` field in `doover_config.json`.

## Layout

```
src/data_report_segmenter/
  __init__.py       # handler(event, context) — lambda entry
  app_config.py     # config.Schema + export()
  app_ui.py         # ui.UI with one RemoteComponent + export()
  application.py     # processor: seeding, switch_segment / generate_report RPCs, report engine
  segments.py       # PURE: kind rules, switch clamping, window intersection
  report.py         # PURE: ui_state variable-tree walk, value extraction, CSV, filename
tests/              # pytest over the pure modules + import smoke test
simulators/         # sample deployment_config.json (dv-rpc subscription!)
```
