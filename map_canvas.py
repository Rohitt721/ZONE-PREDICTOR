"""
map_canvas.py
The central map display widget.
Handles zoom/pan, coordinate conversion, and overlay rendering.
"""

import math
import tkinter as tk
from tkinter import ttk
from typing import Optional, TYPE_CHECKING

from PIL import Image, ImageTk

from zone_manager import PHASE_COLORS, FLIGHT_PATH_COLOR
from annotation_tools import SelectTool, FlightPathTool, CircleTool

if TYPE_CHECKING:
    from app import BGMIZoneAnnotator
    from dataset_manager import DatasetManager


# ─── Drawing constants ────────────────────────────────────────────────────────

CIRCLE_WIDTH      = 2      # border width in pixels (scaled with zoom)
CENTER_DOT_RADIUS = 5      # pixels
LABEL_FONT_BASE   = 11     # base font size (scales with zoom)
FP_WIDTH          = 3      # flight path line width
ENDPOINT_RADIUS   = 6      # flight path endpoint dot radius
GRID_CELLS        = 10     # for snap-to-grid (10×10)


class MapCanvas(tk.Canvas):
    """
    A resizable canvas that renders the Erangel map with zone overlays.

    Coordinate systems:
      normalized (nx, ny) ∈ [0,1] — stored in JSON
      canvas pixel (cx, cy)        — runtime display coords

    Conversion:
      cx = offset_x + nx * map_w * zoom
      cy = offset_y + ny * map_h * zoom
    """

    def __init__(self, parent, map_path: str, app: "BGMIZoneAnnotator"):
        super().__init__(parent, bg="#0d0d1a", highlightthickness=0, cursor="crosshair")
        self.app = app
        self.dm: "DatasetManager" = app.dm

        # ── Map image state ────────────────────────────────────────────────
        self.pil_image: Optional[Image.Image] = None
        self._tk_image: Optional[ImageTk.PhotoImage] = None
        self._map_w: int = 1
        self._map_h: int = 1

        # ── Viewport state ─────────────────────────────────────────────────
        self.zoom: float = 1.0
        self.offset_x: float = 0.0   # canvas pixels from left edge to map left
        self.offset_y: float = 0.0   # canvas pixels from top edge to map top

        # ── Interaction state ──────────────────────────────────────────────
        self.selected_index: Optional[int] = None
        self.selected_fp_endpoint: Optional[str] = None  # "start" | "end"
        self._pan_start: Optional[tuple] = None

        # ── Visibility toggles (not serialized) ───────────────────────────
        self.show_flight_path: bool = True
        self.show_zones: bool = True
        self.show_labels: bool = True
        self.show_centers: bool = True
        self.show_grid: bool = False
        self.snap_to_grid: bool = False
        self.phase_visible: dict = {i: True for i in range(1, 9)}

        # ── Prediction overlay (from predictor.py, not persisted) ─────────────
        self.predictions: list = []      # list of Zone objects
        self.show_predictions: bool = True

        # ── Redraw throttle ───────────────────────────────────────────────
        self._redraw_pending: bool = False
        self._fitted: bool = False   # True once fit_map ran with real dimensions

        # ── Tool (set via app.set_tool) ───────────────────────────────────
        self.active_tool = SelectTool(self, self.dm)

        # ── Bind events ───────────────────────────────────────────────────
        self._bind_events()

        # Redraw on resize
        self.bind("<Configure>", self._on_resize)

        # Load map — defer fit until after the window is fully drawn
        if map_path:
            self.load_map(map_path)

    # ─── Map Loading ──────────────────────────────────────────────────────────

    def load_map(self, path: str):
        """Load the PIL image; defer fit until the canvas has real dimensions."""
        self.pil_image = Image.open(path).convert("RGB")
        self._map_w, self._map_h = self.pil_image.size
        self._fitted = False
        # Schedule fit after the event loop has rendered the window
        self.after_idle(self._deferred_fit)

    def _deferred_fit(self):
        """Called via after_idle — by now the canvas has real pixel dimensions."""
        cw = self.winfo_width()
        ch = self.winfo_height()
        if cw < 50 or ch < 50:
            # Still not ready, try again shortly
            self.after(50, self._deferred_fit)
            return
        self.fit_map()

    def fit_map(self):
        """Fit the entire map into the current canvas size."""
        cw = self.winfo_width()
        ch = self.winfo_height()
        # Guard: use sensible fallback if dimensions are not ready yet
        if cw < 50:  cw = 900
        if ch < 50:  ch = 650
        if self._map_w == 0 or self._map_h == 0:
            return
        scale_x = cw / self._map_w
        scale_y = ch / self._map_h
        self.zoom = min(scale_x, scale_y)
        # Center the map
        displayed_w = self._map_w * self.zoom
        displayed_h = self._map_h * self.zoom
        self.offset_x = (cw - displayed_w) / 2
        self.offset_y = (ch - displayed_h) / 2
        self._fitted = True
        self.schedule_redraw()

    # ─── Coordinate Conversion ────────────────────────────────────────────────

    def norm_to_canvas(self, nx: float, ny: float) -> tuple:
        cx = self.offset_x + nx * self._map_w * self.zoom
        cy = self.offset_y + ny * self._map_h * self.zoom
        return (cx, cy)

    def canvas_to_norm(self, cx: float, cy: float) -> tuple:
        if self._map_w * self.zoom == 0:
            return (0.0, 0.0)
        nx = (cx - self.offset_x) / (self._map_w * self.zoom)
        ny = (cy - self.offset_y) / (self._map_h * self.zoom)
        return (nx, ny)

    def norm_radius_to_canvas(self, nr: float) -> float:
        """Normalized radius → canvas pixels (based on map width)."""
        return nr * self._map_w * self.zoom

    def canvas_radius_to_norm(self, cr: float) -> float:
        denom = self._map_w * self.zoom
        return cr / denom if denom > 0 else 0.0

    def snap(self, nx: float, ny: float) -> tuple:
        """Snap normalized coordinates to grid if enabled."""
        if self.snap_to_grid:
            nx = round(nx * GRID_CELLS) / GRID_CELLS
            ny = round(ny * GRID_CELLS) / GRID_CELLS
        return (max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny)))

    # ─── Zoom / Pan ───────────────────────────────────────────────────────────

    def zoom_in(self, factor: float = 1.25):
        cw = self.winfo_width() / 2
        ch = self.winfo_height() / 2
        self._do_zoom(factor, cw, ch)

    def zoom_out(self, factor: float = 0.8):
        cw = self.winfo_width() / 2
        ch = self.winfo_height() / 2
        self._do_zoom(factor, cw, ch)

    def _do_zoom(self, factor: float, pivot_cx: float, pivot_cy: float):
        new_zoom = max(0.1, min(20.0, self.zoom * factor))
        # Keep the pivot point fixed
        ratio = new_zoom / self.zoom
        self.offset_x = pivot_cx - ratio * (pivot_cx - self.offset_x)
        self.offset_y = pivot_cy - ratio * (pivot_cy - self.offset_y)
        self.zoom = new_zoom
        self.schedule_redraw()

    def _on_wheel(self, event):
        factor = 1.15 if event.delta > 0 else (1 / 1.15)
        self._do_zoom(factor, event.x, event.y)

    def _on_pan_start(self, event):
        self._pan_start = (event.x, event.y)

    def _on_pan_drag(self, event):
        if self._pan_start:
            dx = event.x - self._pan_start[0]
            dy = event.y - self._pan_start[1]
            self.offset_x += dx
            self.offset_y += dy
            self._pan_start = (event.x, event.y)
            self.schedule_redraw()

    def _on_pan_end(self, event):
        self._pan_start = None

    # ─── Event Binding ────────────────────────────────────────────────────────

    def _bind_events(self):
        # Zoom
        self.bind("<MouseWheel>", self._on_wheel)
        # Pan — middle mouse button
        self.bind("<ButtonPress-2>",   self._on_pan_start)
        self.bind("<B2-Motion>",       self._on_pan_drag)
        self.bind("<ButtonRelease-2>", self._on_pan_end)
        # Pan — right mouse button (alternative)
        self.bind("<ButtonPress-3>",   self._on_pan_start)
        self.bind("<B3-Motion>",       self._on_pan_drag)
        self.bind("<ButtonRelease-3>", self._on_pan_end)

        # Tool events (left mouse button)
        self.bind("<ButtonPress-1>",   self._tool_press)
        self.bind("<B1-Motion>",       self._tool_drag)
        self.bind("<ButtonRelease-1>", self._tool_release)
        self.bind("<Motion>",          self._tool_move)

        # Keyboard
        self.bind("<Delete>",   self._on_delete)
        self.bind("<Escape>",   self._on_escape)
        self.bind("<FocusIn>",  lambda e: None)

    def _tool_press(self, event):
        self.focus_set()
        self.active_tool.on_press(event)
        self._update_inspector(event)

    def _tool_drag(self, event):
        self.active_tool.on_drag(event)
        self._update_inspector(event)

    def _tool_release(self, event):
        self.active_tool.on_release(event)
        self._update_inspector(event)

    def _tool_move(self, event):
        self.active_tool.on_move(event)
        self._update_inspector(event)

    def _on_delete(self, event):
        if self.selected_index is not None:
            self.dm.delete_zone(self.selected_index)
            self.selected_index = None

    def _on_escape(self, event):
        self.active_tool.cancel()
        self.selected_index = None
        self.selected_fp_endpoint = None
        self.redraw()

    def _on_resize(self, event):
        # On first real resize (window fully shown), re-fit the map
        if not self._fitted and self.pil_image is not None:
            cw = event.width
            ch = event.height
            if cw > 50 and ch > 50:
                self.fit_map()
                return
        self.schedule_redraw()

    def _update_inspector(self, event):
        nx, ny = self.canvas_to_norm(event.x, event.y)
        if hasattr(self.app, "status_bar"):
            self.app.status_bar.update_cursor(nx, ny, self.zoom)
        if hasattr(self.app, "right_panel"):
            self.app.right_panel.update_inspector(nx, ny, self.selected_index)

    # ─── Rendering ────────────────────────────────────────────────────────────

    def schedule_redraw(self):
        """Throttle redraws to avoid flooding the event loop."""
        if not self._redraw_pending:
            self._redraw_pending = True
            self.after(16, self._do_redraw)  # ~60 fps cap

    def _do_redraw(self):
        self._redraw_pending = False
        self.redraw()

    def redraw(self):
        """Full redraw: map image + all overlays."""
        self.delete("all")
        self._draw_map()
        if self.show_grid:
            self._draw_grid()
        if self.show_flight_path:
            self._draw_flight_path()
        if self.show_predictions and self.predictions:
            self._draw_predictions()
        if self.show_zones:
            self._draw_zones()
        self._draw_tool_preview()

    def _draw_map(self):
        if self.pil_image is None:
            self._draw_placeholder()
            return
        cw = self.winfo_width()  or 800
        ch = self.winfo_height() or 600
        dw = int(self._map_w * self.zoom)
        dh = int(self._map_h * self.zoom)
        if dw < 1 or dh < 1:
            return
        try:
            resized = self.pil_image.resize((dw, dh), Image.LANCZOS)
            self._tk_image = ImageTk.PhotoImage(resized)
            self.create_image(
                int(self.offset_x), int(self.offset_y),
                anchor="nw", image=self._tk_image, tags="map"
            )
        except Exception as e:
            print(f"[MapCanvas] draw error: {e}")

    def _draw_placeholder(self):
        self.create_rectangle(
            self.offset_x, self.offset_y,
            self.offset_x + self._map_w * self.zoom,
            self.offset_y + self._map_h * self.zoom,
            fill="#1a2a1a", outline="#2a4a2a", width=2
        )
        self.create_text(
            self.winfo_width() // 2, self.winfo_height() // 2,
            text="No map loaded\nFile → Open Map",
            fill="#4a8a4a", font=("Segoe UI", 18), justify="center"
        )

    def _draw_grid(self):
        cw = self.winfo_width()
        ch = self.winfo_height()
        for i in range(GRID_CELLS + 1):
            t = i / GRID_CELLS
            x1, y1 = self.norm_to_canvas(t, 0)
            x2, y2 = self.norm_to_canvas(t, 1)
            self.create_line(x1, y1, x2, y2, fill="#333355", dash=(4, 8))
            x1, y1 = self.norm_to_canvas(0, t)
            x2, y2 = self.norm_to_canvas(1, t)
            self.create_line(x1, y1, x2, y2, fill="#333355", dash=(4, 8))

    def _draw_flight_path(self):
        fp = self.dm.get_flight_path()
        if fp is None or not fp.visible:
            return
        sx, sy = self.norm_to_canvas(fp.start_x, fp.start_y)
        ex, ey = self.norm_to_canvas(fp.end_x, fp.end_y)
        color = FLIGHT_PATH_COLOR
        w = max(2, int(FP_WIDTH * self.zoom * 0.5))

        # Main line (no shadow — Tkinter has no alpha support)
        self.create_line(sx, sy, ex, ey, fill="#000000", width=w + 3, dash=(12, 6))
        self.create_line(sx, sy, ex, ey, fill=color, width=w + 1, dash=(12, 6), tags="fp")

        # Start endpoint (green)
        r = max(ENDPOINT_RADIUS, int(ENDPOINT_RADIUS * self.zoom * 0.3))
        sel_start = (self.selected_fp_endpoint == "start")
        self.create_oval(sx - r, sy - r, sx + r, sy + r,
                         fill="#00E676", outline="#FFFFFF" if sel_start else color,
                         width=2, tags="fp_start")
        # End endpoint (red)
        sel_end = (self.selected_fp_endpoint == "end")
        self.create_oval(ex - r, ey - r, ex + r, ey + r,
                         fill="#FF5252", outline="#FFFFFF" if sel_end else color,
                         width=2, tags="fp_end")

        # Labels
        if self.show_labels:
            self.create_text(sx - 12, sy - 12, text="▶ START", fill="#00E676",
                             font=("Segoe UI", 9, "bold"), anchor="se")
            self.create_text(ex + 12, ey - 12, text="END ●", fill="#FF5252",
                             font=("Segoe UI", 9, "bold"), anchor="sw")

    def _draw_predictions(self):
        """Draw predicted zones as dashed, stippled overlays."""
        for pred in self.predictions:
            if not self.phase_visible.get(pred.phase, True):
                continue
            self._draw_prediction_zone(pred)

    def _draw_prediction_zone(self, zone):
        """Single predicted zone: dashed ring + stipple dot + label."""
        cx, cy = self.norm_to_canvas(zone.center_x, zone.center_y)
        rp = self.norm_radius_to_canvas(zone.radius)
        color = zone.color()

        # Outer dashed ring (wider, dimmer)
        self.create_oval(
            cx - rp, cy - rp, cx + rp, cy + rp,
            outline=color, width=2, fill="", dash=(8, 6),
            tags=f"pred_{zone.phase}"
        )
        # Second inner ring to give depth
        if rp > 8:
            self.create_oval(
                cx - rp + 4, cy - rp + 4, cx + rp - 4, cy + rp - 4,
                outline=color, width=1, fill="", dash=(4, 10),
                tags=f"pred_{zone.phase}_inner"
            )

        # Centre marker (hollow diamond shape via two lines)
        mr = max(4, CENTER_DOT_RADIUS)
        self.create_oval(cx - mr, cy - mr, cx + mr, cy + mr,
                         fill="", outline=color, width=2,
                         tags=f"pred_{zone.phase}_center")
        # Cross
        cl = mr + 5
        self.create_line(cx - cl, cy, cx + cl, cy, fill=color, width=1, dash=(3, 3))
        self.create_line(cx, cy - cl, cx, cy + cl, fill=color, width=1, dash=(3, 3))

        # Label: "~P{N}" with "~" meaning predicted
        if self.show_labels:
            fs = max(8, min(14, int(LABEL_FONT_BASE * self.zoom * 0.4)))
            self.create_text(
                cx + rp * 0.707 + 5,
                cy - rp * 0.707 - 5,
                text=f"~P{zone.phase}",
                fill=color,
                font=("Segoe UI", fs, "bold"),
                anchor="sw",
                tags=f"pred_label_{zone.phase}"
            )

    def _draw_zones(self):
        zones = self.dm.get_zones()
        for i, zone in enumerate(zones):
            if not zone.visible or not self.phase_visible.get(zone.phase, True):
                continue
            self._draw_zone(zone, i, selected=(i == self.selected_index))


    def _draw_zone(self, zone, index: int, selected: bool = False):
        cx, cy = self.norm_to_canvas(zone.center_x, zone.center_y)
        rp = self.norm_radius_to_canvas(zone.radius)
        color = zone.color()
        lw = (4 if selected else 2)   # always at least 2px regardless of zoom
        outline_color = "#FFFFFF" if selected else color

        # Circle
        self.create_oval(
            cx - rp, cy - rp, cx + rp, cy + rp,
            outline=outline_color, width=lw,
            fill="", tags=f"zone_{index}"
        )

        # Selection glow (extra ring)
        if selected:
            self.create_oval(
                cx - rp - 4, cy - rp - 4, cx + rp + 4, cy + rp + 4,
                outline="#AAAAAA", width=1, fill="", tags=f"zone_{index}_glow"
            )

        # Center marker
        if self.show_centers:
            mr = max(3, CENTER_DOT_RADIUS)
            self.create_oval(cx - mr, cy - mr, cx + mr, cy + mr,
                             fill=color, outline="#000000", width=1,
                             tags=f"zone_{index}_center")
            # Crosshair lines
            cl = mr + 4
            self.create_line(cx - cl, cy, cx + cl, cy, fill=color, width=1)
            self.create_line(cx, cy - cl, cx, cy + cl, fill=color, width=1)

        # Phase label
        if self.show_labels:
            fs = max(8, min(16, int(LABEL_FONT_BASE * self.zoom * 0.4)))
            label = f"P{zone.phase}"
            self.create_text(
                cx + rp * 0.707 + 5,
                cy - rp * 0.707 - 5,
                text=label, fill=color,
                font=("Segoe UI", fs, "bold"),
                anchor="sw"
            )
            # Radius info
            if selected or self.zoom > 1.5:
                rm = zone.radius_meters()
                self.create_text(
                    cx, cy + rp + 14,
                    text=f"{rm:.0f}m", fill=color,
                    font=("Segoe UI", max(7, fs - 2)),
                    anchor="n"
                )

    def _draw_tool_preview(self):
        """Let the active tool draw any in-progress overlay."""
        tool = self.active_tool

        if isinstance(tool, FlightPathTool):
            def draw_fp_preview(start_norm, end_norm):
                sx, sy = self.norm_to_canvas(*start_norm)
                ex, ey = self.norm_to_canvas(*end_norm)
                self.create_line(sx, sy, ex, ey,
                                 fill=FLIGHT_PATH_COLOR, width=2, dash=(8, 4))
                r = ENDPOINT_RADIUS
                self.create_oval(sx - r, sy - r, sx + r, sy + r,
                                 fill="#00E676", outline="#FFFFFF", width=1)
            tool.draw_preview(draw_fp_preview)

        elif isinstance(tool, CircleTool):
            def draw_circle_preview(center_norm, radius_norm, phase):
                cx, cy = self.norm_to_canvas(*center_norm)
                rp = self.norm_radius_to_canvas(radius_norm)
                color = PHASE_COLORS.get(phase, "#FFFFFF")
                self.create_oval(cx - rp, cy - rp, cx + rp, cy + rp,
                                 outline=color, width=2, fill="", dash=(6, 4))
                mr = CENTER_DOT_RADIUS
                self.create_oval(cx - mr, cy - mr, cx + mr, cy + mr,
                                 fill=color, outline="#000", width=1)
            tool.draw_preview(draw_circle_preview)
