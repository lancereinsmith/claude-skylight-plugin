# claude-skylight-plugin

Claude Code / Claude Desktop MCP plugin that adds, reads, and deletes events on a
[Skylight Calendar](https://www.skylightframe.com/) frame via the unofficial
`app.ourskylight.com` API (reverse-engineered; see `spec/skylight-openapi.yaml`
and [TheEagleByte/skylight-api](https://github.com/TheEagleByte/skylight-api)).

## Tools

- `create_event` — add an event (title, times, location, family-member category, RRULE recurrence)
- `list_events` — events in a date range
- `delete_event` — remove an event by ID
- `get_categories` — family members / color categories with IDs

## Configuration

| Env var | Required | Notes |
| --- | --- | --- |
| `SKYLIGHT_EMAIL` | yes | ourskylight.com login |
| `SKYLIGHT_PASSWORD` | yes | |
| `SKYLIGHT_FRAME_ID` | no | auto-discovered when possible; else copy from the web app URL |
| `SKYLIGHT_TIMEZONE` | no | default `America/Chicago` |

Auth is a headless replay of Skylight's own web OAuth 2.0 (Authorization
Code + PKCE) login flow — email/password are still the only inputs required;
the plugin drives the same browser-facing endpoints the web app uses and
exchanges the result for a bearer token.

## Install (Claude Code)

### From the marketplace (recommended)

    claude plugin marketplace add lancereinsmith/claude-marketplace
    claude plugin install skylight@lancereinsmith

Then set `SKYLIGHT_EMAIL` and `SKYLIGHT_PASSWORD` in your environment (e.g. your
shell profile) so the MCP server can log in.

### Direct MCP server install

    claude mcp add skylight -e SKYLIGHT_EMAIL=you@example.com -e SKYLIGHT_PASSWORD=... \
      -- uvx --from git+https://github.com/lancereinsmith/claude-skylight-plugin claude-skylight-plugin

## Use as a Python library

The Skylight API client (`skylight_core.py`) is packaged with the plugin, so
you can reuse it in any Python project without the MCP layer.

### Install from GitHub

pip:

    pip install git+https://github.com/lancereinsmith/claude-skylight-plugin

uv (adds it to your project's `pyproject.toml`):

    uv add git+https://github.com/lancereinsmith/claude-skylight-plugin

### Install from a local clone

    git clone https://github.com/lancereinsmith/claude-skylight-plugin

pip (activate your project's virtualenv first; editable, so edits to the
clone take effect immediately):

    cd claude-skylight-plugin
    pip install -e .

uv (from your project directory):

    uv add --editable ../claude-skylight-plugin

### Usage

    from skylight_core import SkylightClient

    # Reads SKYLIGHT_EMAIL / SKYLIGHT_PASSWORD (and optional SKYLIGHT_FRAME_ID,
    # SKYLIGHT_TIMEZONE) from the environment; or pass them explicitly:
    client = SkylightClient(email="you@example.com", password="...")

    categories = client.get_categories()          # family members with IDs
    events = client.list_events("2026-07-16", "2026-07-20")
    client.create_event(
        "Dinner with the Smiths",
        "2026-07-18T18:00",                        # naive datetimes = frame timezone
        ends_at="2026-07-18T20:00",
        category_ids=[categories[0]["id"]],
    )

Naive datetimes are interpreted in the frame's timezone. `rrule` accepts a
recurrence string such as `"RRULE:FREQ=WEEKLY;BYDAY=TU"`.

## Development

    uv sync
    uv run pytest

**Disclaimer:** unofficial API; may break without notice. Not affiliated with Skylight.
