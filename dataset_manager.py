"""
dataset_manager.py
Match lifecycle management: CRUD, undo/redo, and export operations.
Acts as the single source of truth for the current match state.
"""

import copy
import json
from pathlib import Path
from typing import Optional, List, Callable

import storage
from flightpath import FlightPath
from zone_manager import Zone

MAX_UNDO = 50


class DatasetManager:
    """
    Manages the currently open match and the full match dataset.
    UI components read state from here; all mutations go through here.
    """

    def __init__(self):
        self.current_match: Optional[dict] = None
        self._undo_stack: List[dict] = []
        self._redo_stack: List[dict] = []
        self._dirty: bool = False           # unsaved changes flag
        self._on_change_callbacks: List[Callable] = []

    # ─── Observer ─────────────────────────────────────────────────────────────

    def register_on_change(self, cb: Callable):
        """Register a callback to be called after any state mutation."""
        self._on_change_callbacks.append(cb)

    def _notify(self):
        for cb in self._on_change_callbacks:
            try:
                cb()
            except Exception:
                pass

    # ─── Match Lifecycle ──────────────────────────────────────────────────────

    def new_match(self) -> dict:
        """Create and activate a blank match."""
        match_id = storage.get_next_match_id()
        self.current_match = {
            "match_id": match_id,
            "flight_path": None,
            "zones": [],
        }
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._dirty = False
        self._notify()
        return self.current_match

    def open_match(self, match_id: str) -> bool:
        """Load a saved match. Returns True on success."""
        data = storage.load_match(match_id)
        if data is None:
            return False
        self.current_match = data
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._dirty = False
        self._notify()
        return True

    def save_current(self) -> Optional[Path]:
        """Persist current match to disk."""
        if self.current_match is None:
            return None
        path = storage.save_match(self.current_match)
        self._dirty = False
        return path

    def delete_current_match(self) -> bool:
        """Delete current match file, then start a new blank match."""
        if self.current_match is None:
            return False
        mid = self.current_match["match_id"]
        result = storage.delete_match_file(mid)
        self.new_match()
        return result

    def delete_match_by_id(self, match_id: str) -> bool:
        return storage.delete_match_file(match_id)

    def list_matches(self) -> List[dict]:
        return storage.list_matches()

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def match_id(self) -> Optional[str]:
        return self.current_match["match_id"] if self.current_match else None

    # ─── Undo / Redo ──────────────────────────────────────────────────────────

    def _push_undo(self):
        """Snapshot current state before a mutation."""
        if self.current_match is None:
            return
        self._undo_stack.append(copy.deepcopy(self.current_match))
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> bool:
        if not self._undo_stack or self.current_match is None:
            return False
        self._redo_stack.append(copy.deepcopy(self.current_match))
        self.current_match = self._undo_stack.pop()
        self._dirty = True
        self._notify()
        return True

    def redo(self) -> bool:
        if not self._redo_stack or self.current_match is None:
            return False
        self._undo_stack.append(copy.deepcopy(self.current_match))
        self.current_match = self._redo_stack.pop()
        self._dirty = True
        self._notify()
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    # ─── Flight Path ──────────────────────────────────────────────────────────

    def set_flight_path(self, sx: float, sy: float, ex: float, ey: float):
        """Set or replace the flight path."""
        self._push_undo()
        self.current_match["flight_path"] = {
            "start_x": round(sx, 6), "start_y": round(sy, 6),
            "end_x":   round(ex, 6), "end_y":   round(ey, 6),
        }
        self._dirty = True
        self._notify()

    def clear_flight_path(self):
        self._push_undo()
        self.current_match["flight_path"] = None
        self._dirty = True
        self._notify()

    def get_flight_path(self) -> Optional[FlightPath]:
        fp = self.current_match.get("flight_path") if self.current_match else None
        return FlightPath.from_dict(fp) if fp else None

    # ─── Zones ────────────────────────────────────────────────────────────────

    def get_zones(self) -> List[Zone]:
        if not self.current_match:
            return []
        return [Zone.from_dict(z) for z in self.current_match.get("zones", [])]

    def add_zone(self, zone: Zone) -> int:
        """Add zone and return its index."""
        self._push_undo()
        self.current_match["zones"].append(zone.to_dict())
        self._dirty = True
        self._notify()
        return len(self.current_match["zones"]) - 1

    def update_zone(self, index: int, zone: Zone):
        self._push_undo()
        self.current_match["zones"][index] = zone.to_dict()
        self._dirty = True
        self._notify()

    def delete_zone(self, index: int):
        self._push_undo()
        self.current_match["zones"].pop(index)
        self._dirty = True
        self._notify()

    def move_zone_up(self, index: int) -> int:
        """Move zone earlier in the list (lower phase index). Returns new index."""
        if index <= 0:
            return index
        self._push_undo()
        zones = self.current_match["zones"]
        zones[index - 1], zones[index] = zones[index], zones[index - 1]
        self._dirty = True
        self._notify()
        return index - 1

    def move_zone_down(self, index: int) -> int:
        zones = self.current_match["zones"]
        if index >= len(zones) - 1:
            return index
        self._push_undo()
        zones[index], zones[index + 1] = zones[index + 1], zones[index]
        self._dirty = True
        self._notify()
        return index + 1

    def zone_count(self) -> int:
        return len(self.current_match.get("zones", [])) if self.current_match else 0

    def update_zone_visibility(self, index: int, visible: bool):
        """Toggle visibility without pushing undo (display-only state)."""
        zones = self.current_match.get("zones", [])
        if 0 <= index < len(zones):
            # Store visibility in a separate in-memory dict (not serialized)
            pass  # handled by zone objects in canvas

    # ─── Export ───────────────────────────────────────────────────────────────

    def export_full_dataset(self, output_path: Path) -> int:
        return storage.export_full_dataset(output_path)

    def export_training_data(self, output_path: Path) -> int:
        return storage.export_training_data(output_path)

    def export_match_png(self, canvas_widget, output_path: Path):
        """Render the current annotated map to a PNG using PIL."""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import zone_manager as zm

            # Use the canvas's underlying PIL image (full resolution)
            if not hasattr(canvas_widget, "pil_image") or canvas_widget.pil_image is None:
                return False

            img = canvas_widget.pil_image.copy().convert("RGBA")
            w, h = img.size
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Draw flight path
            fp = self.get_flight_path()
            if fp and fp.visible:
                sx = int(fp.start_x * w)
                sy = int(fp.start_y * h)
                ex = int(fp.end_x * w)
                ey = int(fp.end_y * h)
                draw.line([(sx, sy), (ex, ey)], fill=(41, 182, 246, 220), width=max(3, w//300))
                r = max(5, w // 200)
                draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(41, 182, 246, 255))
                draw.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(255, 100, 100, 255))

            # Draw zones
            for zone in self.get_zones():
                if not zone.visible:
                    continue
                cx = int(zone.center_x * w)
                cy = int(zone.center_y * h)
                rp = int(zone.radius * w)
                fa = zone.fill_alpha()
                border = tuple(int(x) for x in bytes.fromhex(zone.color()[1:])) + (220,)
                draw.ellipse([cx - rp, cy - rp, cx + rp, cy + rp],
                             fill=fa, outline=border, width=max(2, w // 400))
                # Center marker
                mr = max(4, w // 300)
                draw.ellipse([cx - mr, cy - mr, cx + mr, cy + mr], fill=border)
                # Phase label
                draw.text((cx + rp + 5, cy), f"P{zone.phase}", fill=border)

            # Composite and save
            result = Image.alpha_composite(img, overlay)
            result.convert("RGB").save(str(output_path), "PNG")
            return True
        except Exception as e:
            print(f"[Export PNG Error] {e}")
            return False
