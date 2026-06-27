"""
ui.py - All UI panels: MenuBar, LeftPanel, RightPanel, StatusBar
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
from zone_manager import PHASE_COLORS, PHASE_RADII_M, NUM_PHASES, ERANGEL_MAP_SIZE_M

# ── Theme colors ──────────────────────────────────────────────────────────────
BG       = "#0f0f1e"
BG2      = "#161628"
BG3      = "#1e1e35"
ACCENT   = "#4FC3F7"
ACCENT2  = "#29B6F6"
FG       = "#e0e0e0"
FG_DIM   = "#888899"
BTN_BG   = "#252540"
BTN_HOV  = "#2e2e55"
SEL_BG   = "#1a3a5c"
BORDER   = "#2a2a4a"
RED      = "#FF5252"
GREEN    = "#69F0AE"
FONT     = ("Segoe UI", 10)
FONT_B   = ("Segoe UI", 10, "bold")
FONT_S   = ("Segoe UI", 9)
FONT_H   = ("Segoe UI", 13, "bold")


def styled_btn(parent, text, cmd, color=ACCENT, width=18, **kw):
    b = tk.Button(parent, text=text, command=cmd, bg=BTN_BG, fg=color,
                  activebackground=BTN_HOV, activeforeground=color,
                  relief="flat", bd=0, font=FONT, cursor="hand2",
                  width=width, pady=6, **kw)
    b.bind("<Enter>", lambda e: b.config(bg=BTN_HOV))
    b.bind("<Leave>", lambda e: b.config(bg=BTN_BG))
    return b


def section_label(parent, text):
    f = tk.Frame(parent, bg=BG2)
    tk.Label(f, text=text, bg=BG2, fg=ACCENT, font=FONT_B).pack(side="left", padx=6)
    tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(0, 4))
    return f


# ── Menu Bar ──────────────────────────────────────────────────────────────────
class MenuBar(tk.Menu):
    def __init__(self, app):
        super().__init__(app, bg=BG3, fg=FG, activebackground=ACCENT,
                         activeforeground=BG, relief="flat", bd=0)
        self.app = app
        self._build()

    def _build(self):
        a = self.app
        # File
        file_m = tk.Menu(self, tearoff=0, bg=BG3, fg=FG,
                         activebackground=ACCENT, activeforeground=BG)
        file_m.add_command(label="New Match          Ctrl+N", command=a.cmd_new_match)
        file_m.add_command(label="Open Match…", command=a.cmd_open_match)
        file_m.add_command(label="Save Match          Ctrl+S", command=a.cmd_save)
        file_m.add_separator()
        file_m.add_command(label="Change Map Image…", command=a.cmd_change_map)
        file_m.add_separator()
        file_m.add_command(label="Exit", command=a.destroy)
        self.add_cascade(label="File", menu=file_m)
        # Edit
        edit_m = tk.Menu(self, tearoff=0, bg=BG3, fg=FG,
                         activebackground=ACCENT, activeforeground=BG)
        edit_m.add_command(label="Undo    Ctrl+Z", command=a.cmd_undo)
        edit_m.add_command(label="Redo    Ctrl+Y", command=a.cmd_redo)
        edit_m.add_separator()
        edit_m.add_command(label="Delete Selected    Del", command=a.cmd_delete_selected)
        edit_m.add_command(label="Clear Flight Path", command=a.cmd_clear_fp)
        edit_m.add_command(label="Clear All Zones", command=a.cmd_clear_zones)
        self.add_cascade(label="Edit", menu=edit_m)
        # View
        view_m = tk.Menu(self, tearoff=0, bg=BG3, fg=FG,
                         activebackground=ACCENT, activeforeground=BG)
        view_m.add_command(label="Fit Map to Window    F", command=a.cmd_fit_map)
        view_m.add_command(label="Zoom In    +", command=lambda: a.canvas.zoom_in())
        view_m.add_command(label="Zoom Out   -", command=lambda: a.canvas.zoom_out())
        self.add_cascade(label="View", menu=view_m)
        # Export
        exp_m = tk.Menu(self, tearoff=0, bg=BG3, fg=FG,
                        activebackground=ACCENT, activeforeground=BG)
        exp_m.add_command(label="Export Match PNG…", command=a.cmd_export_png)
        exp_m.add_command(label="Export Full Dataset JSON…", command=a.cmd_export_dataset)
        exp_m.add_command(label="Export Training Data JSON…", command=a.cmd_export_training)
        self.add_cascade(label="Export", menu=exp_m)
        # Analytics
        ana_m = tk.Menu(self, tearoff=0, bg=BG3, fg=FG,
                        activebackground=ACCENT, activeforeground=BG)
        ana_m.add_command(label="📊  Show Analytics Dashboard", command=a.cmd_show_analytics)
        self.add_cascade(label="Analytics", menu=ana_m)


# ── Left Panel ────────────────────────────────────────────────────────────────
class LeftPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG2, width=200)
        self.pack_propagate(False)
        self.app = app
        self._build()

    def _build(self):
        a = self.app
        pad = dict(padx=8, pady=3, fill="x")

        # Title
        tk.Label(self, text="🎯 Zone Annotator", bg=BG2, fg=ACCENT,
                 font=("Segoe UI", 12, "bold")).pack(pady=(12, 4), **{"padx": 8})

        # ── Match info ────────────────────────────────────────────────────
        section_label(self, " MATCH").pack(**pad)
        self.lbl_match = tk.Label(self, text="Match: ---", bg=BG2, fg=FG, font=FONT)
        self.lbl_match.pack(**pad)

        styled_btn(self, "＋ New Match",    a.cmd_new_match).pack(**pad)
        styled_btn(self, "📂 Open Match",   a.cmd_open_match).pack(**pad)
        styled_btn(self, "💾 Save Match",   a.cmd_save, color=GREEN).pack(**pad)
        styled_btn(self, "🗑 Delete Match", a.cmd_delete_match, color=RED).pack(**pad)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── Tools (Select & Flight Path only) ─────────────────────────────
        section_label(self, " TOOLS").pack(**pad)

        self._tool_btns = {}
        tools = [("🖱 Select / Move", "select"),
                 ("✈ Flight Path",   "flight_path")]
        for label, mode in tools:
            b = styled_btn(self, label, lambda m=mode: self._set_tool(m))
            b.pack(**pad)
            self._tool_btns[mode] = b

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── Phase buttons — click to draw that phase's zone ───────────────
        section_label(self, " DRAW ZONE  (click phase to draw)").pack(**pad)

        # Hint label shown when a phase is locked
        self.lbl_phase_hint = tk.Label(
            self, text="Draw P1 first", bg=BG2, fg="#FF8A65",
            font=("Segoe UI", 8), wraplength=180, justify="left")
        self.lbl_phase_hint.pack(**{**pad, "padx": 12})

        self.phase_var = tk.IntVar(value=1)
        phase_frame = tk.Frame(self, bg=BG2)
        phase_frame.pack(**pad)
        self._phase_btns: dict = {}   # phase -> Radiobutton widget
        for i in range(1, 9):
            col = PHASE_COLORS.get(i, "#fff")
            b = tk.Radiobutton(
                phase_frame, text=f"P{i}", variable=self.phase_var,
                value=i, bg=BG2, fg=col, selectcolor=BG3,
                activebackground=BG2, font=("Segoe UI", 9, "bold"),
                command=lambda ph=i: self._on_phase_btn(ph),
                indicatoron=False, relief="flat", bd=1, padx=4)
            b.grid(row=(i - 1) // 4, column=(i - 1) % 4, padx=2, pady=2)
            self._phase_btns[i] = b

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── Visibility toggles ────────────────────────────────────────────
        section_label(self, " LAYERS").pack(**pad)
        self.var_fp    = tk.BooleanVar(value=True)
        self.var_zones = tk.BooleanVar(value=True)
        self.var_labels = tk.BooleanVar(value=True)
        self.var_centers = tk.BooleanVar(value=True)
        self.var_grid   = tk.BooleanVar(value=False)
        self.var_snap   = tk.BooleanVar(value=False)

        toggles = [
            ("✈ Flight Path",   self.var_fp,      self._tog_fp),
            ("⭕ Zones",        self.var_zones,   self._tog_zones),
            ("🏷 Labels",       self.var_labels,  self._tog_labels),
            ("＋ Centers",      self.var_centers, self._tog_centers),
            ("⊞ Grid",         self.var_grid,    self._tog_grid),
            ("🔲 Snap to Grid", self.var_snap,    self._tog_snap),
        ]
        for text, var, cmd in toggles:
            cb = tk.Checkbutton(self, text=text, variable=var, command=cmd,
                                bg=BG2, fg=FG, selectcolor=BG3, font=FONT_S,
                                activebackground=BG2, anchor="w")
            cb.pack(**{**pad, "padx": 12})

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── Phase visibility ──────────────────────────────────────────────
        section_label(self, " PHASE VISIBILITY").pack(**pad)
        self.phase_vis_vars = {}
        pf = tk.Frame(self, bg=BG2)
        pf.pack(**pad)
        for i in range(1, 9):
            v = tk.BooleanVar(value=True)
            self.phase_vis_vars[i] = v
            col = PHASE_COLORS.get(i, "#fff")
            cb = tk.Checkbutton(pf, text=f"P{i}", variable=v,
                                command=lambda ph=i: self._tog_phase(ph),
                                bg=BG2, fg=col, selectcolor=BG3, font=FONT_S,
                                activebackground=BG2)
            cb.grid(row=(i - 1) // 4, column=(i - 1) % 4, padx=2)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── Undo / Redo ───────────────────────────────────────────────────
        uf = tk.Frame(self, bg=BG2)
        uf.pack(**pad)
        styled_btn(uf, "↩ Undo", a.cmd_undo, width=8).pack(side="left", padx=2)
        styled_btn(uf, "↪ Redo", a.cmd_redo, width=8).pack(side="left", padx=2)

        # ── Zoom ──────────────────────────────────────────────────────────
        zf = tk.Frame(self, bg=BG2)
        zf.pack(**pad)
        styled_btn(zf, "＋", lambda: a.canvas.zoom_in(),  width=4).pack(side="left", padx=2)
        styled_btn(zf, "Fit", a.cmd_fit_map,              width=6).pack(side="left", padx=2)
        styled_btn(zf, "－", lambda: a.canvas.zoom_out(), width=4).pack(side="left", padx=2)

    def _set_tool(self, mode):
        self.app.set_tool(mode)
        for m, b in self._tool_btns.items():
            b.config(fg=ACCENT if m == mode else FG)

    def _on_phase_btn(self, phase: int):
        """Called when user clicks a P1–P8 button."""
        existing_phases = {z.phase for z in self.app.dm.get_zones()}

        # Phase already drawn — block new creation
        if phase in existing_phases:
            self.lbl_phase_hint.config(
                text=f"\u2714 P{phase} already drawn. Delete it first to redraw.",
                fg="#FF8A65")
            # Keep current tool unchanged
            return

        # Phase locked (previous not drawn)
        if phase > 1 and (phase - 1) not in existing_phases:
            next_needed = phase - 1
            self.phase_var.set(next_needed)
            self.lbl_phase_hint.config(
                text=f"🔒 P{phase} locked — draw P{next_needed} first",
                fg="#FF5252")
            return

        # Phase available — activate draw tool
        self.lbl_phase_hint.config(
            text=f"Click on map to place P{phase} zone",
            fg="#69F0AE")
        self.app.set_tool("circle", phase=phase)

    def refresh_phase_buttons(self):
        """Update phase button states: done / available / locked."""
        existing_phases = {z.phase for z in self.app.dm.get_zones()}
        for phase, btn in self._phase_btns.items():
            col = PHASE_COLORS.get(phase, "#fff")
            if phase in existing_phases:
                # Already drawn — disable with a dim green "done" tint
                btn.config(state="disabled", fg="#2e6b4f")
            elif phase == 1 or (phase - 1) in existing_phases:
                # Ready to draw
                btn.config(state="normal", fg=col)
            else:
                # Locked (previous phase not yet drawn)
                btn.config(state="disabled", fg="#444466")

        # Hint label
        next_undone = None
        for p in range(1, 9):
            if p not in existing_phases:
                next_undone = p
                break

        if next_undone is None:
            self.lbl_phase_hint.config(text="✓ All 8 zones drawn", fg="#69F0AE")
        elif next_undone == 1 or (next_undone - 1) in existing_phases:
            col = PHASE_COLORS.get(next_undone, ACCENT)
            self.lbl_phase_hint.config(
                text=f"P{next_undone} ready — click to draw", fg=col)
        else:
            self.lbl_phase_hint.config(
                text=f"Draw P{next_undone - 1} to unlock P{next_undone}",
                fg="#FF8A65")

    def _tog_fp(self):
        self.app.canvas.show_flight_path = self.var_fp.get()
        self.app.canvas.schedule_redraw()

    def _tog_zones(self):
        self.app.canvas.show_zones = self.var_zones.get()
        self.app.canvas.schedule_redraw()

    def _tog_labels(self):
        self.app.canvas.show_labels = self.var_labels.get()
        self.app.canvas.schedule_redraw()

    def _tog_centers(self):
        self.app.canvas.show_centers = self.var_centers.get()
        self.app.canvas.schedule_redraw()

    def _tog_grid(self):
        self.app.canvas.show_grid = self.var_grid.get()
        self.app.canvas.schedule_redraw()

    def _tog_snap(self):
        self.app.canvas.snap_to_grid = self.var_snap.get()

    def _tog_phase(self, ph):
        self.app.canvas.phase_visible[ph] = self.phase_vis_vars[ph].get()
        self.app.canvas.schedule_redraw()

    def refresh(self, match=None):
        mid = self.app.dm.match_id or "---"
        dirty = "●" if self.app.dm.is_dirty else ""
        self.lbl_match.config(text=f"Match: {mid}  {dirty}")
        self.refresh_phase_buttons()


# ── Right Panel ───────────────────────────────────────────────────────────────
class RightPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG2, width=260)
        self.pack_propagate(False)
        self.app = app
        self._sel_idx = None
        
        # Setup scrolling
        self.canvas = tk.Canvas(self, bg=BG2, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG2)
        
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw", width=240)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Mousewheel scrolling binding
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
        self._build()

    def _on_mousewheel(self, event):
        # Only scroll if pointer is over the right panel
        x, y = self.winfo_pointerxy()
        widget = self.winfo_containing(x, y)
        if widget and str(widget).startswith(str(self)):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def _build(self):
        pad = dict(padx=8, pady=3, fill="x")
        parent = self.inner

        # ── Match list ────────────────────────────────────────────────────
        section_label(parent, " DATASET").pack(**pad)
        lf = tk.Frame(parent, bg=BG2)
        lf.pack(**pad)
        sb = tk.Scrollbar(lf, orient="vertical")
        self.match_list = tk.Listbox(lf, bg=BG3, fg=FG, selectbackground=SEL_BG,
                                     font=FONT_S, relief="flat", bd=0,
                                     height=6, yscrollcommand=sb.set)
        sb.config(command=self.match_list.yview)
        self.match_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.match_list.bind("<<ListboxSelect>>", self._on_match_select)

        styled_btn(parent, "🔃 Refresh List", self.refresh_match_list, width=20).pack(**pad)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── Zone list ─────────────────────────────────────────────────────
        section_label(parent, " ZONES").pack(**pad)
        zf = tk.Frame(parent, bg=BG2)
        zf.pack(**pad)
        zsb = tk.Scrollbar(zf, orient="vertical")
        self.zone_list = tk.Listbox(zf, bg=BG3, fg=FG, selectbackground=SEL_BG,
                                    font=FONT_S, relief="flat", bd=0,
                                    height=8, yscrollcommand=zsb.set)
        zsb.config(command=self.zone_list.yview)
        self.zone_list.pack(side="left", fill="both", expand=True)
        zsb.pack(side="right", fill="y")
        self.zone_list.bind("<<ListboxSelect>>", self._on_zone_select)

        zbf = tk.Frame(parent, bg=BG2)
        zbf.pack(**pad)
        styled_btn(zbf, "▲", self._zone_up,  width=5).pack(side="left", padx=2)
        styled_btn(zbf, "▼", self._zone_down, width=5).pack(side="left", padx=2)
        styled_btn(zbf, "🗑 Del", self._zone_del, color=RED, width=8).pack(side="left", padx=2)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── Coordinate inspector ──────────────────────────────────────────
        section_label(parent, " INSPECTOR").pack(**pad)
        self.insp_frame = tk.Frame(parent, bg=BG2)
        self.insp_frame.pack(**pad)
        self._insp_labels = {}
        rows = [
            ("cursor_x",   "Cursor X"),
            ("cursor_y",   "Cursor Y"),
            ("sel_phase",  "Phase"),
            ("sel_cx",     "Center X"),
            ("sel_cy",     "Center Y"),
            ("sel_r_norm", "Radius (norm)"),
            ("sel_r_m",    "Radius (m)"),
            ("sel_r_ref",  "Ref Radius (m)"),
        ]
        for key, label in rows:
            row = tk.Frame(self.insp_frame, bg=BG2)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{label}:", bg=BG2, fg=FG_DIM,
                     font=FONT_S, width=14, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="---", bg=BG2, fg=ACCENT, font=FONT_S, anchor="w")
            lbl.pack(side="left")
            self._insp_labels[key] = lbl

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── Export ────────────────────────────────────────────────────────
        section_label(parent, " EXPORT").pack(**pad)
        styled_btn(parent, "📸 Export PNG",     self.app.cmd_export_png).pack(**pad)
        styled_btn(parent, "📦 Full Dataset",   self.app.cmd_export_dataset).pack(**pad)
        styled_btn(parent, "🤖 Training Data",  self.app.cmd_export_training).pack(**pad)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=6)

        # ── AI Predictor ──────────────────────────────────────────────────
        section_label(parent, " 🤖 AI PREDICTOR").pack(**pad)

        # Status line
        self.lbl_pred_status = tk.Label(
            parent, text="Not trained", bg=BG2, fg="#FF8A65",
            font=FONT_S, wraplength=220, justify="left"
        )
        self.lbl_pred_status.pack(**{**pad, "padx": 12})

        # Train button
        styled_btn(parent, "⚡ Train Model",
                   self.app.cmd_train_predictor, color="#FFD740").pack(**pad)

        # Predict button
        styled_btn(parent, "🔮 Predict Zones",
                   self.app.cmd_predict_zones, color=GREEN).pack(**pad)

        # Clear predictions
        styled_btn(parent, "✕ Clear Predictions",
                   self.app.cmd_clear_predictions, color=RED, width=18).pack(**pad)

        # Show predictions toggle
        self.var_show_pred = tk.BooleanVar(value=True)
        tk.Checkbutton(
            parent, text="👁 Show Predictions", variable=self.var_show_pred,
            command=self._tog_predictions,
            bg=BG2, fg=ACCENT, selectcolor=BG3, font=FONT_S,
            activebackground=BG2, anchor="w"
        ).pack(**{**pad, "padx": 12})

        # Per-phase confidence display
        tk.Label(parent, text="Phase confidence:", bg=BG2, fg=FG_DIM,
                 font=FONT_S).pack(**{**pad, "padx": 12, "pady": (6, 0)})
        self.pred_conf_labels: dict = {}
        conf_frame = tk.Frame(parent, bg=BG2)
        conf_frame.pack(**{**pad, "padx": 12})
        from zone_manager import PHASE_COLORS
        for phase in range(1, 9):
            col = PHASE_COLORS.get(phase, "#fff")
            row = tk.Frame(conf_frame, bg=BG2)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"P{phase}:", bg=BG2, fg=col,
                     font=FONT_S, width=3, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="---", bg=BG2, fg=FG_DIM,
                           font=("Segoe UI", 8), anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            self.pred_conf_labels[phase] = lbl

    def _tog_predictions(self):
        self.app.canvas.show_predictions = self.var_show_pred.get()
        self.app.canvas.schedule_redraw()

    def update_predictor_status(self, status_text: str, conf_info: dict = None):
        """Called by app after training/predicting to refresh predictor UI."""
        self.lbl_pred_status.config(text=status_text)
        if conf_info:
            for phase in range(1, 9):
                n = conf_info.get("samples", {}).get(phase, 0)
                ml = phase in conf_info.get("ml_phases", [])
                label = f"ML ({n})" if ml else f"Heuristic ({n})"
                color = GREEN if ml else "#FF8A65"
                self.pred_conf_labels[phase].config(text=label, fg=color)


    # ── Match list ────────────────────────────────────────────────────────────

    def refresh_match_list(self):
        self.match_list.delete(0, "end")
        for m in self.app.dm.list_matches():
            n_zones = len(m.get("zones", []))
            has_fp = "✈" if m.get("flight_path") else "  "
            self.match_list.insert("end", f"{has_fp} Match {m['match_id']}  [{n_zones} zones]")

    def _on_match_select(self, event):
        sel = self.match_list.curselection()
        if not sel:
            return
        matches = self.app.dm.list_matches()
        idx = sel[0]
        if idx < len(matches):
            mid = matches[idx]["match_id"]
            if messagebox.askyesno("Open Match",
                                   f"Open Match {mid}? Unsaved changes will be lost."):
                self.app.dm.open_match(mid)
                self.app.canvas.selected_index = None
                self.app.canvas.redraw()
                self.refresh()

    # ── Zone list ─────────────────────────────────────────────────────────────

    def refresh_zone_list(self):
        self.zone_list.delete(0, "end")
        for z in self.app.dm.get_zones():
            col = PHASE_COLORS.get(z.phase, "#fff")
            rm  = z.radius_meters()
            ref = PHASE_RADII_M.get(z.phase, 0)
            self.zone_list.insert(
                "end",
                f"P{z.phase}  ({z.center_x:.3f}, {z.center_y:.3f})  r={rm:.0f}m"
            )
        # Sync selection
        if self.app.canvas.selected_index is not None:
            idx = self.app.canvas.selected_index
            if idx < self.zone_list.size():
                self.zone_list.selection_clear(0, "end")
                self.zone_list.selection_set(idx)
                self.zone_list.see(idx)

    def _on_zone_select(self, event):
        sel = self.zone_list.curselection()
        if sel:
            self.app.canvas.selected_index = sel[0]
            self.app.canvas.redraw()
            self.update_inspector(None, None, sel[0])

    def _zone_up(self):
        idx = self.app.canvas.selected_index
        if idx is not None:
            new_idx = self.app.dm.move_zone_up(idx)
            self.app.canvas.selected_index = new_idx
            self.refresh()

    def _zone_down(self):
        idx = self.app.canvas.selected_index
        if idx is not None:
            new_idx = self.app.dm.move_zone_down(idx)
            self.app.canvas.selected_index = new_idx
            self.refresh()

    def _zone_del(self):
        idx = self.app.canvas.selected_index
        if idx is not None:
            self.app.dm.delete_zone(idx)
            self.app.canvas.selected_index = None

    # ── Inspector ─────────────────────────────────────────────────────────────

    def update_inspector(self, nx, ny, sel_idx):
        def s(key, val): self._insp_labels[key].config(text=val)
        if nx is not None:
            s("cursor_x", f"{nx:.4f}  ({nx * ERANGEL_MAP_SIZE_M:.0f}m)")
            s("cursor_y", f"{ny:.4f}  ({ny * ERANGEL_MAP_SIZE_M:.0f}m)")
        if sel_idx is not None:
            zones = self.app.dm.get_zones()
            if sel_idx < len(zones):
                z = zones[sel_idx]
                s("sel_phase",  str(z.phase))
                s("sel_cx",     f"{z.center_x:.4f}")
                s("sel_cy",     f"{z.center_y:.4f}")
                s("sel_r_norm", f"{z.radius:.5f}")
                s("sel_r_m",    f"{z.radius_meters():.1f} m")
                s("sel_r_ref",  f"{z.reference_radius_m()} m")
        elif sel_idx is None:
            for k in ("sel_phase","sel_cx","sel_cy","sel_r_norm","sel_r_m","sel_r_ref"):
                s(k, "---")

    def refresh(self):
        self.refresh_match_list()
        self.refresh_zone_list()
        self.app.left_panel.refresh()


# ── Status Bar ────────────────────────────────────────────────────────────────
class StatusBar(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG3, height=26)
        self.pack_propagate(False)
        self.app = app

        tk.Frame(self, bg=ACCENT, width=3).pack(side="left", fill="y")

        self.lbl_tool   = tk.Label(self, text="Tool: Select", bg=BG3, fg=ACCENT,  font=FONT_S)
        self.lbl_cursor = tk.Label(self, text="X: 0.000  Y: 0.000", bg=BG3, fg=FG, font=FONT_S)
        self.lbl_zoom   = tk.Label(self, text="Zoom: 100%", bg=BG3, fg=FG_DIM, font=FONT_S)
        self.lbl_match  = tk.Label(self, text="Match: ---", bg=BG3, fg=FG_DIM, font=FONT_S)
        self.lbl_zones  = tk.Label(self, text="Zones: 0", bg=BG3, fg=FG_DIM, font=FONT_S)
        self.lbl_dirty  = tk.Label(self, text="", bg=BG3, fg=RED, font=FONT_S)

        for lbl in (self.lbl_tool, self.lbl_cursor, self.lbl_zoom,
                    self.lbl_match, self.lbl_zones, self.lbl_dirty):
            lbl.pack(side="left", padx=14)

    def update_cursor(self, nx: float, ny: float, zoom: float):
        from zone_manager import ERANGEL_MAP_SIZE_M as MS
        self.lbl_cursor.config(
            text=f"X: {nx:.4f} ({nx*MS:.0f}m)  Y: {ny:.4f} ({ny*MS:.0f}m)")
        self.lbl_zoom.config(text=f"Zoom: {zoom*100:.0f}%")

    def refresh(self, tool_name="select", match_id="---", n_zones=0, dirty=False):
        self.lbl_tool.config(text=f"Tool: {tool_name.replace('_',' ').title()}")
        self.lbl_match.config(text=f"Match: {match_id}")
        self.lbl_zones.config(text=f"Zones: {n_zones}")
        self.lbl_dirty.config(text="● Unsaved" if dirty else "")
