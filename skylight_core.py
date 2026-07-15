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
