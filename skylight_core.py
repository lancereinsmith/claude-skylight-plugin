"""Shared Skylight client logic used by the MCP server and probe script.

Wraps the unofficial API at https://app.ourskylight.com (reverse-engineered;
see spec/skylight-openapi.yaml). Deliberately thin: if Skylight changes the
API, this is the only file to fix.
"""

import base64
import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

BASE_URL = "https://app.ourskylight.com"

# OAuth 2.0 Authorization Code + PKCE flow, replaying the web app. Verified
# live 2026-07-15 against the real API (the old POST /api/sessions login is
# retired). See docs/superpowers/specs/2026-07-15-skylight-mcp-design.md.
WEB_URL = "https://ourskylight.com"
CLIENT_ID = "skylight-mobile"
SCOPE = "everything"
REDIRECT_URI = f"{WEB_URL}/welcome"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:149.0) Gecko/20100101 Firefox/149.0"
)
API_UA = "SkylightMobile (web)"
API_VERSION = "2026-03-01"

_AUTHENTICITY_TOKEN_RE = re.compile(
    r'name=["\']authenticity_token["\'][^>]*value=["\']([^"\']+)["\']'
)


class SkylightError(RuntimeError):
    """Raised for auth/config problems and non-2xx API responses."""


def _new_pkce_verifier() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _new_state() -> str:
    return uuid.uuid4().hex[:10]


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
    return str(dt.astimezone(timezone.utc).replace(microsecond=0))


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
        self._token: str | None = None
        self._http = httpx.Client(base_url=BASE_URL, timeout=30)

    # -- auth -----------------------------------------------------------

    def login(self) -> str:
        """Replay Skylight's web OAuth 2.0 Authorization Code + PKCE flow.

        Five steps, all verified live 2026-07-15: authorize -> login form ->
        submit credentials -> resume authorize -> exchange code for token.
        Never include email, password, or tokens in raised error messages.
        """
        verifier = _new_pkce_verifier()
        challenge = _pkce_challenge(verifier)
        state = _new_state()

        browser_headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": BROWSER_UA,
            "Referer": f"{WEB_URL}/",
        }

        # Step 1: GET /oauth/authorize -> 302 to the login form.
        resp = self._http.get(
            "/oauth/authorize",
            params={
                "client_id": CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": SCOPE,
                "state": state,
                "prompt": "login",
            },
            headers=browser_headers,
        )
        if resp.status_code != 302:
            raise SkylightError(
                f"Skylight login step 1 (authorize) failed ({resp.status_code}): "
                f"{resp.text[:300]}"
            )
        login_form_url = resp.headers["location"]

        # Step 2: GET the login form -> extract the CSRF authenticity token.
        resp = self._http.get(login_form_url, headers=browser_headers)
        if resp.status_code != 200:
            raise SkylightError(
                f"Skylight login step 2 (login form) failed ({resp.status_code}): "
                f"{resp.text[:300]}"
            )
        match = _AUTHENTICITY_TOKEN_RE.search(resp.text)
        if not match:
            raise SkylightError(
                "Skylight login step 2 (login form): could not find an "
                "authenticity token in the response — Skylight may have "
                "changed its login page."
            )
        authenticity_token = match.group(1)

        # Step 3: POST credentials.
        resp = self._http.post(
            "/auth/session",
            data={
                "authenticity_token": authenticity_token,
                "email": self.email,
                "password": self.password,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/auth/session/new",
                "User-Agent": BROWSER_UA,
            },
        )
        if resp.status_code not in (301, 302, 303):
            raise SkylightError(
                "Skylight login step 3 (auth/session) did not redirect "
                f"(got {resp.status_code}) — check SKYLIGHT_EMAIL/SKYLIGHT_PASSWORD."
            )
        resume_url = httpx.URL(BASE_URL).join(resp.headers["location"])

        # Step 4: GET the resume URL -> redirect carrying the auth code + state.
        resp = self._http.get(str(resume_url), headers=browser_headers)
        if resp.status_code != 302:
            raise SkylightError(
                f"Skylight login step 4 (resume) failed ({resp.status_code}): "
                f"{resp.text[:300]}"
            )
        final_url = httpx.URL(resp.headers["location"])
        if final_url.params.get("state") != state:
            raise SkylightError(
                "Skylight login step 4 (resume): state mismatch in the "
                "redirect — possible CSRF or a stale login flow."
            )
        code = final_url.params.get("code")
        if not code:
            raise SkylightError(
                "Skylight login step 4 (resume): no authorization code in "
                "the redirect."
            )

        # Step 5: exchange the authorization code for an access token.
        resp = self._http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "scope": SCOPE,
                "redirect_uri": REDIRECT_URI,
                "code": code,
                "code_verifier": verifier,
                "skylight_api_client_device_fingerprint": str(uuid.uuid4()),
                "skylight_api_client_device_platform": "web",
                "skylight_api_client_device_name": "unknown",
                "skylight_api_client_device_os_version": "unknown",
                "skylight_api_client_device_app_version": "unknown",
                "skylight_api_client_device_hardware": "Macintosh",
            },
            headers={
                "Accept": "application/json, text/javascript; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": WEB_URL,
                "Referer": f"{WEB_URL}/",
                "User-Agent": BROWSER_UA,
            },
        )
        if resp.status_code != 200:
            raise SkylightError(
                f"Skylight login step 5 (token exchange) failed ({resp.status_code}): "
                f"{resp.text[:300]}"
            )
        body = resp.json()
        token = body.get("access_token") or body.get("token")
        if not token:
            raise SkylightError(
                "Skylight login step 5 (token exchange): no access_token in "
                "the response."
            )
        self._token = token
        return self._token

    def _auth_header(self) -> dict[str, str]:
        if self._token is None:
            self.login()
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": API_UA,
            "Skylight-Api-Version": API_VERSION,
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        extra_headers = kwargs.pop("headers", {})
        resp = self._http.request(
            method, path, headers={**self._auth_header(), **extra_headers}, **kwargs
        )
        if resp.status_code == 401:
            self.login()
            resp = self._http.request(
                method, path, headers={**self._auth_header(), **extra_headers}, **kwargs
            )
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

    def create_event(
        self,
        summary: str,
        starts_at: str,
        ends_at: str | None = None,
        all_day: bool = False,
        description: str = "",
        location: str = "",
        category_ids: list[str] | None = None,
        rrule: str | list[str] | None = None,
    ) -> dict:
        start = _parse_when(starts_at, self.tz)
        if ends_at:
            end = _parse_when(ends_at, self.tz)
        elif all_day:
            end = start
        else:
            end = start + timedelta(hours=1)
        if isinstance(rrule, str):
            rrule = [rrule]
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "starts_at": _utc_str(start),
            "ends_at": _utc_str(end),
            "timezone": str(self.tz),
            "all_day": all_day,
            "category_ids": category_ids or [],
            "rrule": rrule or None,
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
