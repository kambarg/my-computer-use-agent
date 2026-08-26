# API design

The public surface is the FastAPI backend on port 8000. The HTML client
at `/` is one consumer of this API; anything that speaks HTTP and SSE
can be another.

JSON request and response bodies use snake_case. Timestamps are ISO-8601
with a timezone offset. Session ids are UUIDs.

The demo UI is `/`, not Swagger. Local Compose also serves `/docs` and
`/openapi.json`. Production Compose sets `ENABLE_DOCS=0`, so those
routes 404.

## Lifecycle of a run

```
POST /sessions                  → 201  { id, status: "active", ... }
GET  /sessions/{id}/events      → SSE  (keep this open)
POST /sessions/{id}/messages    → 202  { session_id, run_id }
     first prompt also starts a worker container
GET  /sessions/{id}/desktop     → 307  → noVNC (after a worker is bound)
DELETE /sessions/{id}           → 204  stops the container, drops history
```

The SSE stream stays open across runs. A second prompt on the same
session is another `POST /messages` on the same connection; a second
prompt while a run is in flight is `409`.

## Endpoints

### `GET /health`

Liveness. Answers before the database is reachable.

```json
{ "status": "ok" }
```

### `GET /`

The demo client (`frontend/index.html`). Also `/app.js` and `/style.css`.

### Sessions

#### `POST /sessions` → `201`

Body is optional.

```json
{ "title": "Dubai weather" }
```

`title` is at most 200 characters. Response:

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "active",
  "title": "Dubai weather",
  "created_at": "2026-08-26T00:00:00+00:00",
  "updated_at": "2026-08-26T00:00:00+00:00"
}
```

`status` is `active`, `running`, or `closed`. Creating a session does
not start a desktop. The first `POST .../messages` does.

#### `GET /sessions` → `200`

Query: `limit` (1–100, default 50), `offset` (default 0). Newest first.
Returns an array of the session object above.

#### `GET /sessions/{id}` → `200`

The same object. `404` if the id is unknown.

#### `DELETE /sessions/{id}` → `204`

Cancels an in-flight run, stops and removes the worker container,
deletes the row and its events. `404` if unknown.

### Prompts

#### `POST /sessions/{id}/messages` → `202`

```json
{ "prompt": "Search the weather in Dubai" }
```

`prompt` must be non-empty. Response:

```json
{
  "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "run_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"
}
```

Accepted means the run was started, not that the agent finished.
Progress arrives on the event stream.

| Status | When |
| --- | --- |
| `404` | Unknown session |
| `409` | A run is already in progress on this session (`SessionBusy`) |
| `502` | Worker unreachable, or the container failed to start (`ProvisionFailed`) |
| `503` | `MAX_WORKERS` concurrent desktops already exist. `Retry-After` is set. |

### Events

#### `GET /sessions/{id}/events` → `text/event-stream`

Replay then live tail. Resume from `?from=<seq>` (the first seq to
yield) or the `Last-Event-ID` header (the last seq already seen; the
server continues at `id + 1`).

Each frame:

```
id: 3
event: assistant_text
data: {"session_id":"...","seq":3,"ts":"...","payload":{"type":"assistant_text","text":"..."}}

```

`id` is the session `seq`. Comment keepalives (`: keepalive\n\n`) are
sent while idle so proxies do not close the socket. A subscriber that
falls behind is dropped; it reconnects and replays.

The stream does **not** close on `run_finished`. Prompt again on the
same session without reconnecting.

### Desktop

#### `GET /sessions/{id}/desktop` → `307`

Redirects to `.../desktop/vnc.html?autoconnect=1&resize=scale`. The
backend reverse-proxies HTTP and the noVNC WebSocket to the bound
worker's port 6080. That port is not published on the host.

`409` (`NoDesktop`) if the session has no worker yet — send a prompt
first. `404` if the session does not exist.

An iframe of `/sessions/{id}/desktop` is enough for the demo client.

### Screenshots

#### `GET /blobs/{key}` → image bytes

Tool results store a reference, not inline base64. `key` is a
content-addressed filename (digest plus extension). `404` if unknown.

## Event payloads

The backend persists `Event` from `shared/events.py`. Clients see the
full envelope (`session_id`, `seq`, `ts`, `payload`). `payload.type`
matches the SSE `event:` field.

| `type` | Meaning | Notable fields |
| --- | --- | --- |
| `assistant_text` | Model text | `text` |
| `assistant_thinking` | Extended-thinking block | `thinking` |
| `tool_use` | Claude requested a tool | `tool_use_id`, `name`, `input` |
| `tool_result` | Tool finished | `tool_use_id`, `output`, `error`, `screenshot` |
| `run_finished` | Loop returned; no more tool calls | |
| `run_failed` | Anthropic API error | `message`, `status_code` |
| `run_cancelled` | Cancelled from outside (session delete) | |

Screenshots on the wire to browsers are `{ "kind": "ref", "url": "/blobs/..." }`.
The worker originally sent `{ "kind": "inline", "data": "<base64>" }`;
the backend rewrites them on ingest.

## Errors

Bodies are `{"detail": "..."}`. Domain errors:

| Status | Exception | Typical cause |
| --- | --- | --- |
| `400` | | Traversal in a desktop path |
| `404` | `SessionNotFound` | Unknown session or blob |
| `409` | `SessionBusy` | Second prompt while running |
| `409` | `NoDesktop` | Desktop requested before a worker is bound |
| `422` | | Validation (bad UUID, empty prompt, overlong title) |
| `502` | `WorkerUnreachable` / `ProvisionFailed` | Worker HTTP failed, or `docker run` / health wait failed |
| `503` | `PoolExhausted` | At `MAX_WORKERS`; `Retry-After` header |

## Querying a session from the demo client

`/?session=<uuid>` selects that session (and `history.replaceState`
keeps the URL in sync). **Open in a new window** is the same URL in
another tab, which is how two concurrent usage-case windows stay on
different desktops.

## Internal worker API

Not published on the host. The backend calls it on the Compose
network at `http://cu-worker-<session-id>:8000`.

| Method | Path | Role |
| --- | --- | --- |
| `GET` | `/health` | Ready check before the session is bound |
| `POST` | `/runs` | `{ session_id, prompt }` → `{ run_id, session_id }` (`201`; `409` if already running) |
| `GET` | `/runs/{run_id}` | Status |
| `GET` | `/runs/{run_id}/events` | SSE of `WorkerEvent` (no `seq`; the backend assigns that) |
| `POST` | `/runs/{run_id}/cancel` | Best-effort cancel |

The worker runs `sampling_loop()` unpatched and maps its three
callbacks onto the event types above (`worker/runner.py`).
