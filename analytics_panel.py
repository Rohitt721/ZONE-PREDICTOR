"""
analytics_panel.py
Analytics dashboard with map-based visualizations for BGMI Zone Predictor.
Uses PIL (Pillow) to composite analytics overlays directly onto the Erangel map.
Layout: left sidebar (controls + stats) + right map canvas (primary visual).
"""
from __future__ import annotations

import math
import os
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

import storage
from zone_manager import PHASE_COLORS, PHASE_RADII_M, NUM_PHASES, ERANGEL_MAP_SIZE_M

# ── Theme ─────────────────────────────────────────────────────────────────────
BG       = "#0f0f1e"
BG2      = "#161628"
BG3      = "#1e1e35"
ACCENT   = "#4FC3F7"
FG       = "#e0e0e0"
FG_DIM   = "#888899"
BTN_BG   = "#252540"
BTN_HOV  = "#2e2e55"
BORDER   = "#2a2a4a"
RED      = "#FF5252"
GREEN    = "#69F0AE"
AMBER    = "#FFD740"
FONT     = ("Segoe UI", 10)
FONT_B   = ("Segoe UI", 10, "bold")
FONT_S   = ("Segoe UI", 9)


# ── Colour helpers ────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _heat_rgba(value: float, max_val: float) -> Tuple[int, int, int, int]:
    """Map 0…max_val → (r,g,b,a) heat colour (transparent for 0)."""
    if max_val == 0 or value == 0:
        return (0, 0, 0, 0)
    t = min(1.0, value / max_val)
    stops = [
        (0.00, (0,   0,  80)),
        (0.25, (0, 180, 255)),
        (0.50, (0, 240, 100)),
        (0.75, (255, 200,  0)),
        (1.00, (255,  60, 60)),
    ]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0
            r = int(c0[0] + (c1[0] - c0[0]) * f)
            g = int(c0[1] + (c1[1] - c0[1]) * f)
            b = int(c0[2] + (c1[2] - c0[2]) * f)
            a = int(80 + 160 * t)
            return (r, g, b, min(240, a))
    return (255, 60, 60, 240)


def _draw_arrowhead(draw: "ImageDraw.ImageDraw",
                    x1: int, y1: int, x2: int, y2: int,
                    col: Tuple[int, int, int], alpha: int = 200, size: int = 8):
    """Draw a filled arrowhead at (x2,y2) pointing from (x1,y1)."""
    dx, dy = x2 - x1, y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    ax = x2 - ux * size
    ay = y2 - uy * size
    p1 = (int(ax + px * size * 0.45), int(ay + py * size * 0.45))
    p2 = (int(ax - px * size * 0.45), int(ay - py * size * 0.45))
    draw.polygon([(x2, y2), p1, p2], fill=(*col, alpha))


# ── Scrollable frame widget ───────────────────────────────────────────────────

class _ScrollFrame(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG2, **kw)
        self._cv = tk.Canvas(self, bg=BG2, highlightthickness=0)
        self._sb = ttk.Scrollbar(self, orient="vertical", command=self._cv.yview)
        self.inner = tk.Frame(self._cv, bg=BG2)
        self.inner.bind("<Configure>",
            lambda e: self._cv.configure(scrollregion=self._cv.bbox("all")))
        self._cv.create_window((0, 0), window=self.inner, anchor="nw")
        self._cv.configure(yscrollcommand=self._sb.set)
        self._cv.pack(side="left", fill="both", expand=True)
        self._sb.pack(side="right", fill="y")
        # Bind wheel only on this canvas; check pointer position in handler
        self._cv.bind("<MouseWheel>", self._on_wheel)
        self.inner.bind("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, event):
        self._cv.yview_scroll(int(-1 * (event.delta / 120)), "units")



def _section(parent, text: str) -> tk.Frame:
    f = tk.Frame(parent, bg=BG2)
    tk.Label(f, text=text, bg=BG2, fg=ACCENT, font=FONT_B).pack(side="left", padx=6)
    tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(0, 4))
    return f


def _btn(parent, text, cmd, color=ACCENT):
    b = tk.Button(parent, text=text, command=cmd, bg=BTN_BG, fg=color,
                  activebackground=BTN_HOV, activeforeground=color,
                  relief="flat", bd=0, font=FONT, cursor="hand2", pady=5, padx=10)
    b.bind("<Enter>", lambda e: b.config(bg=BTN_HOV))
    b.bind("<Leave>", lambda e: b.config(bg=BTN_BG))
    return b


# ── Main panel ────────────────────────────────────────────────────────────────

class AnalyticsPanel(tk.Toplevel):
    """
    5-tab analytics Toplevel.
    Each tab: left sidebar (controls + compact stats) + right map canvas
    (primary visualization rendered via PIL compositing on the Erangel map).
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("📊 BGMI Zone Analytics Dashboard")
        self.configure(bg=BG)
        self.geometry("1150x720")
        self.minsize(900, 580)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._map_pil: Optional[Image.Image] = None
        self._load_map()

        # Cached analytics data
        self._matches: List[dict] = []
        self._acc_data: dict      = {}
        self._zone_hm:  dict      = {}
        self._fp_hm:    list      = []
        self._stats:    dict      = {}
        self._cov:      dict      = {}

        self._build_ui()
        self.refresh()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _on_close(self):
        self.destroy()

    def open_or_focus(self):
        self.deiconify(); self.lift(); self.focus_force()
        self.refresh()

    def _load_map(self):
        try:
            cfg = storage.load_config()
            path = cfg.get("map_path", "")
            if path and not os.path.isabs(path):
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
            if path and os.path.exists(path) and _PIL_OK:
                self._map_pil = Image.open(path).convert("RGB")
        except Exception as e:
            print(f"[Analytics] map load: {e}")

    # ── UI skeleton ───────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG3, height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📊  Zone Analytics Dashboard",
                 bg=BG3, fg=ACCENT, font=("Segoe UI", 14, "bold")).pack(side="left", padx=16, pady=10)
        _btn(hdr, "🔄  Refresh", self.refresh).pack(side="right", padx=12, pady=8)

        # Tab strip
        tbar = tk.Frame(self, bg=BG2, height=38)
        tbar.pack(fill="x"); tbar.pack_propagate(False)

        self._tab_labels = [
            "📈  Model Accuracy",
            "🗺  Zone Heatmap",
            "✈  Flight Paths",
            "📊  Match Statistics",
            "🔵  Zone Coverage",
        ]
        self._tab_btns: List[tk.Button] = []
        for i, lbl in enumerate(self._tab_labels):
            b = tk.Button(tbar, text=lbl, relief="flat", bd=0,
                          bg=BG2, fg=FG_DIM, font=FONT_S, cursor="hand2",
                          command=lambda idx=i: self._switch_tab(idx),
                          padx=14, pady=6)
            b.pack(side="left")
            self._tab_btns.append(b)

        # Tab content area
        self._content = tk.Frame(self, bg=BG)
        self._content.pack(fill="both", expand=True)

        self._tab_frames: List[tk.Frame] = []
        for builder in [
            self._build_accuracy_tab,
            self._build_zone_hm_tab,
            self._build_fp_hm_tab,
            self._build_stats_tab,
            self._build_coverage_tab,
        ]:
            f = tk.Frame(self._content, bg=BG)
            builder(f)
            self._tab_frames.append(f)

        self._switch_tab(0)

    def _switch_tab(self, idx: int):
        for i, f in enumerate(self._tab_frames):
            if i == idx: f.place(relx=0, rely=0, relwidth=1, relheight=1)
            else:         f.place_forget()
        for i, b in enumerate(self._tab_btns):
            b.config(bg=BG3 if i == idx else BG2,
                     fg=ACCENT if i == idx else FG_DIM)

    # ── Data refresh ──────────────────────────────────────────────────────────

    def refresh(self):
        import analytics as an
        self._matches = storage.list_matches()
        self._stats   = an.match_statistics(self._matches)
        self._cov     = an.zone_coverage(self._matches)
        self._zone_hm = an.zone_heatmap_data(self._matches, grid=60)
        self._fp_hm   = an.flight_path_heatmap_data(self._matches, grid=60)

        if len(self._matches) >= 2 and hasattr(self.app, "predictor"):
            try:
                self._acc_data = an.model_accuracy_stats(self.app.predictor, self._matches)
            except Exception as e:
                self._acc_data = {}
                print(f"[Analytics] accuracy: {e}")
        else:
            self._acc_data = {}

        self._render_all()

    def _render_all(self):
        self._render_accuracy()
        self._render_zone_heatmap()
        self._render_fp_heatmap()
        self._render_stats()
        self._render_coverage()

    # ── PIL map compositing ───────────────────────────────────────────────────

    def _composite(self, canvas: tk.Canvas, draw_fn):
        """
        Render map + overlay onto canvas.
        draw_fn(draw: ImageDraw, cw: int, ch: int) draws onto an RGBA overlay.
        """
        if not _PIL_OK:
            cw = canvas.winfo_width() or 600
            ch = canvas.winfo_height() or 500
            canvas.delete("all")
            canvas.create_text(cw // 2, ch // 2,
                               text="Pillow not installed.\nRun: pip install Pillow",
                               fill="#FFD740", font=FONT, justify="center")
            return

        cw = max(4, canvas.winfo_width()  or 600)
        ch = max(4, canvas.winfo_height() or 500)

        # Base: map image (slightly darkened) or solid dark bg
        if self._map_pil:
            base = self._map_pil.resize((cw, ch), Image.LANCZOS).convert("RGBA")
            # Slight darkening veil
            veil = Image.new("RGBA", (cw, ch), (0, 0, 16, 110))
            base = Image.alpha_composite(base, veil)
        else:
            base = Image.new("RGBA", (cw, ch), (13, 13, 26, 255))

        overlay = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw_fn(draw, cw, ch)

        photo = ImageTk.PhotoImage(Image.alpha_composite(base, overlay).convert("RGB"))
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas._photo_ref = photo      # prevent GC

    # ─────────────────────────────────────────────────────────────────────────
    # Tab 1 — Model Accuracy
    # ─────────────────────────────────────────────────────────────────────────

    def _build_accuracy_tab(self, parent: tk.Frame):
        left = tk.Frame(parent, bg=BG2, width=260); left.pack(side="left", fill="y")
        left.pack_propagate(False)
        sf = _ScrollFrame(left); sf.pack(fill="both", expand=True)
        parent._acc_table = sf.inner

        right = tk.Frame(parent, bg=BG); right.pack(fill="both", expand=True)
        mc = tk.Canvas(right, bg="#0d0d1a", highlightthickness=0)
        mc.pack(fill="both", expand=True, padx=4, pady=4)
        mc.bind("<Configure>", lambda e: self._render_accuracy_map())
        parent._acc_canvas = mc

    def _render_accuracy(self):
        parent = self._tab_frames[0]
        frame = parent._acc_table
        for w in frame.winfo_children(): w.destroy()

        n = len(self._matches)
        _section(frame, " MODEL ACCURACY").pack(fill="x", padx=8, pady=(10, 4))
        tk.Label(frame, text=f"Leave-one-out evaluation\n{n} match(es) in dataset",
                 bg=BG2, fg=FG_DIM, font=FONT_S, justify="left").pack(padx=10, pady=(0, 6), anchor="w")

        if n < 2:
            tk.Label(frame, text="⚠  Need ≥2 saved matches\nto evaluate accuracy.",
                     bg=BG2, fg=AMBER, font=FONT_S, justify="left").pack(padx=10, pady=8)
        else:
            for phase in range(1, NUM_PHASES + 1):
                d    = self._acc_data.get(phase, {})
                ph_n = d.get("n_samples", 0)
                avg  = d.get("avg_m")
                mn   = d.get("min_m")
                mx   = d.get("max_m")
                col  = PHASE_COLORS.get(phase, "#fff")
                rbg  = BG3 if phase % 2 == 0 else BG2
                row  = tk.Frame(frame, bg=rbg); row.pack(fill="x", padx=4, pady=1)
                tk.Label(row, text=f"P{phase}", bg=rbg, fg=col,
                         font=FONT_B, width=3).pack(side="left", padx=4)
                if avg is not None:
                    ec = GREEN if avg < 200 else (AMBER if avg < 500 else RED)
                    tk.Label(row, text=f"avg {avg:.0f}m",  bg=rbg, fg=ec,    font=FONT_B).pack(side="left")
                    tk.Label(row, text=f" ↕{mn:.0f}–{mx:.0f}m ({ph_n})",
                             bg=rbg, fg=FG_DIM, font=("Segoe UI", 8)).pack(side="left")
                else:
                    tk.Label(row, text="—", bg=rbg, fg=FG_DIM, font=FONT_S).pack(side="left")

        tk.Label(frame,
                 text="\nMap legend:\n  ●  Avg actual zone centre\n  ─  Per-phase avg circle\n  ×  Individual zone centres",
                 bg=BG2, fg=FG_DIM, font=("Segoe UI", 8), justify="left").pack(padx=10, pady=10, anchor="w")
        self._render_accuracy_map()

    def _render_accuracy_map(self):
        canvas = self._tab_frames[0]._acc_canvas
        matches = self._matches

        def draw_fn(d: ImageDraw.ImageDraw, cw: int, ch: int):
            # Collect per-phase actual positions
            per_phase: Dict[int, list] = {p: [] for p in range(1, NUM_PHASES + 1)}
            for m in matches:
                for z in m.get("zones", []):
                    ph = z.get("phase")
                    if 1 <= ph <= NUM_PHASES:
                        per_phase[ph].append(z)

            for phase in range(1, NUM_PHASES + 1):
                zones = per_phase[phase]
                if not zones:
                    continue
                col = _hex_to_rgb(PHASE_COLORS.get(phase, "#ffffff"))

                # Draw each actual zone faintly
                for z in zones:
                    px = int(z["center_x"] * cw)
                    py = int(z["center_y"] * ch)
                    rp = int(z.get("radius", 0) * cw)
                    if rp > 1:
                        d.ellipse([px - rp, py - rp, px + rp, py + rp],
                                  outline=(*col, 45), width=1)
                    d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=(*col, 100))

                # Average zone
                avg_cx = sum(z["center_x"] for z in zones) / len(zones)
                avg_cy = sum(z["center_y"] for z in zones) / len(zones)
                avg_r  = sum(z.get("radius", 0) for z in zones) / len(zones)
                apx = int(avg_cx * cw)
                apy = int(avg_cy * ch)
                arp = int(avg_r * cw)
                if arp > 1:
                    d.ellipse([apx - arp, apy - arp, apx + arp, apy + arp],
                              outline=(*col, 220), width=3)
                # Centre dot + crosshair
                r2 = 7
                d.ellipse([apx - r2, apy - r2, apx + r2, apy + r2],
                          fill=(*col, 255))
                d.line([apx - 14, apy, apx + 14, apy], fill=(*col, 200), width=1)
                d.line([apx, apy - 14, apx, apy + 14], fill=(*col, 200), width=1)
                # Label
                d.text((apx + arp + 6, apy - 10), f"P{phase}", fill=(*col, 230))

        self._composite(canvas, draw_fn)

    # ─────────────────────────────────────────────────────────────────────────
    # Tab 2 — Zone Heatmap
    # ─────────────────────────────────────────────────────────────────────────

    def _build_zone_hm_tab(self, parent: tk.Frame):
        left = tk.Frame(parent, bg=BG2, width=220); left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="Phase Filter", bg=BG2, fg=ACCENT, font=FONT_B).pack(padx=8, pady=(12,4))

        parent._zhm_phase = tk.IntVar(value=0)
        tk.Radiobutton(left, text="All phases combined", variable=parent._zhm_phase, value=0,
                       bg=BG2, fg=FG, selectcolor=BG3, activebackground=BG2,
                       font=FONT_S, indicatoron=False, relief="flat", bd=1,
                       command=self._render_zone_heatmap).pack(padx=8, pady=2, fill="x")
        for i in range(1, NUM_PHASES + 1):
            col = PHASE_COLORS.get(i, "#fff")
            tk.Radiobutton(left, text=f"Phase {i}", variable=parent._zhm_phase, value=i,
                           bg=BG2, fg=col, selectcolor=BG3, activebackground=BG2,
                           font=("Segoe UI", 9, "bold"), indicatoron=False, relief="flat", bd=1,
                           command=self._render_zone_heatmap).pack(padx=8, pady=1, fill="x")

        parent._zhm_show_circles = tk.BooleanVar(value=True)
        tk.Checkbutton(left, text="Show zone circles", variable=parent._zhm_show_circles,
                       bg=BG2, fg=FG, selectcolor=BG3, font=FONT_S, activebackground=BG2,
                       command=self._render_zone_heatmap).pack(padx=8, pady=8, anchor="w")

        parent._zhm_info = tk.Label(left, text="", bg=BG2, fg=FG_DIM,
                                    font=("Segoe UI", 8), wraplength=200, justify="left")
        parent._zhm_info.pack(padx=8, pady=4, anchor="w")

        # Colour legend (drawn on a small canvas)
        tk.Label(left, text="Density scale:", bg=BG2, fg=FG_DIM, font=("Segoe UI", 8)).pack(padx=8, anchor="w")
        leg = tk.Canvas(left, bg=BG2, height=14, width=200, highlightthickness=0)
        leg.pack(padx=8, pady=2)
        leg.bind("<Configure>", lambda e, c=leg: self._draw_legend(c))
        parent._zhm_legend = leg

        right = tk.Frame(parent, bg=BG); right.pack(fill="both", expand=True)
        mc = tk.Canvas(right, bg="#0d0d1a", highlightthickness=0)
        mc.pack(fill="both", expand=True, padx=4, pady=4)
        mc.bind("<Configure>", lambda e: self._render_zone_heatmap())
        parent._zhm_canvas = mc

    def _draw_legend(self, canvas: tk.Canvas):
        """Small tkinter-native gradient legend (no 8-char hex)."""
        canvas.delete("all")
        w = canvas.winfo_width() or 200
        steps = 40
        for i in range(steps):
            r, g, b, _ = _heat_rgba(i + 1, steps)
            colour = f"#{r:02x}{g:02x}{b:02x}"
            x0 = int(i * w / steps)
            x1 = int((i + 1) * w / steps)
            canvas.create_rectangle(x0, 0, x1, 14, fill=colour, outline="")
        canvas.create_text(2,  7, anchor="w", text="0",    fill="#888899", font=("Segoe UI", 7))
        canvas.create_text(w-2, 7, anchor="e", text="max", fill="#888899", font=("Segoe UI", 7))

    def _render_zone_heatmap(self):
        parent = self._tab_frames[1]
        canvas = parent._zhm_canvas
        phase_sel    = parent._zhm_phase.get()
        show_circles = parent._zhm_show_circles.get()

        # Merge or select grid
        if not self._zone_hm:
            def _empty(d, cw, ch):
                d.text((cw // 2 - 40, ch // 2 - 8), "No data yet.", fill=(180, 180, 180, 200))
            self._composite(canvas, _empty)
            return

        grid_size = len(next(iter(self._zone_hm.values())))
        if phase_sel == 0:
            grid = [[0] * grid_size for _ in range(grid_size)]
            for g in self._zone_hm.values():
                for r in range(grid_size):
                    for c in range(grid_size):
                        grid[r][c] += g[r][c]
        else:
            grid = self._zone_hm.get(phase_sel, [])

        if not grid:
            return
        max_v = max(max(row) for row in grid) or 1
        total = sum(sum(row) for row in grid)

        def draw_fn(d, cw, ch):
            cw_f, ch_f = float(cw), float(ch)
            for row in range(grid_size):
                for col in range(grid_size):
                    v = grid[row][col]
                    if v == 0:
                        continue
                    rgba = _heat_rgba(v, max_v)
                    x0, y0 = int(col * cw_f / grid_size), int(row * ch_f / grid_size)
                    x1, y1 = int((col + 1) * cw_f / grid_size), int((row + 1) * ch_f / grid_size)
                    d.rectangle([x0, y0, x1, y1], fill=rgba)

            # Zone circle outlines
            if show_circles:
                phases = [phase_sel] if phase_sel > 0 else list(range(1, NUM_PHASES + 1))
                for m in self._matches:
                    for z in m.get("zones", []):
                        if z.get("phase") not in phases:
                            continue
                        col = _hex_to_rgb(PHASE_COLORS.get(z["phase"], "#ffffff"))
                        px = int(z["center_x"] * cw)
                        py = int(z["center_y"] * ch)
                        rp = int(z.get("radius", 0) * cw)
                        if rp > 1:
                            d.ellipse([px - rp, py - rp, px + rp, py + rp],
                                      outline=(*col, 90), width=1)
                        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=(*col, 160))

        self._composite(canvas, draw_fn)
        label = f"Phase {phase_sel}" if phase_sel > 0 else "All phases"
        parent._zhm_info.config(text=f"{label}\n{total} zone(s) plotted\nmax density: {max_v}")

    # ─────────────────────────────────────────────────────────────────────────
    # Tab 3 — Flight Path Heatmap
    # ─────────────────────────────────────────────────────────────────────────

    def _build_fp_hm_tab(self, parent: tk.Frame):
        left = tk.Frame(parent, bg=BG2, width=220); left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="Flight Path Density", bg=BG2, fg=ACCENT, font=FONT_B).pack(padx=8, pady=(12,4))

        parent._fp_lines = tk.BooleanVar(value=True)
        tk.Checkbutton(left, text="Show individual paths", variable=parent._fp_lines,
                       bg=BG2, fg=FG, selectcolor=BG3, font=FONT_S, activebackground=BG2,
                       command=self._render_fp_heatmap).pack(padx=8, pady=4, anchor="w")

        parent._fp_start_end = tk.BooleanVar(value=True)
        tk.Checkbutton(left, text="Show start/end dots", variable=parent._fp_start_end,
                       bg=BG2, fg=FG, selectcolor=BG3, font=FONT_S, activebackground=BG2,
                       command=self._render_fp_heatmap).pack(padx=8, pady=2, anchor="w")

        tk.Label(left, text="\n● Green = path start\n● Red = path end\nDensity: blue→red",
                 bg=BG2, fg=FG_DIM, font=("Segoe UI", 8), justify="left").pack(padx=12, pady=8, anchor="w")

        parent._fp_info = tk.Label(left, text="", bg=BG2, fg=FG_DIM, font=FONT_S)
        parent._fp_info.pack(padx=8, pady=4, anchor="w")

        # Legend
        leg = tk.Canvas(left, bg=BG2, height=14, width=200, highlightthickness=0)
        leg.pack(padx=8, pady=2)
        leg.bind("<Configure>", lambda e, c=leg: self._draw_legend(c))

        right = tk.Frame(parent, bg=BG); right.pack(fill="both", expand=True)
        mc = tk.Canvas(right, bg="#0d0d1a", highlightthickness=0)
        mc.pack(fill="both", expand=True, padx=4, pady=4)
        mc.bind("<Configure>", lambda e: self._render_fp_heatmap())
        parent._fp_canvas = mc

    def _render_fp_heatmap(self):
        parent = self._tab_frames[2]
        canvas     = parent._fp_canvas
        show_lines = parent._fp_lines.get()
        show_dots  = parent._fp_start_end.get()
        gd         = self._fp_hm
        total_fp   = sum(1 for m in self._matches if m.get("flight_path"))

        def draw_fn(d, cw, ch):
            # Heat grid
            if gd and any(any(r) for r in gd):
                gs = len(gd)
                mv = max(max(row) for row in gd) or 1
                for row in range(gs):
                    for col in range(gs):
                        v = gd[row][col]
                        if v == 0:
                            continue
                        rgba = _heat_rgba(v, mv)
                        x0, y0 = int(col * cw / gs), int(row * ch / gs)
                        x1, y1 = int((col + 1) * cw / gs), int((row + 1) * ch / gs)
                        d.rectangle([x0, y0, x1, y1], fill=rgba)

            # Individual paths
            for m in self._matches:
                fp = m.get("flight_path")
                if not fp:
                    continue
                sx = int(fp["start_x"] * cw); sy = int(fp["start_y"] * ch)
                ex = int(fp["end_x"]   * cw); ey = int(fp["end_y"]   * ch)
                if show_lines:
                    d.line([sx, sy, ex, ey], fill=(41, 182, 246, 90), width=2)
                if show_dots:
                    r = 4
                    d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(0, 230, 118, 180))
                    d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(255, 82, 82, 180))

        self._composite(canvas, draw_fn)
        parent._fp_info.config(text=f"{total_fp} paths annotated")

    # ─────────────────────────────────────────────────────────────────────────
    # Tab 4 — Match Statistics
    # ─────────────────────────────────────────────────────────────────────────

    def _build_stats_tab(self, parent: tk.Frame):
        left = tk.Frame(parent, bg=BG2, width=270); left.pack(side="left", fill="y")
        left.pack_propagate(False)
        sf = _ScrollFrame(left); sf.pack(fill="both", expand=True)
        parent._st_table = sf.inner

        parent._st_show_drift = tk.BooleanVar(value=True)
        parent._st_show_zones = tk.BooleanVar(value=True)

        right = tk.Frame(parent, bg=BG); right.pack(fill="both", expand=True)

        # Toggle row at top of right
        tog = tk.Frame(right, bg=BG3, height=30); tog.pack(fill="x"); tog.pack_propagate(False)
        tk.Checkbutton(tog, text="Show drift arrows", variable=parent._st_show_drift,
                       bg=BG3, fg=FG, selectcolor=BG2, font=FONT_S, activebackground=BG3,
                       command=self._render_stats_map).pack(side="left", padx=10, pady=4)
        tk.Checkbutton(tog, text="Show avg zones", variable=parent._st_show_zones,
                       bg=BG3, fg=FG, selectcolor=BG2, font=FONT_S, activebackground=BG3,
                       command=self._render_stats_map).pack(side="left", padx=10, pady=4)

        mc = tk.Canvas(right, bg="#0d0d1a", highlightthickness=0)
        mc.pack(fill="both", expand=True, padx=4, pady=4)
        mc.bind("<Configure>", lambda e: self._render_stats_map())
        parent._st_canvas = mc

    def _render_stats(self):
        parent = self._tab_frames[3]
        frame = parent._st_table
        for w in frame.winfo_children(): w.destroy()

        s = self._stats
        n = s.get("total_matches", 0)
        _section(frame, " MATCH STATISTICS").pack(fill="x", padx=8, pady=(10, 4))
        tk.Label(frame, text=f"Matches: {n}   Zones: {s.get('total_zones', 0)}",
                 bg=BG2, fg=FG, font=FONT_S).pack(padx=8, anchor="w")

        if n == 0:
            tk.Label(frame, text="No data yet.", bg=BG2, fg=FG_DIM, font=FONT_S).pack(padx=8, pady=8)
            self._render_stats_map()
            return

        _section(frame, " PER-PHASE").pack(fill="x", padx=8, pady=(8, 2))
        cols = ["Ph", "Radius", "Ref", "Drift"]
        widths = [24, 72, 60, 65]
        hrow = tk.Frame(frame, bg=BG3); hrow.pack(fill="x", padx=4)
        for c, w in zip(cols, widths):
            tk.Label(hrow, text=c, bg=BG3, fg=ACCENT, font=("Segoe UI", 8, "bold"),
                     width=w // 7, anchor="center").pack(side="left", padx=1)

        for phase in range(1, NUM_PHASES + 1):
            ps  = s.get("per_phase", {}).get(phase, {})
            col = PHASE_COLORS.get(phase, "#fff")
            rbg = BG2 if phase % 2 == 0 else BG3
            row = tk.Frame(frame, bg=rbg); row.pack(fill="x", padx=4, pady=1)
            avg_r = ps.get("avg_radius_m")
            ref_r = ps.get("ref_radius_m", 0)
            drift = ps.get("avg_drift_m")
            vals = [
                (f"P{phase}",                             col,    FONT_B),
                (f"{avg_r:.0f}m" if avg_r else "—",       FG,     FONT_S),
                (f"{ref_r}m",                             FG_DIM, ("Segoe UI", 8)),
                (f"{drift:.0f}m" if drift else "—",       AMBER,  FONT_S),
            ]
            for (txt, fg, fnt), w in zip(vals, widths):
                tk.Label(row, text=txt, bg=rbg, fg=fg, font=fnt,
                         width=w // 7, anchor="center").pack(side="left", padx=1)

        tk.Label(frame,
                 text="\nMap shows:\n  ● = avg zone centre\n  ○ = avg zone radius\n  → = drift direction",
                 bg=BG2, fg=FG_DIM, font=("Segoe UI", 8), justify="left").pack(padx=10, pady=10, anchor="w")
        self._render_stats_map()

    def _render_stats_map(self):
        parent = self._tab_frames[3]
        canvas      = parent._st_canvas
        show_drift  = parent._st_show_drift.get()
        show_zones  = parent._st_show_zones.get()
        per_phase   = self._stats.get("per_phase", {})

        def draw_fn(d, cw, ch):
            centres = {}  # phase → (px, py) canvas coords
            for phase in range(1, NUM_PHASES + 1):
                ps     = per_phase.get(phase, {})
                avg_cx = ps.get("avg_cx")
                avg_cy = ps.get("avg_cy")
                avg_r  = ps.get("avg_radius_m")
                if avg_cx is None:
                    continue
                col = _hex_to_rgb(PHASE_COLORS.get(phase, "#ffffff"))
                px, py = int(avg_cx * cw), int(avg_cy * ch)
                centres[phase] = (px, py)

                if show_zones and avg_r:
                    rp = int((avg_r / ERANGEL_MAP_SIZE_M) * cw)
                    # Faint fill + solid border
                    d.ellipse([px - rp, py - rp, px + rp, py + rp],
                              fill=(*col, 18), outline=(*col, 200), width=2)

                # Centre dot
                r2 = 6
                d.ellipse([px - r2, py - r2, px + r2, py + r2], fill=(*col, 255))
                d.text((px + r2 + 4, py - 9), f"P{phase}", fill=(*col, 230))

            # Drift arrows
            if show_drift:
                for phase in range(2, NUM_PHASES + 1):
                    if phase - 1 in centres and phase in centres:
                        x1, y1 = centres[phase - 1]
                        x2, y2 = centres[phase]
                        col = _hex_to_rgb(PHASE_COLORS.get(phase, "#ffffff"))
                        d.line([x1, y1, x2, y2], fill=(*col, 160), width=2)
                        _draw_arrowhead(d, x1, y1, x2, y2, col, alpha=200)

        self._composite(canvas, draw_fn)

    # ─────────────────────────────────────────────────────────────────────────
    # Tab 5 — Zone Coverage
    # ─────────────────────────────────────────────────────────────────────────

    def _build_coverage_tab(self, parent: tk.Frame):
        left = tk.Frame(parent, bg=BG2, width=260); left.pack(side="left", fill="y")
        left.pack_propagate(False)
        sf = _ScrollFrame(left); sf.pack(fill="both", expand=True)
        parent._cov_table = sf.inner

        right = tk.Frame(parent, bg=BG); right.pack(fill="both", expand=True)
        mc = tk.Canvas(right, bg="#0d0d1a", highlightthickness=0)
        mc.pack(fill="both", expand=True, padx=4, pady=4)
        mc.bind("<Configure>", lambda e: self._render_coverage_map())
        parent._cov_canvas = mc

    def _render_coverage(self):
        parent = self._tab_frames[4]
        frame = parent._cov_table
        for w in frame.winfo_children(): w.destroy()

        _section(frame, " ZONE COVERAGE").pack(fill="x", padx=8, pady=(10, 4))
        tk.Label(frame, text="Avg % of map area\ncovered per phase",
                 bg=BG2, fg=FG_DIM, font=FONT_S).pack(padx=8, anchor="w")

        n = len(self._matches)
        if n == 0:
            tk.Label(frame, text="No data yet.", bg=BG2, fg=FG_DIM, font=FONT_S).pack(padx=8, pady=8)
            self._render_coverage_map()
            return

        for phase in range(1, NUM_PHASES + 1):
            cv  = self._cov.get(phase, {})
            col = PHASE_COLORS.get(phase, "#fff")
            rbg = BG3 if phase % 2 == 0 else BG2
            row = tk.Frame(frame, bg=rbg); row.pack(fill="x", padx=4, pady=2)
            tk.Label(row, text=f"P{phase}", bg=rbg, fg=col,
                     font=FONT_B, width=3).pack(side="left", padx=4)
            pct = cv.get("avg_pct")
            if pct is not None:
                # Mini bar
                bar = tk.Canvas(row, bg=rbg, height=10, width=100, highlightthickness=0)
                bar.pack(side="left", padx=2)
                fill_w = max(2, int(pct / 55.0 * 100))
                bar.create_rectangle(0, 1, fill_w, 9, fill=col, outline="")
                tk.Label(row, text=f"{pct:.2f}%", bg=rbg, fg=AMBER, font=FONT_S).pack(side="left", padx=2)
                ref_r = PHASE_RADII_M.get(phase, 0)
                tk.Label(row, text=f"ref {ref_r}m", bg=rbg, fg=FG_DIM, font=("Segoe UI", 7)).pack(side="left")
            else:
                tk.Label(row, text="—", bg=rbg, fg=FG_DIM, font=FONT_S).pack(side="left")

        tk.Label(frame,
                 text="\nMap shows average\nzone circles.\nOpacity ∝ coverage %.",
                 bg=BG2, fg=FG_DIM, font=("Segoe UI", 8), justify="left").pack(padx=10, pady=10, anchor="w")
        self._render_coverage_map()

    def _render_coverage_map(self):
        parent  = self._tab_frames[4]
        canvas  = parent._cov_canvas
        cov     = self._cov
        stats   = self._stats

        def draw_fn(d, cw, ch):
            per_phase = stats.get("per_phase", {})
            for phase in range(1, NUM_PHASES + 1):
                ps    = per_phase.get(phase, {})
                cv    = cov.get(phase, {})
                cx    = ps.get("avg_cx")
                cy    = ps.get("avg_cy")
                avg_r = ps.get("avg_radius_m")
                pct   = cv.get("avg_pct")
                if cx is None or avg_r is None:
                    continue
                col = _hex_to_rgb(PHASE_COLORS.get(phase, "#ffffff"))
                px  = int(cx * cw)
                py  = int(cy * ch)
                rp  = int((avg_r / ERANGEL_MAP_SIZE_M) * cw)
                # Fill opacity scales with coverage
                alpha_fill = int(min(pct * 2.5, 90)) if pct else 20
                if rp > 1:
                    d.ellipse([px - rp, py - rp, px + rp, py + rp],
                              fill=(*col, alpha_fill), outline=(*col, 200), width=2)
                # Label
                d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(*col, 255))
                label = f"P{phase}"
                if pct:
                    label += f"\n{pct:.1f}%"
                d.text((px + rp + 5, py - 8), label, fill=(*col, 230))

        self._composite(canvas, draw_fn)
