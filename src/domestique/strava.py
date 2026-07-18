"""Strava fetch + summarise: raw MCP data -> a compact activity block (BUILD_SPEC §4.1).

The `brief` flow's Fetch step pulls the last 28 days from the Strava MCP
(`list_activities`, `get_athlete_zones`) plus `get_activity_performance` for the
three most recent rides, then summarises them into a compact block (~2k tokens):
date, name, sport, duration, distance, elevation, avg power, kJ, HR, relative effort.

**Data source (BUILD_SPEC §2, §4.1 auth note).** The hosted Strava connector is
attached to the *agent* at the platform layer, not exposed to a standalone process
as a URL or token, so a subprocess cannot call it directly. This module therefore
reads raw Strava MCP results from a JSON file (`domestique brief --activities …`),
produced from the Strava MCP itself — activity facts still come only from Strava,
never invented (CLAUDE.md hard rule). When a standalone CLI later carries its own
Strava OAuth token, `agent.py` attaches the MCP server so the model can also make
follow-up tool calls (BUILD_SPEC §4.4); this module's summary remains the anchor.

Input JSON schema (all keys optional except `activities`):
    {
      "activities":   [ <list_activities entries> ],
      "zones":        { <get_athlete_zones> },
      "performance":  { "<activity_id>": { <get_activity_performance headline> } }
    }
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

# Sport types that count as a bike ride for "3 most recent rides" enrichment (§4.1).
RIDE_SPORTS = {"Ride", "GravelRide", "VirtualRide", "MountainBikeRide", "EBikeRide"}


def load_raw(path: str | Path) -> dict:
    """Load raw Strava MCP results from a JSON file (see module docstring for schema)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "activities" not in data:
        raise ValueError("Strava data file must contain an 'activities' list.")
    return data


def _hm(seconds: float | None) -> str:
    """Format a duration in seconds as 'Hh MMm' (moving time)."""
    if not seconds:
        return "—"
    total = int(seconds)
    return f"{total // 3600}h{(total % 3600) // 60:02d}m"


def _dated(start_local: str | None) -> str:
    """'YYYY-MM-DD Ddd' from a start-local timestamp — real weekday, never guessed."""
    iso = (start_local or "")[:10]
    if not iso:
        return "—"
    try:
        return f"{iso} {date.fromisoformat(iso):%a}"
    except ValueError:
        return iso


def _zones_block(zones: dict | None) -> str:
    """One-line power-zone summary from get_athlete_zones, if present."""
    if not zones:
        return ""
    ftp = zones.get("ftp")
    pz = zones.get("power_zones") or []
    if not ftp or not pz:
        return ""
    src = zones.get("power_zone_source", "")
    est = " (estimated)" if zones.get("ftp_is_estimated") else ""
    bounds = " / ".join(
        f"Z{i + 1} {z.get('min')}–{z.get('max', '')}".rstrip("–") for i, z in enumerate(pz)
    )
    # Strava reports its own FTP; the athlete profile FTP is the source of truth for
    # prescriptions (BUILD_SPEC §5). Label it so this figure never outranks the profile.
    return (
        f"Strava zones (informational — the athlete profile FTP is authoritative): "
        f"FTP {ftp}W{est} [{src}] · power zones {bounds}"
    )


def _activity_line(a: dict, perf: dict | None) -> str:
    """One compact line per activity; enriched with power/HR when perf is available."""
    s = a.get("summary", {})
    sport = a.get("sport_type", "?")
    parts = [
        f"{_dated(a.get('start_local'))}  {a.get('name', '(unnamed)')}",
        sport,
        _hm(s.get("moving_time")),
    ]
    dist = s.get("distance")
    if dist:
        parts.append(f"{dist / 1000:.1f}km")
    if s.get("elevation_gain"):
        parts.append(f"+{round(s['elevation_gain'])}m")

    if perf and perf.get("average_watts"):
        w = perf["average_watts"]
        parts.append(f"avg {round(w)}W")
        kj = round(w * (s.get("moving_time") or 0) / 1000)
        if kj:
            parts.append(f"{kj}kJ")
    elif s.get("total_calories"):
        parts.append(f"{round(s['total_calories'])}kcal")

    if perf and perf.get("average_heartrate"):
        hr = f"HR {round(perf['average_heartrate'])}"
        if perf.get("max_heartrate"):
            hr += f"/{round(perf['max_heartrate'])}"
        parts.append(hr)

    if s.get("relative_effort"):
        parts.append(f"RE {round(s['relative_effort'])}")
    if a.get("is_trainer"):
        parts.append("indoor")
    return " | ".join(parts)


def _recent_ride_ids(activities: list[dict], n: int = 3) -> list[str]:
    """IDs of the n most recent bike rides (activities are newest-first from the MCP)."""
    ids: list[str] = []
    for a in activities:
        if a.get("sport_type") in RIDE_SPORTS:
            ids.append(str(a.get("id")))
        if len(ids) >= n:
            break
    return ids


def summarise(data: dict) -> str:
    """Turn raw Strava MCP data into the compact activity block (BUILD_SPEC §4.1)."""
    activities = data.get("activities", [])
    if not activities:
        return "RECENT TRAINING (Strava, last 28 days): no activities returned."

    performance = data.get("performance", {}) or {}
    dates = [(a.get("start_local", "") or "")[:10] for a in activities if a.get("start_local")]
    window = f"{min(dates)} → {max(dates)}" if dates else "last 28 days"

    lines = [f"RECENT TRAINING (Strava, {len(activities)} activities, {window}):"]
    zb = _zones_block(data.get("zones"))
    if zb:
        lines.append(zb)
    lines.append("")

    for a in activities:
        perf = performance.get(str(a.get("id")))
        lines.append("  " + _activity_line(a, perf))

    # The three most recent rides get an explicit power/HR read (§4.1).
    detail = [
        (a, performance[str(a.get("id"))])
        for a in activities
        if str(a.get("id")) in _recent_ride_ids(activities) and str(a.get("id")) in performance
    ]
    if detail:
        lines.append("")
        lines.append("Three most recent rides — performance detail:")
        for a, perf in detail:
            s = a.get("summary", {})
            bits = [f"{_dated(a.get('start_local'))} {a.get('name', '')}"]
            if perf.get("average_watts"):
                bits.append(f"avg {round(perf['average_watts'])}W")
            if perf.get("average_heartrate"):
                hr = f"HR {round(perf['average_heartrate'])}"
                if perf.get("max_heartrate"):
                    hr += f"/{round(perf['max_heartrate'])}"
                bits.append(hr)
            if s.get("moving_time") and perf.get("average_watts"):
                bits.append(f"{round(perf['average_watts'] * s['moving_time'] / 1000)}kJ")
            if perf.get("calories"):
                bits.append(f"{round(perf['calories'])}kcal")
            for k, label in (("normalized_power", "NP"), ("weighted_average_watts", "NP")):
                if perf.get(k):
                    bits.append(f"{label} {round(perf[k])}W")
                    break
            lines.append("  - " + " | ".join(bits))

    return "\n".join(lines)


def activity_block(activities_path: str | Path) -> str:
    """Load a raw Strava JSON file and return the compact activity block."""
    return summarise(load_raw(activities_path))
