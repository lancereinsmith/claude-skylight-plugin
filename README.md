# claude-skylight-plugin

Claude Code / Claude Desktop MCP plugin that adds and reads events on a
[Skylight Calendar](https://www.skylightframe.com/) frame via the unofficial
`app.ourskylight.com` API (reverse-engineered; see `spec/skylight-openapi.yaml`
and [TheEagleByte/skylight-api](https://github.com/TheEagleByte/skylight-api)).

## Tools

- `create_event` — add an event (title, times, location, family-member category, RRULE recurrence)
- `list_events` — events in a date range
- `get_categories` — family members / color categories with IDs

## Configuration

| Env var | Required | Notes |
|---|---|---|
| `SKYLIGHT_EMAIL` | yes | ourskylight.com login |
| `SKYLIGHT_PASSWORD` | yes | |
| `SKYLIGHT_FRAME_ID` | no | auto-discovered when possible; else copy from the web app URL |
| `SKYLIGHT_TIMEZONE` | no | default `America/Chicago` |
| `SKYLIGHT_AUTH_SCHEME` | no | `basic` (default) or `bearer` |

## Install (Claude Code)

    claude mcp add skylight -e SKYLIGHT_EMAIL=you@example.com -e SKYLIGHT_PASSWORD=... \
      -- uvx --from git+https://github.com/lancereinsmith/claude-skylight-plugin claude-skylight-plugin

## Development

    uv sync
    uv run pytest

**Disclaimer:** unofficial API; may break without notice. Not affiliated with Skylight.
