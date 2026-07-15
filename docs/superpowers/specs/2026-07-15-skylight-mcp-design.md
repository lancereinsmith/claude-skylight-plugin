# Skylight Calendar MCP Plugin — Design

**Date:** 2026-07-15
**Status:** Approved design, pending implementation plan

## Purpose

Let Claude (Claude Code, Claude Desktop, and the Telegram channel) add events to the
family's Skylight Calendar frame and read existing events, using Skylight's
unofficial API at `https://app.ourskylight.com/api`. Packaged as a Claude Code
plugin following the same conventions as `claude-qgenda-plugin`.

## Background / prior art

- Skylight has **no official public API**. The community has reverse-engineered it:
  - [TheEagleByte/skylight-api](https://github.com/TheEagleByte/skylight-api) — OpenAPI
    spec generated from HAR captures (38 endpoints). Primary endpoint reference.
  - [@eaglebyte/skylight-mcp](https://github.com/TheEagleByte/skylight-mcp) — TypeScript
    MCP server; queries events but does **not** expose event creation (our gap).
  - [ramseys1990/Skylight](https://github.com/ramseys1990/Skylight),
    [MegaTheLEGEND/skylight_calendar](https://github.com/MegaTheLEGEND/skylight_calendar) —
    Python/Home Assistant readers.
- A local copy of the OpenAPI spec is kept at `spec/skylight-openapi.yaml` for reference.

## Scope (v1)

Three MCP tools — events create + read only:

| Tool | Purpose |
|------|---------|
| `create_event` | Add a native Skylight event, optionally assigned to categories (family members) and recurring via RRULE |
| `list_events` | Query events in a date range (conflict checking before adding) |
| `get_categories` | List the frame's categories/family members with IDs and colors |

Out of scope for v1: update/delete events, chores, lists, meals, rewards.

## Architecture

```
~/Maker/skylight/
├── skylight_core.py     # SkylightClient: auth + HTTP (httpx), no MCP awareness
├── server.py            # FastMCP server: tool definitions, formatting
├── tests/               # pytest + respx (mocked); opt-in live smoke test
├── skills/skylight/     # usage skill (SKILL.md)
├── spec/                # vendored skylight-openapi.yaml
├── pyproject.toml       # uv + hatchling; deps: mcp[cli], httpx
├── justfile, package/install.sh, Dockerfile   # packaging, per qgenda plugin
└── docs/superpowers/specs/                    # this document
```

Python ≥3.11, `uv`-managed, `mcp[cli]` (FastMCP) + `httpx`. Two-file core mirrors
`claude-qgenda-plugin` (`server.py` + `*_core.py`), so packaging, justfile, and
install scripts can be copied nearly verbatim.

## API contract (from reverse-engineered spec)

Base URL: `https://app.ourskylight.com`

- **Login** — `POST /api/sessions` with `{"email", "password"}` →
  `data.attributes.token`. Token is sent on subsequent requests via the
  `Authorization` header (Basic, base64-encoded token per community usage —
  verify exact scheme during implementation).
- **List events** — `GET /api/frames/{frame_id}/calendar_events`
  with `date_min`, `date_max` (YYYY-MM-DD), `timezone`, and
  `include=categories,calendar_account`. JSON:API response; each event has
  `summary`, `starts_at`/`ends_at` (offset datetimes), `all_day`, `location`,
  `rrule`, `recurring`, `source`, and category relationships.
- **Create event** — `POST /api/frames/{frame_id}/calendar_events` with a flat
  JSON body:
  ```json
  {
    "summary": "...", "description": "...", "location": "",
    "starts_at": "2025-12-29 19:00:00+00:00", "ends_at": "2025-12-29 20:00:00+00:00",
    "timezone": "America/Chicago", "all_day": false,
    "category_ids": ["13600771"], "rrule": null, "kind": "standard",
    "invited_emails": [], "countdown_enabled": false
  }
  ```
  `calendar_account_id`/`calendar_id` are optional (used when writing through a
  linked Google account); omit for native Skylight events — verify against real
  traffic during implementation.
- **Categories** — `GET /api/frames/{frame_id}/categories` → id, `label`,
  `color`, `linked_to_profile`.

## Configuration

Environment variables (same pattern as qgenda plugin):

- `SKYLIGHT_EMAIL`, `SKYLIGHT_PASSWORD` — required.
- `SKYLIGHT_FRAME_ID` — optional. On startup the client attempts frame discovery
  (`GET /api/frames` or equivalent from the session/user payload); if discovery
  isn't possible with this API, the variable is required and the error message
  explains how to find the ID (URL in the ourskylight.com web app).
- `SKYLIGHT_TIMEZONE` — optional, default `America/Chicago`.

## Behavior details

- **Auth lifecycle:** login lazily on first call, cache token in memory. On a
  401, re-login once and retry the request; if it fails again, surface the error.
- **Datetimes:** tools accept ISO 8601 (`2026-07-15T17:00`); naive datetimes are
  interpreted in the configured timezone. All-day events accept plain dates.
- **Recurrence:** `create_event` takes an optional `rrule` string
  (e.g. `RRULE:FREQ=WEEKLY;BYDAY=TU`), passed through verbatim.
- **Errors:** no silent guessing. Bad credentials, missing frame ID, and
  unexpected response shapes (API drift) return the HTTP status and body excerpt
  so the failure is diagnosable. The client stays thin — one file to fix if
  Skylight changes the API.
- **Output:** tools return compact structured summaries (event id, summary,
  local times, category labels), not raw JSON:API payloads.

## Testing

- `pytest` + `respx` mocking httpx: login flow, 401-retry, event create payload
  shape, list parsing (including recurring events), category parsing, error paths.
- One opt-in live smoke test (`SKYLIGHT_LIVE_TEST=1`) that logs in, lists
  events for today, creates and then deletes nothing (read-only) against the
  real frame.
- Manual end-to-end verification at completion: create a real test event via
  Claude, confirm it renders on the frame, then delete it in the Skylight app.

## Risks

- **Unofficial API** — may change or be blocked without notice. Mitigation: thin
  client, vendored OpenAPI spec for re-derivation, clear error surfacing.
- **Create-payload uncertainty** — the spec's create example writes through a
  linked Google calendar account. Whether a bare native event needs
  `calendar_account_id` must be confirmed with real traffic early in
  implementation (Task 1 of the plan).
