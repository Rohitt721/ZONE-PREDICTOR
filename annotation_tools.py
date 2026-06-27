"""
annotation_tools.py
Tool state machines for user interaction on the map canvas.
Each tool handles mouse events and communicates back via the canvas/app.
"""

import math
from abc import ABC, abstractmethod
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from map_canvas import MapCanvas
    from dataset_manager import DatasetManager

from zone_manager import Zone, PHASE_COLORS, NUM_PHASES, clamp_zone_to_parent


# ─── Hit-test helpers ─────────────────────────────────────────────────────────

HANDLE_RADIUS_PX = 8   # pixels for edge-drag handle detection
CENTER_RADIUS_PX = 10  # pixels for center-click detection


def _dist(ax, ay, bx, by) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


# ─── Base Tool ────────────────────────────────────────────────────────────────

class BaseTool(ABC):
    def __init__(self, canvas: "MapCanvas", dm: "DatasetManager"):
        self.canvas = canvas
        self.dm = dm

    @abstractmethod
    def on_press(self, event): ...

    @abstractmethod
    def on_drag(self, event): ...

    @abstractmethod
    def on_release(self, event): ...

    def on_move(self, event):
        """Mouse movement without button (for hover/inspector)."""
        pass

    def cursor(self) -> str:
        return "crosshair"

    def cancel(self):
        """Called when tool is deactivated mid-action."""
        pass


# ─── Select Tool ─────────────────────────────────────────────────────────────

class SelectTool(BaseTool):
    """
    Click a circle center → select it.
    Drag center → move circle.
    Drag edge → resize circle.
    Click empty space → deselect.
    """

    MODE_IDLE    = "idle"
    MODE_MOVE    = "move"
    MODE_RESIZE  = "resize"

    def __init__(self, canvas, dm):
        super().__init__(canvas, dm)
        self._mode = self.MODE_IDLE
        self._drag_start_norm: Optional[Tuple[float, float]] = None
        self._orig_zone: Optional[Zone] = None
        self._orig_zone_idx: Optional[int] = None

    def cursor(self) -> str:
        return "arrow"

    def on_press(self, event):
        nx, ny = self.canvas.canvas_to_norm(event.x, event.y)
        zones = self.dm.get_zones()

        # Check flight path endpoints first
        fp = self.dm.get_flight_path()
        if fp:
            sx, sy = self.canvas.norm_to_canvas(fp.start_x, fp.start_y)
            ex, ey = self.canvas.norm_to_canvas(fp.end_x, fp.end_y)
            if _dist(event.x, event.y, sx, sy) < CENTER_RADIUS_PX:
                self.canvas.selected_index = None
                self.canvas.selected_fp_endpoint = "start"
                self._mode = self.MODE_MOVE
                self.canvas.redraw()
                return
            if _dist(event.x, event.y, ex, ey) < CENTER_RADIUS_PX:
                self.canvas.selected_index = None
                self.canvas.selected_fp_endpoint = "end"
                self._mode = self.MODE_MOVE
                self.canvas.redraw()
                return

        self.canvas.selected_fp_endpoint = None

        # Check zones in reverse order (top-most drawn = last in list)
        for i in range(len(zones) - 1, -1, -1):
            z = zones[i]
            if not z.visible:
                continue
            cx, cy = self.canvas.norm_to_canvas(z.center_x, z.center_y)
            rp = self.canvas.norm_radius_to_canvas(z.radius)

            # Center drag
            if _dist(event.x, event.y, cx, cy) < CENTER_RADIUS_PX:
                self.canvas.selected_index = i
                self._mode = self.MODE_MOVE
                self._drag_start_norm = (nx, ny)
                self._orig_zone = Zone(z.phase, z.center_x, z.center_y, z.radius)
                self._orig_zone_idx = i
                self.canvas.redraw()
                return

            # Edge resize handle
            dist_from_center = _dist(event.x, event.y, cx, cy)
            if abs(dist_from_center - rp) < HANDLE_RADIUS_PX:
                self.canvas.selected_index = i
                self._mode = self.MODE_RESIZE
                self._drag_start_norm = (nx, ny)
                self._orig_zone = Zone(z.phase, z.center_x, z.center_y, z.radius)
                self._orig_zone_idx = i
                self.canvas.redraw()
                return

        # Nothing hit → deselect
        self.canvas.selected_index = None
        self._mode = self.MODE_IDLE
        self.canvas.redraw()

    def on_drag(self, event):
        nx, ny = self.canvas.canvas_to_norm(event.x, event.y)
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))

        if self._mode == self.MODE_MOVE and self.canvas.selected_fp_endpoint and self.dm.get_flight_path():
            fp = self.dm.get_flight_path()
            if self.canvas.selected_fp_endpoint == "start":
                self.dm.current_match["flight_path"]["start_x"] = round(nx, 6)
                self.dm.current_match["flight_path"]["start_y"] = round(ny, 6)
            else:
                self.dm.current_match["flight_path"]["end_x"] = round(nx, 6)
                self.dm.current_match["flight_path"]["end_y"] = round(ny, 6)
            self.canvas.redraw()
            return

        if self._mode == self.MODE_MOVE and self._orig_zone is not None:
            idx = self._orig_zone_idx
            z = self._orig_zone
            dnx = nx - self._drag_start_norm[0]
            dny = ny - self._drag_start_norm[1]
            new_cx = max(0.0, min(1.0, z.center_x + dnx))
            new_cy = max(0.0, min(1.0, z.center_y + dny))
            new_r = z.radius
            
            # Find parent and child zones to constrain movement
            zones = self.dm.current_match.get("zones", [])
            parent_z = next((oz for i, oz in enumerate(zones) if i != idx and oz["phase"] == z.phase - 1), None)
            child_z  = next((oz for i, oz in enumerate(zones) if i != idx and oz["phase"] == z.phase + 1), None)
            
            # Clamp to parent
            if parent_z:
                new_cx, new_cy, new_r = clamp_zone_to_parent(
                    new_cx, new_cy, new_r, 
                    parent_z["center_x"], parent_z["center_y"], parent_z["radius"]
                )
            
            # Clamp child to this (this acts as parent to the child)
            if child_z:
                # To constrain *this* center so it contains the child:
                # We do the reverse clamp: try clamping the child to this new center.
                # If the child gets moved by clamping, it means this center is invalid.
                # Actually, simpler: dist(new_cx, child_cx) + child_r <= new_r
                # If dist > new_r - child_r, we must move new_cx towards child_cx
                # max_dist = max(0.0, new_r - child_z["radius"])
                # We clamp new_cx, new_cy to be within max_dist of child_cx, child_cy
                max_d = max(0.0, new_r - child_z["radius"])
                cx_dx = new_cx - child_z["center_x"]
                cy_dy = new_cy - child_z["center_y"]
                d = math.sqrt(cx_dx * cx_dx + cy_dy * cy_dy)
                if d > max_d and d > 1e-9:
                    scale = max_d / d
                    new_cx = child_z["center_x"] + cx_dx * scale
                    new_cy = child_z["center_y"] + cy_dy * scale

            # Update in-place without undo push (push on release)
            self.dm.current_match["zones"][idx]["center_x"] = round(new_cx, 6)
            self.dm.current_match["zones"][idx]["center_y"] = round(new_cy, 6)
            self.dm.current_match["zones"][idx]["radius"] = round(new_r, 6)
            self.canvas.redraw()

        elif self._mode == self.MODE_RESIZE and self._orig_zone is not None:
            idx = self._orig_zone_idx
            z = self._orig_zone
            dx = nx - z.center_x
            dy = ny - z.center_y
            new_r = max(0.002, math.sqrt(dx * dx + dy * dy))
            
            # Constraints for resizing
            zones = self.dm.current_match.get("zones", [])
            parent_z = next((oz for i, oz in enumerate(zones) if i != idx and oz["phase"] == z.phase - 1), None)
            child_z  = next((oz for i, oz in enumerate(zones) if i != idx and oz["phase"] == z.phase + 1), None)
            
            # Cannot resize larger than parent allows
            if parent_z:
                # dist + new_r <= parent_r  => new_r <= parent_r - dist
                d_parent = math.sqrt((z.center_x - parent_z["center_x"])**2 + (z.center_y - parent_z["center_y"])**2)
                max_r = max(0.002, parent_z["radius"] - d_parent)
                new_r = min(new_r, max_r)
                
            # Cannot resize smaller than child needs
            if child_z:
                # dist + child_r <= new_r => new_r >= dist + child_r
                d_child = math.sqrt((z.center_x - child_z["center_x"])**2 + (z.center_y - child_z["center_y"])**2)
                min_r = d_child + child_z["radius"]
                new_r = max(new_r, min_r)
                
            self.dm.current_match["zones"][idx]["radius"] = round(new_r, 6)
            self.canvas.redraw()

    def on_release(self, event):
        if self._mode in (self.MODE_MOVE, self.MODE_RESIZE) and self._orig_zone is not None:
            idx = self._orig_zone_idx
            current_zones = self.dm.current_match["zones"]
            if idx is not None and idx < len(current_zones):
                # Push undo with original state
                self.dm._undo_stack.append(
                    __import__("copy").deepcopy(
                        {**self.dm.current_match,
                         "zones": [z.copy() for z in current_zones]}
                    )
                )
                self.dm._dirty = True
                self.dm._notify()

        if self._mode == self.MODE_MOVE and self.canvas.selected_fp_endpoint:
            self.dm._dirty = True
            self.dm._notify()

        self._mode = self.MODE_IDLE
        self._orig_zone = None
        self._orig_zone_idx = None
        self._drag_start_norm = None

    def cancel(self):
        if self._orig_zone is not None and self._orig_zone_idx is not None:
            # Restore original position
            idx = self._orig_zone_idx
            z = self._orig_zone
            zones = self.dm.current_match.get("zones", [])
            if idx < len(zones):
                zones[idx]["center_x"] = z.center_x
                zones[idx]["center_y"] = z.center_y
                zones[idx]["radius"]   = z.radius
        self._mode = self.MODE_IDLE
        self._orig_zone = None
        self.canvas.redraw()


# ─── Flight Path Tool ─────────────────────────────────────────────────────────

class FlightPathTool(BaseTool):
    """
    Click 1: place start endpoint (shown as dot).
    Click 2: place end endpoint, commit flight path.
    """

    def __init__(self, canvas, dm):
        super().__init__(canvas, dm)
        self._start: Optional[Tuple[float, float]] = None
        self._preview_end: Optional[Tuple[float, float]] = None

    def cursor(self) -> str:
        return "crosshair"

    def on_press(self, event):
        nx, ny = self.canvas.canvas_to_norm(event.x, event.y)
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))

        if self._start is None:
            self._start = (nx, ny)
            self._preview_end = (nx, ny)
            self.canvas.redraw()
        else:
            # Commit
            sx, sy = self._start
            self.dm.set_flight_path(sx, sy, nx, ny)
            self._start = None
            self._preview_end = None
            # Switch back to select tool
            self.canvas.app.set_tool("select")

    def on_drag(self, event): pass

    def on_release(self, event): pass

    def on_move(self, event):
        if self._start is not None:
            nx, ny = self.canvas.canvas_to_norm(event.x, event.y)
            self._preview_end = (max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny)))
            self.canvas.redraw()

    def draw_preview(self, draw_fn):
        """Called by canvas during redraw to draw the in-progress path."""
        if self._start and self._preview_end:
            draw_fn(self._start, self._preview_end)

    def cancel(self):
        self._start = None
        self._preview_end = None
        self.canvas.redraw()


# ─── Circle Tool ─────────────────────────────────────────────────────────────

class CircleTool(BaseTool):
    """
    Click = place center.
    Drag  = set radius with live ring preview.
    Release = commit zone.
    """

    def __init__(self, canvas, dm, phase: int = 1):
        super().__init__(canvas, dm)
        self.phase = phase
        self._center: Optional[Tuple[float, float]] = None
        self._radius_norm: float = 0.0

    def cursor(self) -> str:
        return "crosshair"

    def on_press(self, event):
        nx, ny = self.canvas.canvas_to_norm(event.x, event.y)
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))
        self._center = (nx, ny)
        self._radius_norm = 0.0
        self.canvas.redraw()

    def on_drag(self, event):
        if self._center is None:
            return
        nx, ny = self.canvas.canvas_to_norm(event.x, event.y)
        dx = nx - self._center[0]
        dy = ny - self._center[1]
        self._radius_norm = max(0.002, math.sqrt(dx * dx + dy * dy))
        
        # Clamp to parent
        zones = self.dm.current_match.get("zones", []) if self.dm.current_match else []
        parent_z = next((z for z in zones if z["phase"] == self.phase - 1), None)
        if parent_z:
            self._center = (self._center[0], self._center[1])
            cx, cy, r = clamp_zone_to_parent(
                self._center[0], self._center[1], self._radius_norm,
                parent_z["center_x"], parent_z["center_y"], parent_z["radius"]
            )
            self._center = (cx, cy)
            self._radius_norm = r
            
        self.canvas.redraw()

    def on_release(self, event):
        if self._center is None:
            return

        # ── Single annotation constraint ─────────────────────────────────────
        # Prevent creating a second zone for the same phase.
        existing = self.dm.current_match.get("zones", []) if self.dm.current_match else []
        if any(z.get("phase") == self.phase for z in existing):
            self._center = None
            self._radius_norm = 0.0
            self.canvas.redraw()
            self.canvas.app.set_tool("select")
            return

        # If radius too tiny (just a click, no drag), use reference radius
        if self._radius_norm < 0.005:
            from zone_manager import PHASE_RADII_NORM
            self._radius_norm = PHASE_RADII_NORM.get(self.phase, 0.05)
            
            # Apply clamping again just in case reference radius is too big
            zones = self.dm.current_match.get("zones", []) if self.dm.current_match else []
            parent_z = next((z for z in zones if z["phase"] == self.phase - 1), None)
            if parent_z:
                cx, cy, r = clamp_zone_to_parent(
                    self._center[0], self._center[1], self._radius_norm,
                    parent_z["center_x"], parent_z["center_y"], parent_z["radius"]
                )
                self._center = (cx, cy)
                self._radius_norm = r

        zone = Zone(
            phase=self.phase,
            center_x=self._center[0],
            center_y=self._center[1],
            radius=self._radius_norm,
        )
        idx = self.dm.add_zone(zone)
        self.canvas.selected_index = idx
        self._center = None
        self._radius_norm = 0.0
        # Switch to select after placing
        self.canvas.app.set_tool("select")

    def draw_preview(self, draw_fn):
        """Called by canvas to draw the in-progress circle."""
        if self._center:
            draw_fn(self._center, self._radius_norm, self.phase)

    def cancel(self):
        self._center = None
        self._radius_norm = 0.0
        self.canvas.redraw()
