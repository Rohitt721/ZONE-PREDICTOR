"""
analytics.py
Pure-Python computation functions for the BGMI Zone Predictor analytics dashboard.
No external dependencies — uses only stdlib math.
"""
from __future__ import annotations

import math
from typing import List, Dict, Tuple, Optional, Any

from zone_manager import PHASE_RADII_M, ERANGEL_MAP_SIZE_M, NUM_PHASES


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _dist_norm(ax, ay, bx, by) -> float:
    """Euclidean distance in normalized coords."""
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def _dist_meters(ax, ay, bx, by) -> float:
    """Euclidean distance converted to in-game meters."""
    return _dist_norm(ax, ay, bx, by) * ERANGEL_MAP_SIZE_M


def _valid_matches(matches: List[dict]) -> List[dict]:
    """Return matches that have both a flight path and at least one zone."""
    return [m for m in matches if m.get("flight_path") and m.get("zones")]


# ─── 1. Model Accuracy Stats ─────────────────────────────────────────────────

def model_accuracy_stats(predictor, matches: List[dict]) -> Dict[int, dict]:
    """
    Evaluate predictor accuracy by leave-one-out: train on all other matches,
    predict for the held-out match, compare prediction vs ground truth.

    Returns:
        {phase: {avg_m, min_m, max_m, n_samples, errors_m: [float, ...]}}
    """
    valid = _valid_matches(matches)
    if len(valid) < 2:
        return {}

    per_phase_errors: Dict[int, List[float]] = {p: [] for p in range(1, NUM_PHASES + 1)}

    for i, held_out in enumerate(valid):
        training = [m for j, m in enumerate(valid) if j != i]
        fp = held_out.get("flight_path")
        zones = sorted(held_out.get("zones", []), key=lambda z: z.get("phase", 99))
        if not fp or not zones:
            continue

        # Re-train on everything except held-out
        try:
            predictor.train(training)
        except Exception:
            continue

        # Predict autoregressively
        try:
            known: List[dict] = []
            for zone in zones:
                phase = zone.get("phase")
                if not (1 <= phase <= NUM_PHASES):
                    continue
                predictions = predictor.predict_all(fp, known)
                pred_for_phase = next((p for p in predictions if p.phase == phase), None)
                if pred_for_phase:
                    err = _dist_meters(
                        pred_for_phase.center_x, pred_for_phase.center_y,
                        zone["center_x"], zone["center_y"]
                    )
                    per_phase_errors[phase].append(err)
                known.append(zone)
        except Exception:
            continue

    result: Dict[int, dict] = {}
    for phase in range(1, NUM_PHASES + 1):
        errors = per_phase_errors[phase]
        if not errors:
            result[phase] = {"avg_m": None, "min_m": None, "max_m": None, "n_samples": 0, "errors_m": []}
        else:
            result[phase] = {
                "avg_m": sum(errors) / len(errors),
                "min_m": min(errors),
                "max_m": max(errors),
                "n_samples": len(errors),
                "errors_m": errors,
            }
    return result


# ─── 2. Zone Heatmap ─────────────────────────────────────────────────────────

def zone_heatmap_data(matches: List[dict], grid: int = 50) -> Dict[int, List[List[int]]]:
    """
    Build a grid×grid frequency grid for each phase showing where zone
    centres land across all matches.

    Returns:
        {phase: [[count, ...], ...]}  (row-major, top-left = [0][0])
    """
    grids: Dict[int, List[List[int]]] = {
        p: [[0] * grid for _ in range(grid)]
        for p in range(1, NUM_PHASES + 1)
    }

    for match in matches:
        for zone in match.get("zones", []):
            phase = zone.get("phase")
            if not (1 <= phase <= NUM_PHASES):
                continue
            col = min(grid - 1, int(zone["center_x"] * grid))
            row = min(grid - 1, int(zone["center_y"] * grid))
            col = max(0, col)
            row = max(0, row)
            grids[phase][row][col] += 1

    return grids


# ─── 3. Flight Path Heatmap ───────────────────────────────────────────────────

def flight_path_heatmap_data(matches: List[dict], grid: int = 50) -> List[List[int]]:
    """
    Build a grid×grid frequency grid showing where annotated flight paths pass.
    Uses Bresenham-style line rasterisation in grid coordinates.

    Returns:
        [[count, ...], ...]  (row-major)
    """
    density: List[List[int]] = [[0] * grid for _ in range(grid)]

    for match in matches:
        fp = match.get("flight_path")
        if not fp:
            continue
        sx = int(max(0, min(grid - 1, fp["start_x"] * grid)))
        sy = int(max(0, min(grid - 1, fp["start_y"] * grid)))
        ex = int(max(0, min(grid - 1, fp["end_x"] * grid)))
        ey = int(max(0, min(grid - 1, fp["end_y"] * grid)))

        # Bresenham line
        dx = abs(ex - sx)
        dy = abs(ey - sy)
        x, y = sx, sy
        step_x = 1 if ex > sx else -1
        step_y = 1 if ey > sy else -1
        if dx > dy:
            err = dx // 2
            while x != ex:
                density[y][x] += 1
                err -= dy
                if err < 0:
                    y += step_y
                    err += dx
                x += step_x
        else:
            err = dy // 2
            while y != ey:
                density[y][x] += 1
                err -= dx
                if err < 0:
                    x += step_x
                    err += dy
                y += step_y
        density[ey][ex] += 1

    return density


# ─── 4. Match Statistics ──────────────────────────────────────────────────────

def match_statistics(matches: List[dict]) -> dict:
    """
    Aggregate statistics across all matches.

    Returns a dict with:
        total_matches      int
        total_zones        int
        zones_per_match    [int]           histogram list (one per match)
        per_phase: {
            phase: {
                avg_cx, avg_cy,            normalised centre of mass
                avg_radius_m,              avg annotated radius
                ref_radius_m,              reference radius from constants
                avg_radius_error_m,        avg |annotated - reference|
                avg_drift_m,               avg centre drift from previous phase
                n_zones,                   total annotated across all matches
            }
        }
    """
    valid = _valid_matches(matches)

    per_phase_cx: Dict[int, List[float]] = {p: [] for p in range(1, NUM_PHASES + 1)}
    per_phase_cy: Dict[int, List[float]] = {p: [] for p in range(1, NUM_PHASES + 1)}
    per_phase_r:  Dict[int, List[float]] = {p: [] for p in range(1, NUM_PHASES + 1)}
    per_phase_drift: Dict[int, List[float]] = {p: [] for p in range(2, NUM_PHASES + 1)}
    zones_per_match: List[int] = []
    total_zones = 0

    for match in matches:
        zones = sorted(match.get("zones", []), key=lambda z: z.get("phase", 99))
        zones_per_match.append(len(zones))
        total_zones += len(zones)
        prev: Optional[dict] = None
        for zone in zones:
            phase = zone.get("phase")
            if not (1 <= phase <= NUM_PHASES):
                continue
            per_phase_cx[phase].append(zone["center_x"])
            per_phase_cy[phase].append(zone["center_y"])
            per_phase_r[phase].append(zone["radius"] * ERANGEL_MAP_SIZE_M)
            if prev and prev.get("phase") == phase - 1 and phase >= 2:
                drift = _dist_meters(zone["center_x"], zone["center_y"],
                                     prev["center_x"],  prev["center_y"])
                per_phase_drift[phase].append(drift)
            prev = zone

    def _avg(lst):
        return sum(lst) / len(lst) if lst else None

    per_phase_stats: Dict[int, dict] = {}
    for phase in range(1, NUM_PHASES + 1):
        ref_r = PHASE_RADII_M.get(phase, 0)
        avg_r = _avg(per_phase_r[phase])
        avg_r_err = _avg([abs(r - ref_r) for r in per_phase_r[phase]]) if per_phase_r[phase] else None
        per_phase_stats[phase] = {
            "avg_cx":           _avg(per_phase_cx[phase]),
            "avg_cy":           _avg(per_phase_cy[phase]),
            "avg_radius_m":     avg_r,
            "ref_radius_m":     ref_r,
            "avg_radius_error_m": avg_r_err,
            "avg_drift_m":      _avg(per_phase_drift.get(phase, [])),
            "n_zones":          len(per_phase_cx[phase]),
        }

    return {
        "total_matches": len(matches),
        "total_zones":   total_zones,
        "zones_per_match": zones_per_match,
        "per_phase":     per_phase_stats,
    }


# ─── 5. Zone Coverage ────────────────────────────────────────────────────────

def zone_coverage(matches: List[dict]) -> Dict[int, dict]:
    """
    Per phase: compute the average percentage of the map area covered
    by the annotated zone circle.

    Zone area = π·r²  (normalized units, so as fraction of unit square).
    Coverage % = min(100, zone_area / 1.0 * 100).

    Returns:
        {phase: {avg_pct, min_pct, max_pct, n_zones}}
    """
    per_phase: Dict[int, List[float]] = {p: [] for p in range(1, NUM_PHASES + 1)}

    for match in matches:
        for zone in match.get("zones", []):
            phase = zone.get("phase")
            if not (1 <= phase <= NUM_PHASES):
                continue
            r = zone.get("radius", 0.0)
            area = math.pi * r * r   # fraction of 1×1 map
            pct = min(100.0, area * 100.0)
            per_phase[phase].append(pct)

    result: Dict[int, dict] = {}
    for phase in range(1, NUM_PHASES + 1):
        vals = per_phase[phase]
        if not vals:
            result[phase] = {"avg_pct": None, "min_pct": None, "max_pct": None, "n_zones": 0}
        else:
            result[phase] = {
                "avg_pct": sum(vals) / len(vals),
                "min_pct": min(vals),
                "max_pct": max(vals),
                "n_zones": len(vals),
            }
    return result
