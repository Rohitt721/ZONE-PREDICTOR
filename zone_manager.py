"""
zone_manager.py
Zone data model, phase colors, and reference radii constants.
"""

from dataclasses import dataclass
from typing import Dict

# ─── Constants ────────────────────────────────────────────────────────────────

ERANGEL_MAP_SIZE_M = 8000.0  # The map is 8 km × 8 km

# Reference radii per phase in in-game meters (from user specification)
PHASE_RADII_M: Dict[int, int] = {
    1: 2310,
    2: 1220,
    3: 740,
    4: 440,
    5: 270,
    6: 170,
    7: 100,
    8: 75,
}

# Normalized reference radii (fraction of map width)
PHASE_RADII_NORM: Dict[int, float] = {
    k: v / ERANGEL_MAP_SIZE_M for k, v in PHASE_RADII_M.items()
}

# Distinct colors for each phase (border / label color)
PHASE_COLORS: Dict[int, str] = {
    1: "#4FC3F7",  # Light blue
    2: "#69F0AE",  # Green
    3: "#FFD740",  # Amber
    4: "#FF6D00",  # Deep orange
    5: "#F06292",  # Pink
    6: "#CE93D8",  # Lavender
    7: "#80DEEA",  # Cyan
    8: "#FFFFFF",  # White  (final / blue zone)
}

# Translucent fill colors (hex with alpha as last 2 chars, not fully supported
# in Tkinter — used for PIL-based PNG export overlay only)
PHASE_FILL_ALPHA: Dict[int, tuple] = {
    1: (79,  195, 247, 25),
    2: (105, 240, 174, 25),
    3: (255, 215,  64, 25),
    4: (255, 109,   0, 25),
    5: (240,  98, 146, 25),
    6: (206, 147, 216, 25),
    7: (128, 222, 234, 25),
    8: (255, 255, 255, 40),
}

FLIGHT_PATH_COLOR = "#29B6F6"
NUM_PHASES = 8


# ─── Zone Dataclass ───────────────────────────────────────────────────────────

@dataclass
class Zone:
    """
    A single safe-zone circle annotation.
    All spatial values are normalized [0.0, 1.0].
    radius is a fraction of the map width (= map_width_px * zoom as denominator).
    """
    phase: int
    center_x: float
    center_y: float
    radius: float
    visible: bool = True

    # ─── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "phase":    self.phase,
            "center_x": round(self.center_x, 6),
            "center_y": round(self.center_y, 6),
            "radius":   round(self.radius,   6),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Zone":
        return cls(
            phase=int(d["phase"]),
            center_x=float(d["center_x"]),
            center_y=float(d["center_y"]),
            radius=float(d["radius"]),
        )

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def radius_meters(self) -> float:
        return self.radius * ERANGEL_MAP_SIZE_M

    def reference_radius(self) -> float:
        """Standard normalized radius for this phase."""
        return PHASE_RADII_NORM.get(self.phase, 0.1)

    def reference_radius_m(self) -> int:
        return PHASE_RADII_M.get(self.phase, 0)

    def color(self) -> str:
        return PHASE_COLORS.get(self.phase, "#FFFFFF")

    def fill_alpha(self) -> tuple:
        return PHASE_FILL_ALPHA.get(self.phase, (255, 255, 255, 20))

    def contains_point(self, nx: float, ny: float) -> bool:
        """Return True if normalized point (nx, ny) is inside this circle."""
        dx = nx - self.center_x
        dy = ny - self.center_y
        return (dx * dx + dy * dy) <= self.radius * self.radius

    def distance_to_edge(self, nx: float, ny: float) -> float:
        """Distance from point to circle edge in normalized units."""
        import math
        dx = nx - self.center_x
        dy = ny - self.center_y
        dist = math.sqrt(dx * dx + dy * dy)
        return abs(dist - self.radius)

    def __repr__(self):
        return (f"Zone(phase={self.phase}, "
                f"center=({self.center_x:.3f},{self.center_y:.3f}), "
                f"r={self.radius:.4f} [{self.radius_meters():.0f}m])")

def clamp_zone_to_parent(
    child_cx: float, child_cy: float, child_r: float,
    parent_cx: float, parent_cy: float, parent_r: float
) -> tuple[float, float, float]:
    """
    Enforces that the child circle is completely inside the parent circle.
    If the child is too large, its radius is clamped to the parent's radius.
    If the child center is too far from the parent center, it is clamped
    so that distance(child, parent) + child_r <= parent_r.
    Returns the clamped (child_cx, child_cy, child_r).
    """
    import math
    
    # 1. Enforce radius constraint
    child_r = min(child_r, parent_r)
    
    # 2. Enforce center distance constraint
    max_dist = max(0.0, parent_r - child_r)
    dx = child_cx - parent_cx
    dy = child_cy - parent_cy
    dist = math.sqrt(dx * dx + dy * dy)
    
    if dist > max_dist and dist > 1e-9:
        scale = max_dist / dist
        child_cx = parent_cx + dx * scale
        child_cy = parent_cy + dy * scale
        
    return child_cx, child_cy, child_r
