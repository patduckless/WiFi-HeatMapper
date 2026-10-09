import ast
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import BSSID
import heatmap

FLOORPLAN_TYPES = [("Images", "*.png *.jpg *.jpeg *.bmp *.gif"), ("All files", "*.*")]
SURVEY_TYPES = [("Survey files", "*.json"), ("Legacy results", "*.txt"), ("All files", "*.*")]
POINT_RADIUS = 5


class HeatMapper:
    def __init__(self, root):
        self.root = root
        self.points = []
        self.floorplan = None
        self.floorplan_path = None
        self.survey_path = None
        self.scale = 1.0
        self.display_image = None
        self.heatmap = None
        self.scanning = False
        self.dirty = False
        self.scan_results = queue.Queue()
        self.live_ssids = set()

        root.title("Wi-Fi Heatmapper")
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self._build_menu()
        self._build_toolbar()

        self.canvas = tk.Canvas(root, width=900, height=600, background="#3a3a3a", highlightthickness=0)
        self.canvas.grid(column=0, row=1, sticky="nsew")
        self.canvas.create_text(450, 300, text="File > Open Floor Plan to start a survey",
                                fill="white", font=("TkDefaultFont", 14))
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Motion>", self.on_motion)

        self.status = tk.StringVar(value="Open a floor plan, then click where you are standing to take a measurement.")
        ttk.Label(root, textvariable=self.status, anchor="w", padding=(6, 3)).grid(column=0, row=2, sticky="ew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        root.bind("<Control-z>", lambda e: self.undo())
        root.bind("<Control-s>", lambda e: self.save_survey())
        root.bind("<Control-o>", lambda e: self.open_floorplan())

        threading.Thread(target=self._initial_scan, daemon=True).start()
        self.root.after(100, self._poll_scans)

    # ---- UI construction -------------------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open Floor Plan...", accelerator="Ctrl+O", command=self.open_floorplan)
        filemenu.add_separator()
        filemenu.add_command(label="Open Survey...", command=self.open_survey)
        filemenu.add_command(label="Save Survey", accelerator="Ctrl+S", command=self.save_survey)
        filemenu.add_command(label="Save Survey As...", command=lambda: self.save_survey(save_as=True))
        filemenu.add_separator()
        filemenu.add_command(label="Export Heatmap Image...", command=self.export_image)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=filemenu)

        surveymenu = tk.Menu(menubar, tearoff=0)
        surveymenu.add_command(label="Undo Last Point", accelerator="Ctrl+Z", command=self.undo)
        surveymenu.add_command(label="Show Measurements", command=self.show_measurements)
        surveymenu.add_separator()
        surveymenu.add_command(label="Clear Survey", command=self.clear_survey)
        menubar.add_cascade(label="Survey", menu=surveymenu)

        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_command(label="Heatmap Report...", command=self.show_report)
        menubar.add_cascade(label="View", menu=viewmenu)
        self.root.config(menu=menubar)

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(6, 4))
        bar.grid(column=0, row=0, sticky="ew")

        self.ssid_var = tk.StringVar(value=heatmap.ALL_NETWORKS)
        self.band_var = tk.StringVar(value=heatmap.BANDS[0])
        self.mode_var = tk.StringVar(value=heatmap.MODES[0])
        self.min_signal_var = tk.IntVar(value=-85)
        self.opacity_var = tk.DoubleVar(value=0.65)
        self.show_heatmap_var = tk.BooleanVar(value=True)
        self.show_aps_var = tk.BooleanVar(value=True)

        ttk.Label(bar, text="Network").pack(side="left")
        self.ssid_box = ttk.Combobox(bar, textvariable=self.ssid_var, width=24, state="readonly",
                                     values=[heatmap.ALL_NETWORKS])
        self.ssid_box.pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="Band").pack(side="left")
        ttk.Combobox(bar, textvariable=self.band_var, width=9, state="readonly",
                     values=heatmap.BANDS).pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="View").pack(side="left")
        ttk.Combobox(bar, textvariable=self.mode_var, width=18, state="readonly",
                     values=heatmap.MODES).pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="Min signal (dBm)").pack(side="left")
        spinbox = ttk.Spinbox(bar, textvariable=self.min_signal_var, from_=-95, to=-40, increment=1, width=5,
                              command=self.refresh)
        spinbox.pack(side="left", padx=(4, 10))
        spinbox.bind("<Return>", lambda e: self.refresh())
        spinbox.bind("<FocusOut>", lambda e: self.refresh())
        ttk.Label(bar, text="Opacity").pack(side="left")
        ttk.Scale(bar, variable=self.opacity_var, from_=0.2, to=1.0, length=90,
                  command=lambda _: self.redraw()).pack(side="left", padx=(4, 10))
        ttk.Checkbutton(bar, text="Heatmap", variable=self.show_heatmap_var,
                        command=self.refresh).pack(side="left")
        ttk.Checkbutton(bar, text="APs", variable=self.show_aps_var,
                        command=self.redraw).pack(side="left", padx=(6, 0))

        for var in (self.ssid_var, self.band_var, self.mode_var):
            var.trace_add("write", lambda *_: self.refresh())

    # ---- Scanning --------------------------------------------------------------------------

    def _initial_scan(self):
        try:
            self.scan_results.put(("ssids", BSSID.network_list(), None))
        except Exception as error:
            self.scan_results.put(("ssids", [], error))

    def _scan_worker(self, x, y):
        started = time.time()
        try:
            readings = BSSID.scan()
            error = None
        except Exception as e:
            readings, error = None, e
        self.scan_results.put(("point", {"x": x, "y": y, "time": started, "readings": readings}, error))

    def _poll_scans(self):
        while not self.scan_results.empty():
            kind, payload, error = self.scan_results.get()
            if kind == "ssids":
                if error:
                    self.status.set(f"Wi-Fi scan unavailable: {error}")
                self.live_ssids.update(payload)
                self._update_ssid_list()
            else:
                self.scanning = False
                self.canvas.delete("pending")
                if error:
                    messagebox.showerror("Scan failed", str(error))
                    self.status.set("Scan failed.")
                else:
                    self.points.append(payload)
                    self.dirty = True
                    self.live_ssids.update(r["SSID"] for r in payload["readings"])
                    self._update_ssid_list()
                    self.status.set(f'Point {len(self.points)}: {len(payload["readings"])} access points heard, '
                                    f'best {self._best_text(payload)}.')
                    self.refresh()
        self.root.after(100, self._poll_scans)

    def _update_ssid_list(self):
        surveyed = {r["SSID"] for p in self.points for r in p["readings"]}
        names = sorted((surveyed | self.live_ssids) - {""}, key=str.lower)
        self.ssid_box["values"] = [heatmap.ALL_NETWORKS] + names

    def _filters(self):
        return self.ssid_var.get(), self.band_var.get()

    def _best_text(self, point):
        signal = heatmap.best_signal(point, *self._filters())
        return "nothing on this network/band" if signal is None else f"{signal} dBm"

    # ---- Canvas interaction ----------------------------------------------------------------

    def _to_image(self, event):
        x, y = event.x / self.scale, event.y / self.scale
        if self.floorplan and 0 <= x < self.floorplan.width and 0 <= y < self.floorplan.height:
            return x, y
        return None

    def on_left_click(self, event):
        position = self._to_image(event)
        if position is None:
            return
        if self.scanning:
            self.status.set("Still scanning the previous point, please wait...")
            return
        self.scanning = True
        r = POINT_RADIUS + 3
        self.canvas.create_oval(event.x - r, event.y - r, event.x + r, event.y + r,
                                outline="white", width=2, dash=(3, 2), tags="pending")
        self.status.set("Scanning... stay still until the point appears.")
        threading.Thread(target=self._scan_worker, args=position, daemon=True).start()

    def on_right_click(self, event):
        position = self._to_image(event)
        if position is None or not self.points:
            return
        distances = [((p["x"] - position[0]) ** 2 + (p["y"] - position[1]) ** 2) ** 0.5 * self.scale
                     for p in self.points]
        nearest = min(range(len(distances)), key=distances.__getitem__)
        if distances[nearest] <= POINT_RADIUS * 3:
            del self.points[nearest]
            self.dirty = True
            self.status.set(f"Deleted point {nearest + 1}.")
            self.refresh()

    def on_motion(self, event):
        position = self._to_image(event)
        if position is None or self.scanning:
            return
        if self.heatmap:
            text = self.heatmap.describe(*position)
            self.status.set(text or "Outside the surveyed area.")

    # ---- Rendering -------------------------------------------------------------------------

    def refresh(self):
        """Recompute the heatmap from the survey data, then redraw."""
        if self.floorplan is None:
            return
        self.heatmap = None
        if self.show_heatmap_var.get() and self.points:
            try:
                min_signal = int(self.min_signal_var.get())
            except (tk.TclError, ValueError):
                min_signal = -85
            ssid, band = self._filters()
            self.heatmap = heatmap.compute(self.points, self.floorplan.size, ssid=ssid, band=band,
                                           mode=self.mode_var.get(), min_signal=min_signal)
        self.redraw()

    def redraw(self):
        if self.floorplan is None:
            return
        size = self.display_image.size
        composite = self.display_image
        if self.heatmap is not None:
            composite = Image.alpha_composite(composite, self.heatmap.overlay(size, self.opacity_var.get()))
        self.photo = ImageTk.PhotoImage(composite)
        self.canvas.delete("all")
        self.canvas.config(width=size[0], height=size[1])
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        s = self.scale
        if len(self.points) > 1:
            route = [c for p in self.points for c in (p["x"] * s, p["y"] * s)]
            self.canvas.create_line(*route, fill="#1d3f8f", width=1, dash=(4, 3))
        for point in self.points:
            color = heatmap.point_color(heatmap.best_signal(point, *self._filters()))
            x, y, r = point["x"] * s, point["y"] * s, POINT_RADIUS
            self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="black")

        if self.heatmap is not None and self.show_aps_var.get():
            for ap in self.heatmap.aps.values():
                x, y = ap["x"] * s, ap["y"] * s
                self.canvas.create_polygon(x, y - 9, x - 8, y + 6, x + 8, y + 6, fill="#2b2b2b", outline="white")
                self.canvas.create_text(x + 10, y - 4, anchor="w", fill="black", font=("TkDefaultFont", 8),
                                        text=f'{ap["SSID"] or "<hidden>"} ch {ap["Channel"]}')

    # ---- Files -----------------------------------------------------------------------------

    def open_floorplan(self, path=None):
        path = path or filedialog.askopenfilename(title="Open floor plan", filetypes=FLOORPLAN_TYPES)
        if not path:
            return False
        if self.points and self.floorplan_path and os.path.abspath(path) != os.path.abspath(self.floorplan_path):
            if not messagebox.askyesno("Change floor plan",
                                       "Keep the current survey points on the new floor plan?"):
                self.points.clear()
        self.floorplan = Image.open(path).convert("RGBA")
        self.floorplan_path = path
        max_w = self.root.winfo_screenwidth() - 80
        max_h = self.root.winfo_screenheight() - 200
        self.scale = min(1.0, max_w / self.floorplan.width, max_h / self.floorplan.height)
        size = (max(1, round(self.floorplan.width * self.scale)), max(1, round(self.floorplan.height * self.scale)))
        self.display_image = self.floorplan.resize(size, Image.LANCZOS)
        self.root.title(f"Wi-Fi Heatmapper - {os.path.basename(path)}")
        self.refresh()
        return True

    def save_survey(self, save_as=False):
        if not self.points and not self.floorplan_path:
            messagebox.showinfo("Save survey", "Nothing to save yet.")
            return
        path = self.survey_path
        if save_as or not path:
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=SURVEY_TYPES[:1])
            if not path:
                return
        floorplan = self.floorplan_path
        if floorplan:
            try:
                floorplan = os.path.relpath(floorplan, os.path.dirname(os.path.abspath(path)))
            except ValueError:
                floorplan = os.path.abspath(floorplan)
        with open(path, "w") as file:
            json.dump({"version": 2, "floorplan": floorplan, "points": self.points}, file, indent=1)
        self.survey_path = path
        self.dirty = False
        self.status.set(f"Saved {len(self.points)} points to {path}")

    def open_survey(self):
        path = filedialog.askopenfilename(title="Open survey", filetypes=SURVEY_TYPES)
        if not path:
            return
        with open(path, "r") as file:
            text = file.read()
        try:
            data = json.loads(text)
            points = data["points"]
            floorplan = data.get("floorplan")
            if floorplan and not os.path.isabs(floorplan):
                floorplan = os.path.join(os.path.dirname(os.path.abspath(path)), floorplan)
        except (ValueError, KeyError, TypeError):
            points = convert_legacy(ast.literal_eval(text))
            floorplan = None

        self.points = []
        if floorplan and os.path.exists(floorplan):
            self.open_floorplan(floorplan)
        elif self.floorplan is None:
            messagebox.showinfo("Floor plan", "Select the floor plan this survey was taken on.")
            if not self.open_floorplan():
                return
        self.points = points
        self.survey_path = path if path.lower().endswith(".json") else None
        self.dirty = False
        self._update_ssid_list()
        self.status.set(f"Loaded {len(points)} points from {path}")
        self.refresh()

    def export_image(self):
        if self.floorplan is None or self.heatmap is None:
            messagebox.showinfo("Export", "Take some measurements first.")
            return
        options = self._export_options()
        if options is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png")])
        if path:
            self._report_figure(**options).savefig(path, dpi=150, bbox_inches="tight")
            self.status.set(f"Exported {path}")

    def _export_options(self):
        """Ask which overlays to include in the exported image. Returns None if cancelled."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Export Options")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        variables = {
            "show_points": tk.BooleanVar(value=True),
            "show_aps": tk.BooleanVar(value=self.show_aps_var.get()),
            "show_names": tk.BooleanVar(value=True),
            "show_contours": tk.BooleanVar(value=True),
        }
        labels = {
            "show_points": "Measurement points and route",
            "show_aps": "Access point markers",
            "show_names": "SSID names (on AP labels and legend)",
            "show_contours": "Contour lines at (dBm):",
        }
        frame = ttk.Frame(dialog, padding=12)
        frame.pack()
        levels_var = tk.StringVar(value="-67, -75")
        for key, var in variables.items():
            row = ttk.Frame(frame)
            row.pack(anchor="w", pady=2, fill="x")
            ttk.Checkbutton(row, text=labels[key], variable=var).pack(side="left")
            if key == "show_contours":
                ttk.Entry(row, textvariable=levels_var, width=14).pack(side="left", padx=(6, 0))
        result = {}

        def accept():
            try:
                levels = tuple(float(v) for v in levels_var.get().replace(";", ",").split(",") if v.strip())
            except ValueError:
                messagebox.showerror("Export Options", "Contour levels must be numbers, e.g. -67, -75", parent=dialog)
                return
            result.update({key: var.get() for key, var in variables.items()})
            result["contour_levels"] = levels
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e", pady=(10, 0))
        ttk.Button(buttons, text="Export...", command=accept).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left")
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result or None

    # ---- Other windows ---------------------------------------------------------------------

    def _report_figure(self, **options):
        ssid, band = self._filters()
        title = f"{self.mode_var.get()} - {ssid}" + ("" if band == heatmap.BANDS[0] else f" ({band})")
        options.setdefault("show_aps", self.show_aps_var.get())
        return heatmap.render_figure(self.floorplan, self.heatmap, self.points, self.opacity_var.get(),
                                     title=title, **options)

    def show_report(self):
        if self.floorplan is None or self.heatmap is None:
            messagebox.showinfo("Report", "Take some measurements first.")
            return
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        window = tk.Toplevel(self.root)
        window.title("Heatmap Report")
        figure_canvas = FigureCanvasTkAgg(self._report_figure(), master=window)
        NavigationToolbar2Tk(figure_canvas, window).update()
        figure_canvas.get_tk_widget().pack(fill="both", expand=True)
        figure_canvas.draw()

    def show_measurements(self):
        window = tk.Toplevel(self.root)
        window.title("Measurements")
        columns = ("point", "ssid", "bssid", "signal", "channel", "band")
        tree = ttk.Treeview(window, columns=columns, show="headings", height=20)
        for column, width in zip(columns, (50, 180, 140, 70, 70, 70)):
            tree.heading(column, text=column.title())
            tree.column(column, width=width, anchor="w")
        for number, point in enumerate(self.points, 1):
            for r in sorted(point["readings"], key=lambda r: -r["Signal"]):
                tree.insert("", "end", values=(number, r["SSID"], r["BSSID"], f'{r["Signal"]} dBm',
                                               r.get("Channel"), r.get("Band")))
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ---- Survey editing --------------------------------------------------------------------

    def undo(self):
        if self.points:
            self.points.pop()
            self.dirty = True
            self.status.set(f"Removed the last point, {len(self.points)} left.")
            self.refresh()

    def clear_survey(self):
        if self.points and messagebox.askyesno("Clear Survey", "Are you sure you want to clear all measurements?"):
            self.points.clear()
            self.dirty = True
            self.refresh()

    def quit(self):
        if self.dirty and self.points:
            answer = messagebox.askyesnocancel("Unsaved survey", "Save the survey before exiting?")
            if answer is None:
                return
            if answer:
                self.save_survey()
                if self.dirty:
                    return
        self.root.destroy()


def convert_legacy(results):
    """Convert the old results.txt format (36 copies of each click, Windows signal %) to survey points."""
    points = []
    for result in results:
        readings = [{"SSID": "", "BSSID": z["BSSID"].lower(),
                     "Signal": BSSID.windows_quality_to_dbm(int(str(z["Signal"]).rstrip("%"))),
                     "Channel": None, "Band": "", "Security": ""} for z in result["Z"]]
        if points and points[-1]["readings"] == readings:
            points[-1]["_xs"].append(result["X"])
            points[-1]["_ys"].append(result["Y"])
        else:
            points.append({"_xs": [result["X"]], "_ys": [result["Y"]], "time": None, "readings": readings})
    for point in points:
        xs, ys = point.pop("_xs"), point.pop("_ys")
        point["x"], point["y"] = sum(xs) / len(xs), sum(ys) / len(ys)
    return points


if __name__ == "__main__":
    root = tk.Tk()
    HeatMapper(root)
    root.mainloop()
