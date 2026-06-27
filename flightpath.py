"""
flightpath.py
FlightPath data model representing the airplane route for a match.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FlightPath:
    """
    Normalized flight path from start to end across the Erangel map.
    All coordinates are in [0.0, 1.0] range where (0,0) = top-left, (1,1) = bottom-right.
    """
    start_x: float = 0.0
    start_y: float = 0.0
    end_x: float   = 1.0
    end_y: float   = 1.0
    visible: bool  = True

    # ─── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "start_x": round(self.start_x, 6),
            "start_y": round(self.start_y, 6),
            "end_x":   round(self.end_x,   6),
            "end_y":   round(self.end_y,   6),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FlightPath":
        return cls(
            start_x=float(d["start_x"]),
            start_y=float(d["start_y"]),
            end_x=float(d["end_x"]),
            end_y=float(d["end_y"]),
        )

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def length_norm(self) -> float:
        """Euclidean length in normalized space."""
        dx = self.end_x - self.start_x
        dy = self.end_y - self.start_y
        return (dx * dx + dy * dy) ** 0.5

    def midpoint(self):
        """Return (mx, my) midpoint in normalized coords."""
        return ((self.start_x + self.end_x) / 2,
                (self.start_y + self.end_y) / 2)

    def angle_deg(self) -> float:
        """Angle of flight path in degrees (0 = right, 90 = down)."""
        import math
        dx = self.end_x - self.start_x
        dy = self.end_y - self.start_y
        return math.degrees(math.atan2(dy, dx))

    def __repr__(self):
        return (f"FlightPath(({self.start_x:.3f},{self.start_y:.3f}) → "
                f"({self.end_x:.3f},{self.end_y:.3f}))")
