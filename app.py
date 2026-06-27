"""
app.py  —  BGMI Erangel Zone Annotator
Main application window. Wires all components together.
"""
from __future__ import annotations
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

import storage
from dataset_manager import DatasetManager
from map_canvas import MapCanvas
from annotation_tools import SelectTool, FlightPathTool, CircleTool
from ui import MenuBar, LeftPanel, RightPanel, StatusBar
from predictor import ZonePredictor
from analytics_panel import AnalyticsPanel

# ─── Default map search paths ─────────────────────────────────────────────────
MAP_SEARCH_PATHS = [
    "assets/erangel.png",
    "assets/Erangel.png",
    "assets/erangle.jpg",
    "assets/erangel.jpg",
    "erangle.jpg",
    "Erangel.png",
    "erangel.png",
    "map.png",
    "map.jpg",
]


class BGMIZoneAnnotator(tk.Tk):
    def __init__(self):
        super().__init__()

        # ── Window setup ──────────────────────────────────────────────────
        self.title("BGMI Erangel Zone Annotator")
        self.configure(bg="#0f0f1e")
        self.state("zoomed")           # maximised on Windows
        self.minsize(1100, 700)

        # ── Core components ───────────────────────────────────────────────
        self.dm = DatasetManager()
        self.dm.register_on_change(self._on_state_change)
        self.predictor = ZonePredictor()
        self._analytics_panel: AnalyticsPanel | None = None

        # ── Locate map image ──────────────────────────────────────────────
        map_path = self._find_or_select_map()
        if not map_path:
            messagebox.showerror("Map Required",
                                 "No map image selected. The app will run without a map.")
            map_path = None

        # ── Build UI ──────────────────────────────────────────────────────
        self._build_ui(map_path)
        self._bind_shortcuts()

        # ── Start with a blank match ──────────────────────────────────────
        self.dm.new_match()
        self.current_tool_name = "select"

        # ── Make canvas focusable ────────────────────────────────────
        self.canvas.focus_set()
        # Note: map fitting is handled by map_canvas._deferred_fit via after_idle

    # ─── Map Discovery ────────────────────────────────────────────────────────

    def _find_or_select_map(self) -> str | None:
        # Check config first
        cfg = storage.load_config()
        cached = cfg.get("map_path")
        if cached and os.path.exists(cached):
            return cached

        # Search default locations
        for p in MAP_SEARCH_PATHS:
            if os.path.exists(p):
                storage.save_config({"map_path": p})
                return p

        # Ask user
        path = filedialog.askopenfilename(
            title="Select Erangel Map Image",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")]
        )
        if path:
            storage.save_config({"map_path": path})
        return path or None

    # ─── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self, map_path):
        # Menu bar
        self.menu_bar = MenuBar(self)
        self.config(menu=self.menu_bar)

        # Status bar (bottom)
        self.status_bar = StatusBar(self, self)
        self.status_bar.pack(side="bottom", fill="x")

        # Main horizontal layout
        main = tk.Frame(self, bg="#0f0f1e")
        main.pack(fill="both", expand=True)

        # Left panel
        self.left_panel = LeftPanel(main, self)
        self.left_panel.pack(side="left", fill="y")

        # Divider
        tk.Frame(main, bg="#2a2a4a", width=1).pack(side="left", fill="y")

        # Canvas area
        canvas_frame = tk.Frame(main, bg="#0d0d1a")
        canvas_frame.pack(side="left", fill="both", expand=True)
        self.canvas = MapCanvas(canvas_frame, map_path, self)
        self.canvas.pack(fill="both", expand=True)

        # Divider
        tk.Frame(main, bg="#2a2a4a", width=1).pack(side="left", fill="y")

        # Right panel
        self.right_panel = RightPanel(main, self)
        self.right_panel.pack(side="right", fill="y")

    # ─── Keyboard Shortcuts ───────────────────────────────────────────────────

    def _bind_shortcuts(self):
        self.bind("<Control-z>", lambda e: self.cmd_undo())
        self.bind("<Control-y>", lambda e: self.cmd_redo())
        self.bind("<Control-s>", lambda e: self.cmd_save())
        self.bind("<Control-n>", lambda e: self.cmd_new_match())
        self.bind("<Delete>",    lambda e: self.cmd_delete_selected())
        self.bind("<Escape>",    lambda e: self.set_tool("select"))
        self.bind("f",           lambda e: self.cmd_fit_map())
        self.bind("+",           lambda e: self.canvas.zoom_in())
        self.bind("-",           lambda e: self.canvas.zoom_out())
        self.bind("s",           lambda e: self.set_tool("select"))
        self.bind("p",           lambda e: self.set_tool("flight_path"))
        self.bind("c",           lambda e: self.set_tool("circle"))

    # ─── Tool Management ──────────────────────────────────────────────────────

    def set_tool(self, name: str, phase: int = 1):
        """Switch the active annotation tool."""
        self.current_tool_name = name
        if name == "select":
            self.canvas.active_tool = SelectTool(self.canvas, self.dm)
        elif name == "flight_path":
            self.canvas.active_tool = FlightPathTool(self.canvas, self.dm)
        elif name == "circle":
            self.canvas.active_tool = CircleTool(self.canvas, self.dm, phase=phase)
        self.canvas.config(cursor=self.canvas.active_tool.cursor())
        self.status_bar.refresh(
            tool_name=name,
            match_id=self.dm.match_id or "---",
            n_zones=self.dm.zone_count(),
            dirty=self.dm.is_dirty,
        )
        # Highlight active tool button (only "select" and "flight_path" have buttons now)
        if hasattr(self, "left_panel"):
            for m, b in self.left_panel._tool_btns.items():
                from ui import ACCENT, FG
                b.config(fg=ACCENT if m == name else FG)

    # ─── State Change Observer ────────────────────────────────────────────────

    def _on_state_change(self):
        """Called by DatasetManager after every mutation."""
        self.canvas.redraw()
        if hasattr(self, "right_panel"):
            self.right_panel.refresh()
        if hasattr(self, "left_panel"):
            self.left_panel.refresh()          # also calls refresh_phase_buttons()
        self.status_bar.refresh(
            tool_name=self.current_tool_name,
            match_id=self.dm.match_id or "---",
            n_zones=self.dm.zone_count(),
            dirty=self.dm.is_dirty,
        )

    # ─── File Commands ────────────────────────────────────────────────────────

    def cmd_new_match(self):
        if self.dm.is_dirty:
            if not messagebox.askyesno("Unsaved Changes",
                                       "Discard unsaved changes and start a new match?"):
                return
        self.dm.new_match()
        self.canvas.selected_index = None

    def cmd_open_match(self):
        matches = self.dm.list_matches()
        if not matches:
            messagebox.showinfo("No Matches", "No saved matches found in dataset/")
            return
        # Simple selection dialog
        top = tk.Toplevel(self)
        top.title("Open Match")
        top.configure(bg="#0f0f1e")
        top.resizable(False, False)
        top.grab_set()

        tk.Label(top, text="Select a match to open:", bg="#0f0f1e", fg="#e0e0e0",
                 font=("Segoe UI", 11)).pack(padx=20, pady=(16, 6))

        lb = tk.Listbox(top, bg="#161628", fg="#e0e0e0", selectbackground="#1a3a5c",
                        font=("Segoe UI", 10), relief="flat", bd=0, height=min(12, len(matches)))
        for m in matches:
            n = len(m.get("zones", []))
            lb.insert("end", f"Match {m['match_id']}  [{n} zones]")
        lb.pack(padx=20, pady=6, fill="both")

        def _open():
            sel = lb.curselection()
            if sel:
                mid = matches[sel[0]]["match_id"]
                self.dm.open_match(mid)
                self.canvas.selected_index = None
            top.destroy()

        tk.Button(top, text="Open", command=_open, bg="#252540", fg="#4FC3F7",
                  relief="flat", font=("Segoe UI", 10), pady=6).pack(padx=20, pady=(4, 16), fill="x")
        lb.bind("<Double-Button-1>", lambda e: _open())

    def cmd_save(self):
        path = self.dm.save_current()
        if path:
            self.status_bar.refresh(
                tool_name=self.current_tool_name,
                match_id=self.dm.match_id or "---",
                n_zones=self.dm.zone_count(),
                dirty=False,
            )
            self.title(f"BGMI Erangel Zone Annotator — Match {self.dm.match_id} saved")
        else:
            messagebox.showerror("Save Error", "No active match to save.")

    def cmd_delete_match(self):
        if not messagebox.askyesno("Delete Match",
                                   f"Permanently delete Match {self.dm.match_id}?"):
            return
        self.dm.delete_current_match()
        self.canvas.selected_index = None

    def cmd_change_map(self):
        path = filedialog.askopenfilename(
            title="Select Erangel Map Image",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")]
        )
        if path:
            storage.save_config({"map_path": path})
            self.canvas.load_map(path)
            self.canvas.fit_map()

    # ─── Edit Commands ────────────────────────────────────────────────────────

    def cmd_undo(self):
        if not self.dm.undo():
            self.status_bar.lbl_dirty.config(text="Nothing to undo")
        self.canvas.selected_index = None

    def cmd_redo(self):
        if not self.dm.redo():
            self.status_bar.lbl_dirty.config(text="Nothing to redo")
        self.canvas.selected_index = None

    def cmd_delete_selected(self):
        idx = self.canvas.selected_index
        if idx is not None:
            self.dm.delete_zone(idx)
            self.canvas.selected_index = None

    def cmd_clear_fp(self):
        if messagebox.askyesno("Clear Flight Path", "Remove the flight path?"):
            self.dm.clear_flight_path()

    def cmd_clear_zones(self):
        if messagebox.askyesno("Clear Zones", "Remove ALL zones from this match?"):
            for _ in range(self.dm.zone_count()):
                self.dm.delete_zone(0)
            self.canvas.selected_index = None

    def cmd_fit_map(self):
        self.canvas.fit_map()

    # ─── Export Commands ──────────────────────────────────────────────────────

    def cmd_export_png(self):
        if not self.dm.current_match:
            messagebox.showerror("Error", "No active match.")
            return
        default = f"match_{self.dm.match_id}.png"
        path = filedialog.asksaveasfilename(
            title="Export Annotated PNG",
            defaultextension=".png",
            initialfile=default,
            filetypes=[("PNG", "*.png")]
        )
        if path:
            ok = self.dm.export_match_png(self.canvas, Path(path))
            if ok:
                messagebox.showinfo("Exported", f"Saved to:\n{path}")
            else:
                messagebox.showerror("Export Failed",
                                     "Could not export PNG. Make sure Pillow is installed.")

    def cmd_export_dataset(self):
        path = filedialog.asksaveasfilename(
            title="Export Full Dataset JSON",
            defaultextension=".json",
            initialfile="erangel_dataset.json",
            filetypes=[("JSON", "*.json")]
        )
        if path:
            count = self.dm.export_full_dataset(Path(path))
            messagebox.showinfo("Exported", f"Exported {count} matches to:\n{path}")

    def cmd_export_training(self):
        path = filedialog.asksaveasfilename(
            title="Export Training Data JSON",
            defaultextension=".json",
            initialfile="training_data.json",
            filetypes=[("JSON", "*.json")]
        )
        if path:
            count = self.dm.export_training_data(Path(path))
            messagebox.showinfo("Exported", f"Exported {count} training records to:\n{path}")

    # ─── Predictor Commands ────────────────────────────────────────────────────────

    def cmd_train_predictor(self):
        """Train the ML model on all saved matches."""
        matches = self.dm.list_matches()
        if not matches:
            messagebox.showinfo("No Data",
                "No saved matches found in dataset/.\n"
                "Annotate and save matches first, then train.")
            return
        self.right_panel.update_predictor_status("Training…")
        self.update_idletasks()
        try:
            counts = self.predictor.train(matches)
            info = self.predictor.confidence_info()
            ml_phases = info["ml_phases"]
            total = len(matches)
            if ml_phases:
                status = (f"Trained on {total} match(es).\n"
                          f"ML active for phases: {ml_phases}")
            else:
                status = (f"Trained on {total} match(es).\n"
                          f"Need ≥5 matches per phase for ML.\nUsing heuristic fallback.")
            self.right_panel.update_predictor_status(status, info)
        except Exception as e:
            self.right_panel.update_predictor_status(f"Train error: {e}")

    def cmd_predict_zones(self):
        """
        Predict missing zones for the current match.
        Uses flight path (required) + any already-annotated zones as context.
        Predictions are displayed as dashed overlays on the map.
        """
        fp = self.dm.get_flight_path()
        if fp is None:
            messagebox.showwarning("No Flight Path",
                "Please annotate the flight path first (use ✈ Flight Path tool), "
                "then click Predict Zones.")
            return

        # Auto-train if not trained yet
        if not self.predictor.is_trained:
            self.cmd_train_predictor()

        fp_dict = fp.to_dict()
        known_zones = [z.to_dict() for z in self.dm.get_zones()]

        try:
            predictions = self.predictor.predict_all(fp_dict, known_zones)
            self.canvas.predictions = predictions
            self.canvas.show_predictions = True
            if hasattr(self.right_panel, "var_show_pred"):
                self.right_panel.var_show_pred.set(True)
            self.canvas.redraw()

            known_phases = {z["phase"] for z in known_zones}
            pred_phases  = [p.phase for p in predictions]
            info = self.predictor.confidence_info()
            status = (f"Predicted zones: {pred_phases}\n"
                      f"Known zones: {sorted(known_phases)}")
            self.right_panel.update_predictor_status(status, info)
        except Exception as e:
            messagebox.showerror("Prediction Error", str(e))

    def cmd_clear_predictions(self):
        """Remove all prediction overlays from the map."""
        self.canvas.predictions = []
        self.canvas.redraw()
        self.right_panel.update_predictor_status("Predictions cleared.")

    # ─── Analytics Command ─────────────────────────────────────────────────────────────

    def cmd_show_analytics(self):
        """Open (or bring to front) the analytics dashboard window."""
        if self._analytics_panel is None or not self._analytics_panel.winfo_exists():
            self._analytics_panel = AnalyticsPanel(self)
        else:
            self._analytics_panel.open_or_focus()


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    app = BGMIZoneAnnotator()
    app.mainloop()
