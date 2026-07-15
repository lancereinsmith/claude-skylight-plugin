"""Skylight MCP Server — create and read events on a Skylight Calendar frame."""

import json
import logging

from mcp.server.fastmcp import FastMCP

import skylight_core as core

logger = logging.getLogger("skylight-mcp")

mcp = FastMCP(
    "skylight",
    instructions=(
        "You are helping a family manage their Skylight Calendar frame. "
        "Before creating an event with a person assignment, call get_categories "
        "to find the right category ID. Datetimes are ISO 8601; naive values are "
        "interpreted in the frame's timezone (default America/Chicago). "
        "This uses an unofficial API — if calls fail with unexpected errors, the "
        "API may have changed. Never expose or log credentials."
    ),
)

_client: core.SkylightClient | None = None


def _get_client() -> core.SkylightClient:
    global _client
    if _client is None:
        _client = core.SkylightClient()
    return _client


@mcp.tool()
def create_event(
    summary: str,
    starts_at: str,
    ends_at: str | None = None,
    all_day: bool = False,
    description: str = "",
    location: str = "",
    category_ids: list[str] | None = None,
    rrule: str | None = None,
) -> str:
    """Add an event to the Skylight Calendar frame.

    Args:
        summary: Event title as it will appear on the frame.
        starts_at: ISO 8601 start, e.g. "2026-07-20T17:00" (local) or "2026-07-20" for all-day.
        ends_at: ISO 8601 end. Defaults to starts_at + 1 hour (or same day if all_day).
        all_day: True for all-day events (pass plain dates).
        description: Optional details.
        location: Optional location text.
        category_ids: Category (family member) IDs from get_categories.
        rrule: Optional recurrence rule, e.g. "RRULE:FREQ=WEEKLY;BYDAY=TU".
    """
    try:
        return json.dumps(_get_client().create_event(
            summary, starts_at, ends_at, all_day, description, location, category_ids, rrule
        ), indent=2)
    except Exception as exc:
        return f"Error creating event: {exc}"


@mcp.tool()
def list_events(date_min: str | None = None, date_max: str | None = None) -> str:
    """List events on the Skylight Calendar in a date range.

    Args:
        date_min: Start date YYYY-MM-DD. Defaults to today.
        date_max: End date YYYY-MM-DD. Defaults to today + 7 days.
    """
    try:
        return json.dumps(_get_client().list_events(date_min, date_max), indent=2)
    except Exception as exc:
        return f"Error listing events: {exc}"


@mcp.tool()
def get_categories() -> str:
    """List the frame's categories (family members) with IDs and colors.

    Call this before create_event when the user wants an event assigned to a
    specific family member.
    """
    try:
        return json.dumps(_get_client().get_categories(), indent=2)
    except Exception as exc:
        return f"Error listing categories: {exc}"


if __name__ == "__main__":
    mcp.run()
