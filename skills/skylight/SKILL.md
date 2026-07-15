---
name: skylight
description: Add or check events on the family's Skylight Calendar frame. Use when the user asks to put something on the Skylight, the family calendar, or the frame, or asks what's on the calendar.
argument-hint: event to add or date range to check
---

You are helping a family manage their Skylight Calendar frame using the skylight MCP tools.

## Workflow

1. **Adding an event for a person:** call `get_categories` first to map the family
   member's name to a category ID, then `create_event` with that ID.
2. **Adding a general event:** call `create_event` directly (no category needed).
3. **Checking the calendar / conflicts:** call `list_events` with the date range;
   before adding an event, check the same time window and mention any overlap.

## Datetimes

ISO 8601. Naive datetimes ("2026-07-20T17:00") are local to the frame's timezone
(default America/Chicago). All-day events take plain dates with `all_day=true`.
Recurring events take an RRULE string, e.g. "RRULE:FREQ=WEEKLY;BYDAY=TU".

## Authentication

Handled by env vars: SKYLIGHT_EMAIL, SKYLIGHT_PASSWORD, optional SKYLIGHT_FRAME_ID,
SKYLIGHT_TIMEZONE, SKYLIGHT_AUTH_SCHEME. If tools fail with a credential error, ask
the user to check those. This is an unofficial API — surface unexpected errors
verbatim rather than retrying blindly.
