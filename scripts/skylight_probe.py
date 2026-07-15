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

    # Check for unknown commands before creating the client (requires credentials)
    known_commands = {"auth", "frames", "categories", "events", "create-test"}
    if cmd not in known_commands:
        print(__doc__)
        sys.exit(1)

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
