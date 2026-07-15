# Skylight Calendar MCP Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code plugin (MCP server) that creates and reads events on the family's Skylight Calendar frame via the unofficial `app.ourskylight.com` API.

**Architecture:** Two-file core mirroring `~/Maker/claude-qgenda-plugin`: `skylight_core.py` (auth + HTTP client, no MCP awareness) and `server.py` (FastMCP tool definitions). Packaged with `.mcp.json` + `.claude-plugin/plugin.json` so `uvx --from git+…` can run it.

**Tech Stack:** Python ≥3.11, `uv`/hatchling, `mcp[cli]` (FastMCP), `httpx`; tests with `pytest` + `respx`.

**Spec:** `docs/superpowers/specs/2026-07-15-skylight-mcp-design.md`. Endpoint reference: `spec/skylight-openapi.yaml` (vendored, reverse-engineered — treat as best-guess, verified live in Task 6).

## Global Constraints

- Python `>=3.11`; runtime deps exactly: `mcp[cli]>=1.26.0`, `httpx>=0.27`. Dev deps: `pytest>=8.0`, `respx>=0.22`.
- Base URL constant: `https://app.ourskylight.com`.
- Env vars: `SKYLIGHT_EMAIL`, `SKYLIGHT_PASSWORD` (required), `SKYLIGHT_FRAME_ID`, `SKYLIGHT_TIMEZONE` (default `America/Chicago`), `SKYLIGHT_AUTH_SCHEME` (`basic` default, or `bearer`).
- Never log or return credentials/tokens in tool output.
- MCP tools return JSON strings (via `json.dumps(..., indent=2)`), errors as `"Error: …"` strings — same convention as qgenda plugin.
- All commands run from `/Users/lance/Maker/skylight` with `uv run`.

---

### Task 1: Scaffold + SkylightClient auth

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.python-version`, `skylight_core.py`, `tests/__init__.py`, `tests/test_core.py`

**Interfaces:**
- Produces: `SkylightError(RuntimeError)`; `SkylightClient(email=None, password=None, frame_id=None, tz=None)` reading env fallbacks; `client.login() -> str` (token); `client._request(method, path, **kwargs) -> dict` (auth header, one 401 re-login retry, raises `SkylightError` on ≥400); `BASE_URL` constant.

- [ ] **Step 1: Scaffold project files**

`pyproject.toml`:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "claude-skylight-plugin"
version = "0.1.0"
description = "Skylight Calendar events skill for Claude Code and Claude Desktop (MCP)"
license = "MIT"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.26.0",
    "httpx>=0.27",
]

[dependency-groups]
dev = ["pytest>=8.0", "respx>=0.22"]

[tool.hatch.build.targets.wheel]
packages = ["."]
only-include = ["server.py", "skylight_core.py"]

[project.scripts]
claude-skylight-plugin = "server:mcp.run"
```

`.python-version`: `3.11`

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
.env
.pytest_cache/
dist/
.DS_Store
```

`tests/__init__.py`: empty file.

Also `touch README.md` (empty placeholder — hatchling needs it to build; real content comes in Task 5).

Then run: `uv sync` — expected: creates `.venv`, installs deps.

- [ ] **Step 2: Write failing tests for login and auth**

`tests/test_core.py`:
```python
"""Tests for skylight_core.SkylightClient (all HTTP mocked with respx)."""

import base64

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_core.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'skylight_core'`

- [ ] **Step 4: Implement `skylight_core.py` auth**

```python
"""Shared Skylight client logic used by the MCP server and probe script.

Wraps the unofficial API at https://app.ourskylight.com (reverse-engineered;
see spec/skylight-openapi.yaml). Deliberately thin: if Skylight changes the
API, this is the only file to fix.
"""

import base64
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

BASE_URL = "https://app.ourskylight.com"


class SkylightError(RuntimeError):
    """Raised for auth/config problems and non-2xx API responses."""


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


class SkylightClient:
    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        frame_id: str | None = None,
        tz: str | None = None,
    ):
        self.email = email or _env("SKYLIGHT_EMAIL")
        self.password = password or _env("SKYLIGHT_PASSWORD")
        missing = [
            name
            for name, val in (("SKYLIGHT_EMAIL", self.email), ("SKYLIGHT_PASSWORD", self.password))
            if not val
        ]
        if missing:
            raise SkylightError(
                f"Skylight credentials not configured: set {' and '.join(missing)} "
                "(your ourskylight.com login)."
            )
        self._frame_id = frame_id or _env("SKYLIGHT_FRAME_ID") or None
        self.tz = ZoneInfo(tz or _env("SKYLIGHT_TIMEZONE") or "America/Chicago")
        self.auth_scheme = (_env("SKYLIGHT_AUTH_SCHEME") or "basic").lower()
        self._token: str | None = None
        self._http = httpx.Client(base_url=BASE_URL, timeout=30)

    # -- auth -----------------------------------------------------------

    def login(self) -> str:
        resp = self._http.post(
            "/api/sessions", json={"email": self.email, "password": self.password}
        )
        if resp.status_code != 200:
            raise SkylightError(
                f"Skylight login failed ({resp.status_code}): {resp.text[:300]}"
            )
        self._token = resp.json()["data"]["attributes"]["token"]
        return self._token

    def _auth_header(self) -> dict[str, str]:
        if self._token is None:
            self.login()
        if self.auth_scheme == "bearer":
            return {"Authorization": f"Bearer {self._token}"}
        encoded = base64.b64encode(self._token.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = self._http.request(method, path, headers=self._auth_header(), **kwargs)
        if resp.status_code == 401:
            self.login()
            resp = self._http.request(method, path, headers=self._auth_header(), **kwargs)
        if resp.status_code >= 400:
            raise SkylightError(
                f"{method} {path} failed ({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .python-version .gitignore uv.lock skylight_core.py tests/
git commit -m "feat: scaffold project and SkylightClient auth with 401 retry"
```

---

### Task 2: Frame discovery + categories

**Files:**
- Modify: `skylight_core.py` (append methods to `SkylightClient`)
- Modify: `tests/test_core.py` (append tests)

**Interfaces:**
- Consumes: `SkylightClient._request`, `login_route()` test helper from Task 1.
- Produces: `client.frame_id -> str` (property: env/arg value, else discovered via `GET /api/frames`, cached); `client.get_categories() -> list[dict]` with keys `id`, `label`, `color`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_core.py -v`
Expected: 7 pass (Task 1), 4 FAIL with `AttributeError` (`frame_id`, `get_categories`)

- [ ] **Step 3: Implement**

Append inside `SkylightClient`:
```python
    # -- frame + categories ----------------------------------------------

    @property
    def frame_id(self) -> str:
        if self._frame_id:
            return self._frame_id
        try:
            frames = self._request("GET", "/api/frames")["data"]
            self._frame_id = frames[0]["id"]
        except (SkylightError, KeyError, IndexError) as exc:
            raise SkylightError(
                "Could not auto-discover your frame ID. Set SKYLIGHT_FRAME_ID: "
                "log in at https://app.ourskylight.com and copy the number from "
                f"the URL (e.g. /frames/12345). Underlying error: {exc}"
            ) from exc
        return self._frame_id

    def get_categories(self) -> list[dict]:
        data = self._request("GET", f"/api/frames/{self.frame_id}/categories")["data"]
        return [
            {
                "id": item["id"],
                "label": item["attributes"].get("label"),
                "color": item["attributes"].get("color"),
            }
            for item in data
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add skylight_core.py tests/test_core.py
git commit -m "feat: frame ID discovery and get_categories"
```

---

### Task 3: list_events

**Files:**
- Modify: `skylight_core.py` (datetime helpers + `list_events`)
- Modify: `tests/test_core.py` (append tests)

**Interfaces:**
- Consumes: `client._request`, `client.frame_id`, `client.tz`.
- Produces: `client.list_events(date_min: str | None, date_max: str | None) -> list[dict]` — dates `YYYY-MM-DD`, defaults today → today+7 (in `client.tz`); event dicts with keys `id`, `summary`, `starts_at`, `ends_at` (ISO strings in frame's tz), `all_day`, `location`, `description`, `recurring`, `rrule`, `source`, `status`, `categories` (list of labels). Module-level `_parse_event(item, cat_lookup) -> dict` shared with Task 4.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_core.py -v`
Expected: 12 pass, 2 FAIL with `AttributeError: ... 'list_events'`

- [ ] **Step 3: Implement**

Add module-level function after `SkylightError` in `skylight_core.py`:
```python
def _parse_event(item: dict, cat_lookup: dict[str, str]) -> dict:
    attrs = item.get("attributes", {})
    rels = item.get("relationships", {})
    cat_refs = []
    for key in ("categories", "category"):
        data = (rels.get(key) or {}).get("data")
        if isinstance(data, list):
            cat_refs += [d["id"] for d in data]
        elif isinstance(data, dict):
            cat_refs.append(data["id"])
    return {
        "id": item.get("id"),
        "summary": attrs.get("summary"),
        "starts_at": attrs.get("starts_at"),
        "ends_at": attrs.get("ends_at"),
        "all_day": attrs.get("all_day"),
        "location": attrs.get("location"),
        "description": attrs.get("description"),
        "recurring": attrs.get("recurring"),
        "rrule": attrs.get("rrule"),
        "source": attrs.get("source"),
        "status": attrs.get("status"),
        "categories": [cat_lookup.get(cid, cid) for cid in cat_refs],
    }
```

Append inside `SkylightClient`:
```python
    # -- events -----------------------------------------------------------

    def list_events(
        self, date_min: str | None = None, date_max: str | None = None
    ) -> list[dict]:
        today = datetime.now(self.tz).date()
        params = {
            "date_min": date_min or today.isoformat(),
            "date_max": date_max or (today + timedelta(days=7)).isoformat(),
            "timezone": str(self.tz),
            "include": "categories",
        }
        payload = self._request(
            "GET", f"/api/frames/{self.frame_id}/calendar_events", params=params
        )
        cat_lookup = {
            inc["id"]: inc["attributes"].get("label")
            for inc in payload.get("included", [])
            if inc.get("type") == "category"
        }
        return [_parse_event(item, cat_lookup) for item in payload.get("data", [])]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add skylight_core.py tests/test_core.py
git commit -m "feat: list_events with category resolution and 7-day default"
```

---

### Task 4: create_event

**Files:**
- Modify: `skylight_core.py` (datetime parsing + `create_event`)
- Modify: `tests/test_core.py` (append tests)

**Interfaces:**
- Consumes: `client._request`, `client.frame_id`, `client.tz`, `_parse_event`.
- Produces: `client.create_event(summary, starts_at, ends_at=None, all_day=False, description="", location="", category_ids=None, rrule=None) -> dict` (parsed created event). Datetimes: ISO 8601 strings; naive → interpreted in `client.tz`; sent to API as UTC `"YYYY-MM-DD HH:MM:SS+00:00"`. `ends_at=None` → start + 1 hour. `all_day=True` accepts plain dates; `ends_at` defaults to same day.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_core.py`:
```python
import json as jsonlib


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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_core.py -v`
Expected: 14 pass, 3 FAIL with `AttributeError: ... 'create_event'`

- [ ] **Step 3: Implement**

Add to `skylight_core.py` imports: `from datetime import datetime, timedelta, timezone` (extend the existing import). Add module-level helper after `_parse_event`:
```python
def _parse_when(value: str, tz: ZoneInfo) -> datetime:
    """Parse an ISO 8601 date/datetime; naive values are local to tz."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SkylightError(
            f"Could not parse datetime {value!r}: use ISO 8601, e.g. "
            "'2026-07-20T17:00' or '2026-07-20'."
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _utc_str(dt: datetime) -> str:
    return str(dt.astimezone(timezone.utc))
```

Append inside `SkylightClient`:
```python
    def create_event(
        self,
        summary: str,
        starts_at: str,
        ends_at: str | None = None,
        all_day: bool = False,
        description: str = "",
        location: str = "",
        category_ids: list[str] | None = None,
        rrule: str | None = None,
    ) -> dict:
        start = _parse_when(starts_at, self.tz)
        if ends_at:
            end = _parse_when(ends_at, self.tz)
        elif all_day:
            end = start
        else:
            end = start + timedelta(hours=1)
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "starts_at": _utc_str(start),
            "ends_at": _utc_str(end),
            "timezone": str(self.tz),
            "all_day": all_day,
            "category_ids": category_ids or [],
            "rrule": rrule,
            "kind": "standard",
            "invited_emails": [],
            "countdown_enabled": False,
        }
        payload = self._request(
            "POST", f"/api/frames/{self.frame_id}/calendar_events", json=body
        )
        cat_lookup = {
            inc["id"]: inc["attributes"].get("label")
            for inc in payload.get("included", [])
            if inc.get("type") == "category"
        }
        return _parse_event(payload["data"], cat_lookup)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add skylight_core.py tests/test_core.py
git commit -m "feat: create_event with local-time parsing and RRULE passthrough"
```

---

### Task 5: MCP server + plugin packaging

Note: the spec's file listing mentions `justfile`, `Dockerfile`, and `package/install.sh` "per qgenda plugin". These are deliberately deferred (YAGNI) — the `.mcp.json` `uvx --from git+…` install path needs none of them. Add later only if a non-uv install target appears.

**Files:**
- Create: `server.py`, `.mcp.json`, `.claude-plugin/plugin.json`, `skills/skylight/SKILL.md`, `README.md` (replace Task 1's empty placeholder)
- Test: manual — `uv run mcp` tool listing (server is a thin wrapper; core logic already covered by pytest, same convention as qgenda plugin which only tests core)

**Interfaces:**
- Consumes: `core.SkylightClient` (Tasks 1–4).
- Produces: MCP tools `create_event`, `list_events`, `get_categories`; console script `claude-skylight-plugin` (already declared in Task 1's pyproject).

- [ ] **Step 1: Write `server.py`**

```python
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
```

- [ ] **Step 2: Write plugin packaging files**

`.mcp.json`:
```json
{
  "mcpServers": {
    "skylight": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/lancereinsmith/claude-skylight-plugin",
        "claude-skylight-plugin"
      ]
    }
  }
}
```

`.claude-plugin/plugin.json`:
```json
{
  "name": "skylight",
  "version": "0.1.0",
  "description": "Add and read events on a Skylight Calendar frame via the unofficial Skylight API.",
  "author": {
    "name": "Lance Reinsmith"
  },
  "repository": "https://github.com/lancereinsmith/claude-skylight-plugin",
  "license": "MIT",
  "mcpServers": "./.mcp.json"
}
```

`skills/skylight/SKILL.md`:
```markdown
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
```

`README.md`:
```markdown
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
```

- [ ] **Step 3: Verify the server starts and exposes tools**

Run: `SKYLIGHT_EMAIL=x SKYLIGHT_PASSWORD=y uv run python -c "
import asyncio, server
tools = asyncio.run(server.mcp.list_tools())
print(sorted(t.name for t in tools))"`
Expected output: `['create_event', 'get_categories', 'list_events']`

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add server.py .mcp.json .claude-plugin/ skills/ README.md
git commit -m "feat: FastMCP server with create/list/categories tools and plugin packaging"
```

---

### Task 6: Probe script + live verification (manual checkpoint)

**Files:**
- Create: `scripts/skylight_probe.py`
- Requires: real credentials in a local `.env` (git-ignored) — **needs Lance at the keyboard**

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: verified answers to the two open spec questions (auth scheme; whether native create needs `calendar_account_id`). If reality differs from the spec's guesses, fix `skylight_core.py` and its tests in this task.

- [ ] **Step 1: Write the probe script**

`scripts/skylight_probe.py`:
```python
"""Live probe for the unofficial Skylight API. Requires real credentials.

Usage (reads SKYLIGHT_EMAIL / SKYLIGHT_PASSWORD from the environment):
    uv run python scripts/skylight_probe.py auth        # test basic vs bearer
    uv run python scripts/skylight_probe.py frames      # try frame discovery
    uv run python scripts/skylight_probe.py categories
    uv run python scripts/skylight_probe.py events [date_min] [date_max]
    uv run python scripts/skylight_probe.py create-test # creates "SKYLIGHT PROBE TEST" tomorrow 15:00
"""

import json
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")
import skylight_core as core


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auth"
    client = core.SkylightClient()

    if cmd == "auth":
        token = client.login()
        print(f"Login OK. Token length: {len(token)} (not printed).")
        for scheme in ("basic", "bearer"):
            client.auth_scheme = scheme
            try:
                client._request("GET", f"/api/frames/{client.frame_id}/categories")
                print(f"  {scheme}: WORKS")
            except core.SkylightError as exc:
                print(f"  {scheme}: FAILED — {exc}")
    elif cmd == "frames":
        print(f"frame_id resolves to: {client.frame_id}")
    elif cmd == "categories":
        print(json.dumps(client.get_categories(), indent=2))
    elif cmd == "events":
        args = sys.argv[2:4]
        print(json.dumps(client.list_events(*args), indent=2))
    elif cmd == "create-test":
        when = (datetime.now(client.tz) + timedelta(days=1)).replace(
            hour=15, minute=0, second=0, microsecond=0
        )
        ev = client.create_event("SKYLIGHT PROBE TEST", when.isoformat())
        print(json.dumps(ev, indent=2))
        print("\nCheck the frame/app, then delete this event in the Skylight app.")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit the probe script**

```bash
git add scripts/skylight_probe.py
git commit -m "feat: live probe script for auth scheme and endpoint verification"
```

- [ ] **Step 3: Live verification (with Lance)**

Ask Lance to create `.env` with real `SKYLIGHT_EMAIL` / `SKYLIGHT_PASSWORD` (and `SKYLIGHT_FRAME_ID` if discovery fails), then run in order:

1. `set -a; source .env; set +a; uv run python scripts/skylight_probe.py auth`
   — Expected: login OK; note which scheme(s) work. **If only `bearer` works, change the default in `SkylightClient.__init__` from `"basic"` to `"bearer"`, update `test_request_sends_basic_auth_header` accordingly, and commit.**
2. `uv run python scripts/skylight_probe.py frames` — if discovery fails, confirm the env-var error message is clear and Lance sets `SKYLIGHT_FRAME_ID`.
3. `uv run python scripts/skylight_probe.py categories` — expected: family members with IDs/colors.
4. `uv run python scripts/skylight_probe.py events` — expected: this week's real events.
5. `uv run python scripts/skylight_probe.py create-test` — expected: event JSON returned. **If the API rejects the payload (e.g. requires `calendar_account_id`), capture the error body, adjust `create_event`'s body in `skylight_core.py` + tests, and re-run.**
6. Lance confirms "SKYLIGHT PROBE TEST" appears in the Skylight app/frame, then deletes it there.

- [ ] **Step 4: Record findings + final commit**

Update the spec's "Risks" section with what was verified (auth scheme, create payload shape). Run `uv run pytest -v` one final time (all pass), then:

```bash
git add -A
git commit -m "docs: record live API verification findings"
```
