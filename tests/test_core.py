"""Tests for skylight_core.SkylightClient (all HTTP mocked with respx)."""

import base64
import json as jsonlib

import httpx
import pytest
import respx

import skylight_core as core

BASE = core.BASE_URL


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("SKYLIGHT_EMAIL", "lance@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "hunter2")
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "42")
    monkeypatch.delenv("SKYLIGHT_TIMEZONE", raising=False)
    monkeypatch.delenv("SKYLIGHT_AUTH_SCHEME", raising=False)


def login_route(token="tok123"):
    return respx.post(f"{BASE}/api/sessions").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"id": "1", "type": "authenticated_user",
                           "attributes": {"email": "lance@example.com", "token": token}}},
        )
    )


@respx.mock
def test_login_returns_token():
    route = login_route()
    client = core.SkylightClient()
    assert client.login() == "tok123"
    body = route.calls.last.request.content
    assert b"lance@example.com" in body and b"hunter2" in body


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.delenv("SKYLIGHT_EMAIL")
    with pytest.raises(core.SkylightError, match="SKYLIGHT_EMAIL"):
        core.SkylightClient()


@respx.mock
def test_login_failure_raises():
    respx.post(f"{BASE}/api/sessions").mock(
        return_value=httpx.Response(401, json={"error": "bad credentials"})
    )
    client = core.SkylightClient()
    with pytest.raises(core.SkylightError, match="401"):
        client.login()


@respx.mock
def test_request_sends_basic_auth_header():
    login_route()
    expected = base64.b64encode(b"tok123").decode()
    route = respx.get(f"{BASE}/api/ping").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = core.SkylightClient()
    assert client._request("GET", "/api/ping") == {"ok": True}
    assert route.calls.last.request.headers["Authorization"] == f"Basic {expected}"


@respx.mock
def test_request_bearer_scheme(monkeypatch):
    monkeypatch.setenv("SKYLIGHT_AUTH_SCHEME", "bearer")
    login_route()
    route = respx.get(f"{BASE}/api/ping").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = core.SkylightClient()
    client._request("GET", "/api/ping")
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok123"


@respx.mock
def test_request_retries_once_on_401():
    login_route()
    route = respx.get(f"{BASE}/api/ping")
    route.side_effect = [
        httpx.Response(401, json={"error": "expired"}),
        httpx.Response(200, json={"ok": True}),
    ]
    client = core.SkylightClient()
    assert client._request("GET", "/api/ping") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_request_error_surfaces_status_and_body():
    login_route()
    respx.get(f"{BASE}/api/ping").mock(
        return_value=httpx.Response(500, text="internal splat")
    )
    client = core.SkylightClient()
    with pytest.raises(core.SkylightError, match="500.*internal splat"):
        client._request("GET", "/api/ping")


@respx.mock
def test_frame_id_from_env():
    login_route()
    client = core.SkylightClient()
    assert client.frame_id == "42"


@respx.mock
def test_frame_id_discovered(monkeypatch):
    monkeypatch.delenv("SKYLIGHT_FRAME_ID")
    login_route()
    respx.get(f"{BASE}/api/frames").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "777", "type": "frame", "attributes": {"name": "Kitchen"}}]}
        )
    )
    client = core.SkylightClient()
    assert client.frame_id == "777"
    assert client.frame_id == "777"  # cached — respx would fail on a second unmocked call


@respx.mock
def test_frame_id_discovery_failure_explains_env_var(monkeypatch):
    monkeypatch.delenv("SKYLIGHT_FRAME_ID")
    login_route()
    respx.get(f"{BASE}/api/frames").mock(return_value=httpx.Response(404, text="nope"))
    client = core.SkylightClient()
    with pytest.raises(core.SkylightError, match="SKYLIGHT_FRAME_ID"):
        _ = client.frame_id


CATEGORIES_JSON = {
    "data": [
        {"id": "111", "type": "category",
         "attributes": {"id": 111, "label": "Lance", "color": "#CB434C"}},
        {"id": "222", "type": "category",
         "attributes": {"id": 222, "label": "Family", "color": "#3B82F6"}},
    ]
}


@respx.mock
def test_get_categories():
    login_route()
    respx.get(f"{BASE}/api/frames/42/categories").mock(
        return_value=httpx.Response(200, json=CATEGORIES_JSON)
    )
    client = core.SkylightClient()
    cats = client.get_categories()
    assert cats == [
        {"id": "111", "label": "Lance", "color": "#CB434C"},
        {"id": "222", "label": "Family", "color": "#3B82F6"},
    ]


EVENTS_JSON = {
    "data": [
        {
            "id": "5355662012-1767018600",
            "type": "calendar_event",
            "attributes": {
                "summary": "Soccer practice",
                "starts_at": "2026-07-21 17:00:00-05:00",
                "ends_at": "2026-07-21 18:00:00-05:00",
                "all_day": False,
                "location": "Field 3",
                "description": None,
                "recurring": True,
                "rrule": ["RRULE:FREQ=WEEKLY;BYDAY=TU"],
                "source": "google",
                "status": "approved",
            },
            "relationships": {
                "categories": {"data": [{"id": "111", "type": "category"}]},
            },
        }
    ],
    "included": [
        {"id": "111", "type": "category",
         "attributes": {"id": 111, "label": "Lance", "color": "#CB434C"}},
    ],
}


@respx.mock
def test_list_events_parses_and_resolves_categories():
    login_route()
    route = respx.get(f"{BASE}/api/frames/42/calendar_events").mock(
        return_value=httpx.Response(200, json=EVENTS_JSON)
    )
    client = core.SkylightClient()
    events = client.list_events("2026-07-20", "2026-07-27")
    params = dict(httpx.URL(str(route.calls.last.request.url)).params)
    assert params["date_min"] == "2026-07-20"
    assert params["date_max"] == "2026-07-27"
    assert params["timezone"] == "America/Chicago"
    assert len(events) == 1
    ev = events[0]
    assert ev["summary"] == "Soccer practice"
    assert ev["categories"] == ["Lance"]
    assert ev["starts_at"] == "2026-07-21 17:00:00-05:00"
    assert ev["rrule"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]


@respx.mock
def test_list_events_defaults_to_next_seven_days():
    login_route()
    route = respx.get(f"{BASE}/api/frames/42/calendar_events").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = core.SkylightClient()
    assert client.list_events() == []
    params = dict(httpx.URL(str(route.calls.last.request.url)).params)
    from datetime import datetime, timedelta

    today = datetime.now(client.tz).date()
    assert params["date_min"] == today.isoformat()
    assert params["date_max"] == (today + timedelta(days=7)).isoformat()


def created_event_response():
    return httpx.Response(
        200,
        json={
            "data": {
                "id": "999",
                "type": "calendar_event",
                "attributes": {
                    "summary": "Dentist",
                    "starts_at": "2026-07-20 17:00:00-05:00",
                    "ends_at": "2026-07-20 18:00:00-05:00",
                    "all_day": False,
                    "status": "approved",
                    "source": "skylight",
                },
                "relationships": {"category": {"data": {"id": "111", "type": "category"}}},
            },
            "included": [
                {"id": "111", "type": "category",
                 "attributes": {"id": 111, "label": "Lance", "color": "#CB434C"}},
            ],
        },
    )


@respx.mock
def test_create_event_converts_naive_local_to_utc():
    login_route()
    route = respx.post(f"{BASE}/api/frames/42/calendar_events").mock(
        return_value=created_event_response()
    )
    client = core.SkylightClient()
    ev = client.create_event(
        "Dentist", "2026-07-20T17:00", category_ids=["111"], location="123 Main St"
    )
    body = jsonlib.loads(route.calls.last.request.content)
    # July in America/Chicago is UTC-5
    assert body["starts_at"] == "2026-07-20 22:00:00+00:00"
    assert body["ends_at"] == "2026-07-20 23:00:00+00:00"  # default: start + 1h
    assert body["summary"] == "Dentist"
    assert body["timezone"] == "America/Chicago"
    assert body["category_ids"] == ["111"]
    assert body["location"] == "123 Main St"
    assert body["all_day"] is False
    assert body["kind"] == "standard"
    assert body["rrule"] is None
    assert ev["id"] == "999"
    assert ev["categories"] == ["Lance"]


@respx.mock
def test_create_event_all_day_and_rrule():
    login_route()
    route = respx.post(f"{BASE}/api/frames/42/calendar_events").mock(
        return_value=created_event_response()
    )
    client = core.SkylightClient()
    client.create_event(
        "Trash day", "2026-07-21", all_day=True, rrule="RRULE:FREQ=WEEKLY;BYDAY=TU"
    )
    body = jsonlib.loads(route.calls.last.request.content)
    assert body["all_day"] is True
    assert body["starts_at"].startswith("2026-07-21")
    assert body["ends_at"].startswith("2026-07-21")
    assert body["rrule"] == "RRULE:FREQ=WEEKLY;BYDAY=TU"


@respx.mock
def test_create_event_rejects_bad_datetime():
    login_route()
    client = core.SkylightClient()
    with pytest.raises(core.SkylightError, match="Could not parse"):
        client.create_event("Bad", "next tuesday-ish")
