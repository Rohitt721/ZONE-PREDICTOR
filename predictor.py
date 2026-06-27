"""
predictor.py
ML-based zone predictor for BGMI Erangel.

Architecture:
  - Trains a separate RandomForest model for each of the 8 phases.
  - Phase N model takes: [flight_path_features + zone_1_features + ... + zone_(N-1)_features]
  - Outputs: (center_x, center_y)  — radius is looked up from reference table.
  - Falls back to a geometric heuristic if fewer than MIN_SAMPLES matches exist.

Autoregressive inference:
  - If user provides 0 known zones → predict all 8.
  - If user provides K known zones → predict phases K+1 … 8,
    feeding each prediction back as context for the next.
"""

from __future__ import annotations
import math
from typing import List, Tuple, Dict, Optional, Any

import storage
from zone_manager import Zone, PHASE_RADII_NORM, PHASE_RADII_M, clamp_zone_to_parent

MIN_SAMPLES = 5   # samples needed before ML is used instead of heuristic


# ─── Feature helpers ─────────────────────────────────────────────────────────

def _fp_features(fp: dict) -> List[float]:
    """8 features from flight path."""
    sx, sy = fp["start_x"], fp["start_y"]
    ex, ey = fp["end_x"], fp["end_y"]
    mx, my = (sx + ex) / 2, (sy + ey) / 2
    dx, dy = ex - sx, ey - sy
    length = math.sqrt(dx * dx + dy * dy) or 1e-9
    return [sx, sy, ex, ey, mx, my, dx / length, dy / length]


def _zone_features(z: dict) -> List[float]:
    """3 features from a zone dict."""
    return [z["center_x"], z["center_y"], z["radius"]]


def _build_features(fp: dict, known_zones: List[dict]) -> List[float]:
    """Feature vector = fp_features + known_zone_features (in order)."""
    feats = _fp_features(fp)
    for z in known_zones:
        feats.extend(_zone_features(z))
    return feats


# ─── Heuristic fallback ───────────────────────────────────────────────────────

def _heuristic(fp: dict, known_zones: List[dict], phase: int) -> Tuple[float, float]:
    """
    Geometric heuristic used when training data is insufficient.
    - Phase 1: weighted blend of flight-path midpoint and map centre.
    - Phase N: drift previous zone centre toward map centre,
               clamped inside the previous zone circle.
    """
    MAP_CX, MAP_CY = 0.5, 0.5
    radius = PHASE_RADII_NORM.get(phase, 0.05)

    if not known_zones:
        # Pull slightly toward flight path midpoint
        mx = (fp["start_x"] + fp["end_x"]) / 2
        my = (fp["start_y"] + fp["end_y"]) / 2
        cx = 0.35 * mx + 0.65 * MAP_CX
        cy = 0.35 * my + 0.65 * MAP_CY
    else:
        prev = known_zones[-1]
        pcx, pcy = prev["center_x"], prev["center_y"]
        pr = prev.get("radius", PHASE_RADII_NORM.get(phase - 1, 0.1))
        # Drift factor increases slightly with each phase
        drift = min(0.10 + 0.03 * (phase - 2), 0.40)
        cx = pcx * (1 - drift) + MAP_CX * drift
        cy = pcy * (1 - drift) + MAP_CY * drift
        cx, cy, _ = clamp_zone_to_parent(cx, cy, radius, pcx, pcy, pr)

    cx = max(radius, min(1.0 - radius, cx))
    cy = max(radius, min(1.0 - radius, cy))
    return cx, cy


# ─── Predictor class ──────────────────────────────────────────────────────────

class ZonePredictor:
    """
    Trains per-phase RandomForest regressors on the saved dataset and
    predicts zone centres autoregressively.
    """

    def __init__(self):
        # model_x[phase] = (fitted_model, expected_feature_length)
        self.model_x: Dict[int, Tuple[Any, int]] = {}
        self.model_y: Dict[int, Tuple[Any, int]] = {}
        self.sample_counts: Dict[int, int] = {}
        self.is_trained: bool = False
        self._has_sklearn: bool = self._check_sklearn()

    # ─── Public API ───────────────────────────────────────────────────────────

    def train(self, matches: Optional[List[dict]] = None) -> Dict[int, int]:
        """
        Build and fit models from the saved dataset.
        Returns {phase: n_training_samples}.
        """
        if matches is None:
            matches = storage.list_matches()

        # Accumulate per-phase training data
        X: Dict[int, List[List[float]]] = {p: [] for p in range(1, 9)}
        Yx: Dict[int, List[float]] = {p: [] for p in range(1, 9)}
        Yy: Dict[int, List[float]] = {p: [] for p in range(1, 9)}

        for m in matches:
            fp = m.get("flight_path")
            zones: List[dict] = m.get("zones", [])
            if fp is None or not zones:
                continue
            # Sort zones by phase to guarantee ordering
            zones_sorted = sorted(zones, key=lambda z: z.get("phase", 99))
            for i, zone in enumerate(zones_sorted):
                phase = zone.get("phase", i + 1)
                if not (1 <= phase <= 8):
                    continue
                known = zones_sorted[:i]      # all prior zones as context
                feats = _build_features(fp, known)
                X[phase].append(feats)
                Yx[phase].append(zone["center_x"])
                Yy[phase].append(zone["center_y"])

        self.model_x.clear()
        self.model_y.clear()
        self.sample_counts.clear()

        for phase in range(1, 9):
            n = len(X[phase])
            self.sample_counts[phase] = n
            if n < MIN_SAMPLES or not self._has_sklearn:
                continue
            # All samples for a given phase have the SAME feature length
            feat_len = len(X[phase][0])
            from sklearn.ensemble import GradientBoostingRegressor
            mx = GradientBoostingRegressor(n_estimators=100, max_depth=3,
                                           learning_rate=0.1, random_state=42)
            my = GradientBoostingRegressor(n_estimators=100, max_depth=3,
                                           learning_rate=0.1, random_state=42)
            mx.fit(X[phase], Yx[phase])
            my.fit(X[phase], Yy[phase])
            self.model_x[phase] = (mx, feat_len)
            self.model_y[phase] = (my, feat_len)

        self.is_trained = True
        return self.sample_counts

    def predict_all(self, fp: dict, known_zones: List[dict]) -> List[Zone]:
        """
        Predict all zones whose phase is NOT already in known_zones.
        Autoregressively feeds each prediction back as context.
        Returns a list of predicted Zone objects in phase order.
        """
        known_phases = {z["phase"] for z in known_zones}
        # Running context = actual known + auto-predicted so far
        context: List[dict] = sorted(known_zones, key=lambda z: z.get("phase", 99))
        predictions: List[Zone] = []

        for phase in range(1, 9):
            if phase in known_phases:
                continue   # skip — already annotated by user
            cx, cy = self._predict_one(fp, context, phase)
            radius = PHASE_RADII_NORM.get(phase, 0.05)
            z_dict = {"phase": phase, "center_x": cx, "center_y": cy, "radius": radius}
            predictions.append(Zone(phase=phase, center_x=cx, center_y=cy, radius=radius))
            context.append(z_dict)   # feed prediction as context for next phase

        return predictions

    def confidence_for(self, phase: int) -> str:
        """Human-readable confidence label for a phase."""
        n = self.sample_counts.get(phase, 0)
        if not self._has_sklearn:
            return "Heuristic (no sklearn)"
        if n < MIN_SAMPLES:
            return f"Heuristic ({n}/{MIN_SAMPLES} samples)"
        return f"ML model ({n} samples)"

    def confidence_info(self) -> dict:
        """Return structural confidence info for the UI."""
        ml_phases = [p for p, c in self.sample_counts.items() 
                     if c >= MIN_SAMPLES and p in self.model_x]
        return {
            "samples": self.sample_counts,
            "ml_phases": ml_phases
        }

    def total_matches(self) -> int:
        return max(self.sample_counts.values(), default=0)

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _predict_one(self, fp: dict, context: List[dict], phase: int) -> Tuple[float, float]:
        """Predict (cx, cy) for one phase."""
        n = self.sample_counts.get(phase, 0)
        if n >= MIN_SAMPLES and phase in self.model_x:
            feats = _build_features(fp, context)
            expected_len = self.model_x[phase][1]
            # Pad if this inference context is shorter than training context
            if len(feats) < expected_len:
                feats = feats + [0.0] * (expected_len - len(feats))
            else:
                feats = feats[:expected_len]
            cx = float(self.model_x[phase][0].predict([feats])[0])
            cy = float(self.model_y[phase][0].predict([feats])[0])
            
            # Clamp ML prediction to parent zone if there is one
            if context:
                prev = context[-1]
                pcx, pcy = prev["center_x"], prev["center_y"]
                pr = prev.get("radius", PHASE_RADII_NORM.get(phase - 1, 0.1))
                child_r = PHASE_RADII_NORM.get(phase, 0.05)
                cx, cy, _ = clamp_zone_to_parent(cx, cy, child_r, pcx, pcy, pr)
                
            return max(0.0, min(1.0, cx)), max(0.0, min(1.0, cy))

        # Heuristic fallback
        return _heuristic(fp, context, phase)

    @staticmethod
    def _check_sklearn() -> bool:
        try:
            import sklearn  # noqa
            return True
        except ImportError:
            return False
