"""
storage.py
Handles all JSON file I/O for match data, configuration, and dataset export.
"""

import json
import os
from pathlib import Path
from typing import Optional, List

DATASET_DIR = Path("dataset")
CONFIG_FILE = Path("config.json")


def ensure_dirs():
    """Ensure required directories exist."""
    DATASET_DIR.mkdir(exist_ok=True)


# ─── Config ───────────────────────────────────────────────────────────────────

def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


# ─── Match CRUD ───────────────────────────────────────────────────────────────

def save_match(match_data: dict) -> Path:
    """Save a match dict to dataset/match_<id>.json."""
    ensure_dirs()
    match_id = match_data["match_id"]
    path = DATASET_DIR / f"match_{match_id}.json"
    with open(path, "w") as f:
        json.dump(match_data, f, indent=2)
    return path


def load_match(match_id: str) -> Optional[dict]:
    """Load a match dict by ID. Returns None if not found."""
    path = DATASET_DIR / f"match_{match_id}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def list_matches() -> List[dict]:
    """Return all saved matches sorted by match_id."""
    ensure_dirs()
    matches = []
    for f in sorted(DATASET_DIR.glob("match_*.json")):
        try:
            with open(f) as fp:
                data = json.load(fp)
                matches.append(data)
        except (json.JSONDecodeError, IOError):
            pass
    return matches


def delete_match_file(match_id: str) -> bool:
    """Delete match JSON. Returns True on success."""
    path = DATASET_DIR / f"match_{match_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def get_next_match_id() -> str:
    """Return the next zero-padded 3-digit match ID."""
    matches = list_matches()
    if not matches:
        return "001"
    ids = []
    for m in matches:
        try:
            ids.append(int(m["match_id"]))
        except (ValueError, KeyError):
            pass
    next_id = (max(ids) + 1) if ids else 1
    return str(next_id).zfill(3)


# ─── Dataset Export ───────────────────────────────────────────────────────────

def export_full_dataset(output_path: Path) -> int:
    """Export all matches into one combined JSON. Returns match count."""
    matches = list_matches()
    payload = {
        "version": "1.0",
        "total_matches": len(matches),
        "matches": matches,
    }
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)
    return len(matches)


def export_training_data(output_path: Path) -> int:
    """
    Export training-ready records.
    Each record: { flight_path, zones_input: [z1..zN-1], target_zone: zN }
    Skips matches with fewer than 2 zones.
    """
    matches = list_matches()
    records = []
    for m in matches:
        zones = m.get("zones", [])
        fp = m.get("flight_path")
        if len(zones) < 2 or fp is None:
            continue
        for i in range(1, len(zones)):
            records.append({
                "match_id": m["match_id"],
                "flight_path": fp,
                "zones_input": zones[:i],
                "target_zone": zones[i],
            })
    payload = {"version": "1.0", "total_records": len(records), "records": records}
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)
    return len(records)
