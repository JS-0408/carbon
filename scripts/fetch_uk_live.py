"""Script: fetch live data from UK Carbon Intensity API and update backend/data/uk_snapshot.json."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

BASE = "https://api.carbonintensity.org.uk"
SNAPSHOT = Path(__file__).parent.parent / "backend" / "data" / "uk_snapshot.json"


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def fetch(days: int = 6) -> dict:
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    start = end - timedelta(days=days)
    url = f"{BASE}/intensity/{iso(start)}/{iso(end)}"
    print(f"GET {url}", flush=True)
    with httpx.Client(timeout=30.0) as c:
        r = c.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()["data"]
    if not data:
        raise ValueError("API returned no data")
    return {
        "fetched_at": iso(datetime.now(timezone.utc)),
        "from": data[0]["from"],
        "to": data[-1]["to"],
        "points": [
            {
                "from": d["from"],
                "forecast": d["intensity"]["forecast"],
                "actual": d["intensity"]["actual"],
            }
            for d in data
        ],
    }


def validate(snap: dict) -> None:
    pts = snap["points"]
    non_null = [p for p in pts if p["forecast"] is not None or p["actual"] is not None]
    values = [
        float(p["forecast"] if p["forecast"] is not None else p["actual"])
        for p in non_null
    ]
    assert all(v > 0 and v < 1000 for v in values), "Unexpected intensity values"
    print(f"Validated {len(pts)} points ({len(non_null)} non-null), range: {min(values):.0f}–{max(values):.0f} gCO2/kWh")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    print(f"Fetching {days} days of UK Carbon Intensity data ...", flush=True)
    snap = fetch(days)
    validate(snap)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snap), encoding="utf-8")
    print(f"Saved {len(snap['points'])} points to {SNAPSHOT}")
    print(f"  From: {snap['from']}")
    print(f"  To  : {snap['to']}")
    print(f"  Fetched at: {snap['fetched_at']}")
    print("DONE - real data snapshot updated.")
