from dataclasses import dataclass, field

import numpy as np
from matplotlib import colors as mcolors
from matplotlib import colormaps
from matplotlib.cm import ScalarMappable
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from PIL import Image
from scipy.interpolate import RBFInterpolator
from scipy.spatial import cKDTree

ALL_NETWORKS = "All networks"
BANDS = ("All bands", "2.4 GHz", "5 GHz", "6 GHz")
MODES = ("Signal Strength", "Secondary Coverage", "Number of APs", "Channel Overlap", "Strongest AP")

NOT_HEARD_DBM = -100.0
GRID_MAX = 360

SIGNAL_RANGE = (-90, -30)
SIGNAL_STOPS = [
    (-90, "#9e0000"), (-85, "#e30000"), (-80, "#ff5500"), (-75, "#ff9a00"), (-70, "#ffd200"),
    (-67, "#f4ff00"), (-60, "#a8f000"), (-50, "#3ccf3c"), (-40, "#00a541"), (-30, "#006b31"),
]
SIGNAL_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "ekahau_signal",
    [((v - SIGNAL_RANGE[0]) / (SIGNAL_RANGE[1] - SIGNAL_RANGE[0]), c) for v, c in SIGNAL_STOPS])

COUNT_COLORS = ["#e30000", "#ff9a00", "#f4ff00", "#a8f000", "#3ccf3c", "#00a541", "#006b31"]
OVERLAP_COLORS = ["#3ccf3c", "#f4ff00", "#ff9a00", "#e30000", "#9e0000"]

UNITS = {
    "Signal Strength": "Signal strength (dBm)",
    "Secondary Coverage": "Secondary signal strength (dBm)",
    "Number of APs": "Access points heard",
    "Channel Overlap": "APs on the same channel",
    "Strongest AP": "",
}


@dataclass
class Heatmap:
    mode: str
    size: tuple
    grid_x: np.ndarray
    grid_y: np.ndarray
    values: np.ndarray
    alpha: np.ndarray
    primary: np.ndarray
    best_ap: np.ndarray
    cmap: object
    norm: object
    aps: dict
    ticks: list = field(default_factory=list)
    tick_labels: list = None

    def rgba(self, opacity=0.65):
        valid = ~np.isnan(self.values)
        rgba = self.cmap(self.norm(np.where(valid, self.values, self.norm.vmin)))
        rgba[..., 3] = np.where(valid, self.alpha * opacity, 0.0)
        return rgba

    def overlay(self, size, opacity=0.65):
        """RGBA PIL image of the heatmap resized to `size` (width, height)."""
        image = Image.fromarray((self.rgba(opacity) * 255).astype(np.uint8), "RGBA")
        return image.convert("RGBa").resize(size, Image.BILINEAR).convert("RGBA")

    def describe(self, x, y):
        """Human readable value at image coordinate (x, y), or None outside the surveyed area."""
        w, h = self.size
        col = min(len(self.grid_x) - 1, max(0, int(x / w * len(self.grid_x))))
        row = min(len(self.grid_y) - 1, max(0, int(y / h * len(self.grid_y))))
        if self.alpha[row, col] <= 0 or np.isnan(self.primary[row, col]):
            return None
        ap = self.aps[list(self.aps)[self.best_ap[row, col]]]
        strongest = f'{self.primary[row, col]:.0f} dBm from {ap["SSID"] or "<hidden>"} ({ap["BSSID"]}, ch {ap["Channel"]})'
        value = self.values[row, col]
        if self.mode in ("Signal Strength", "Strongest AP") or np.isnan(value):
            return strongest
        if self.mode == "Secondary Coverage":
            return f"Secondary {value:.0f} dBm | strongest {strongest}"
        return f"{UNITS[self.mode]}: {value:.0f} | strongest {strongest}"


def reading_matches(reading, ssid=None, band=None):
    return ((not ssid or ssid == ALL_NETWORKS or reading["SSID"] == ssid)
            and (not band or band == BANDS[0] or reading.get("Band") == band))


def best_signal(point, ssid=None, band=None):
    signals = [r["Signal"] for r in point["readings"] if reading_matches(r, ssid, band)]
    return max(signals) if signals else None


def access_points(points, ssid=None, band=None):
    """Every BSSID heard during the survey, with an estimated location (where it was strongest)."""
    aps = {}
    for point in points:
        for reading in point["readings"]:
            if not reading_matches(reading, ssid, band):
                continue
            ap = aps.setdefault(reading["BSSID"], {
                "BSSID": reading["BSSID"], "SSID": reading["SSID"], "Channel": reading.get("Channel"),
                "Band": reading.get("Band", ""), "samples": []})
            ap["samples"].append((point["x"], point["y"], reading["Signal"]))
    for ap in aps.values():
        samples = np.array(ap.pop("samples"), dtype=float)
        ap["Best"] = samples[:, 2].max()
        near_peak = samples[samples[:, 2] >= ap["Best"] - 6]
        weights = 10 ** (near_peak[:, 2] / 10)
        ap["x"], ap["y"] = np.average(near_peak[:, :2], axis=0, weights=weights)
    return dict(sorted(aps.items(), key=lambda item: (item[1]["SSID"], item[0])))


def _channels_overlap(a, b):
    if a["Channel"] is None or b["Channel"] is None or a["Band"] != b["Band"]:
        return False
    if a["Band"] == "2.4 GHz":
        return abs(a["Channel"] - b["Channel"]) < 5
    return a["Channel"] == b["Channel"]


def compute(points, size, ssid=None, band=None, mode=MODES[0], min_signal=-85, overlap_signal=-85,
            radius=None):
    """Interpolate each access point's signal over the floor plan and derive the requested view.
    `size` is the floor plan (width, height) in pixels; point coordinates are in the same space."""
    aps = access_points(points, ssid, band)
    if not points or not aps:
        return None

    w, h = size
    scale = min(1.0, GRID_MAX / max(w, h))
    gw, gh = max(2, round(w * scale)), max(2, round(h * scale))
    grid_x = (np.arange(gw) + 0.5) * w / gw
    grid_y = (np.arange(gh) + 0.5) * h / gh
    gx, gy = np.meshgrid(grid_x, grid_y)
    grid = np.column_stack([gx.ravel(), gy.ravel()])

    xy = np.array([(p["x"], p["y"]) for p in points], dtype=float)
    index = {bssid: i for i, bssid in enumerate(aps)}
    samples = np.full((len(points), len(aps)), NOT_HEARD_DBM)
    for row, point in enumerate(points):
        for reading in point["readings"]:
            col = index.get(reading["BSSID"])
            if col is not None and reading_matches(reading, ssid, band):
                samples[row, col] = max(samples[row, col], reading["Signal"])

    diagonal = float(np.hypot(w, h))
    tree = cKDTree(xy)
    if len(points) > 1:
        spacing = float(np.median(tree.query(xy, k=2)[0][:, 1]))
    else:
        spacing = diagonal / 15
    spacing = max(spacing, diagonal / 100)

    # One multiquadric RBF fit for all APs at once; smoothing absorbs the few dB of scan-to-scan noise
    interpolator = RBFInterpolator(
        xy / spacing, samples, kernel="multiquadric", epsilon=1.0, degree=0,
        smoothing=0.5, neighbors=None if len(points) <= 300 else 80)
    signal = np.clip(interpolator(grid / spacing), NOT_HEARD_DBM, -20)

    radius = radius or max(3 * spacing, diagonal * 0.06)
    distance = tree.query(grid)[0]
    alpha = np.clip((radius - distance) / (0.35 * radius), 0, 1)

    order = np.argsort(-signal, axis=1)
    primary = np.take_along_axis(signal, order[:, :1], axis=1)[:, 0]
    secondary = (np.take_along_axis(signal, order[:, 1:2], axis=1)[:, 0]
                 if signal.shape[1] > 1 else np.full(len(grid), NOT_HEARD_DBM))
    best_ap = order[:, 0]
    covered = primary >= min_signal
    ticks, tick_labels = [], None

    if mode in ("Signal Strength", "Secondary Coverage"):
        values = primary if mode == "Signal Strength" else secondary
        values = np.where(values >= min_signal, values, np.nan)
        cmap = SIGNAL_CMAP
        norm = mcolors.Normalize(*SIGNAL_RANGE)
        ticks = list(range(SIGNAL_RANGE[0], SIGNAL_RANGE[1] + 1, 10)) + [-67]
    elif mode == "Number of APs":
        values = np.where(covered, np.minimum((signal >= min_signal).sum(axis=1), len(COUNT_COLORS) - 1), np.nan)
        cmap = mcolors.ListedColormap(COUNT_COLORS)
        norm = mcolors.BoundaryNorm(np.arange(len(COUNT_COLORS) + 1) - 0.5, cmap.N)
        ticks = list(range(len(COUNT_COLORS)))
        tick_labels = [str(t) for t in ticks[:-1]] + [f"{ticks[-1]}+"]
    elif mode == "Channel Overlap":
        ap_list = list(aps.values())
        overlaps = np.array([[_channels_overlap(a, b) for b in ap_list] for a in ap_list])
        heard = signal >= overlap_signal
        counts = (overlaps[best_ap] & heard).sum(axis=1)
        values = np.where(covered, np.clip(counts, 1, len(OVERLAP_COLORS)), np.nan)
        cmap = mcolors.ListedColormap(OVERLAP_COLORS)
        norm = mcolors.BoundaryNorm(np.arange(len(OVERLAP_COLORS) + 1) + 0.5, cmap.N)
        ticks = list(range(1, len(OVERLAP_COLORS) + 1))
        tick_labels = [str(t) for t in ticks[:-1]] + [f"{ticks[-1]}+"]
    elif mode == "Strongest AP":
        values = np.where(covered, best_ap.astype(float), np.nan)
        palette = colormaps["tab20"]
        cmap = mcolors.ListedColormap([palette(i % 20) for i in range(len(aps))])
        norm = mcolors.BoundaryNorm(np.arange(len(aps) + 1) - 0.5, cmap.N)
    else:
        raise ValueError(f"Unknown mode {mode!r}")

    return Heatmap(
        mode=mode, size=(w, h), grid_x=grid_x, grid_y=grid_y,
        values=values.reshape(gh, gw), alpha=alpha.reshape(gh, gw),
        primary=np.where(covered, primary, np.nan).reshape(gh, gw), best_ap=best_ap.reshape(gh, gw),
        cmap=cmap, norm=norm, aps=aps, ticks=sorted(ticks), tick_labels=tick_labels)


def point_color(signal):
    if signal is None:
        return "#808080"
    return mcolors.to_hex(SIGNAL_CMAP(mcolors.Normalize(*SIGNAL_RANGE)(signal)))


def render_figure(floorplan, heatmap, points, opacity=0.65, title="", show_aps=True,
                  show_points=True, show_names=True, show_contours=True,
                  contour_levels=(-67, -75)):
    """Report-style figure: floor plan, heatmap, contours, survey route, APs and legend."""
    w, h = floorplan.size
    fig_w = 12.0
    fig = Figure(figsize=(fig_w, max(4.0, fig_w * h / w * 0.85)), dpi=100)
    ax = fig.add_subplot()
    ax.imshow(floorplan.convert("RGB"), extent=(0, w, h, 0))
    ax.imshow(heatmap.rgba(opacity), extent=(0, w, h, 0), interpolation="bilinear")

    if show_contours and contour_levels and heatmap.mode in ("Signal Strength", "Secondary Coverage"):
        contour_values = np.where(heatmap.alpha > 0.5, heatmap.values, np.nan)
        if np.isfinite(contour_values).any():
            lines = ax.contour(heatmap.grid_x, heatmap.grid_y, contour_values, levels=sorted(set(contour_levels)),
                               colors="black", linewidths=0.7, alpha=0.6)
            ax.clabel(lines, fmt="%d dBm", fontsize=7)

    if show_points and points:
        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        ax.plot(xs, ys, "-", color="#1d3f8f", linewidth=1, alpha=0.5)
        ax.scatter(xs, ys, s=12, c="#1d3f8f", edgecolors="white", linewidths=0.6, zorder=3)

    if show_aps:
        for ap in heatmap.aps.values():
            ax.scatter(ap["x"], ap["y"], marker="^", s=90, c="#2b2b2b", edgecolors="white", zorder=4)
            label = f'ch {ap["Channel"]}'
            if show_names:
                label = f'{ap["SSID"] or "<hidden>"}\n{label}'
            ax.annotate(label, (ap["x"], ap["y"]),
                        xytext=(6, 6), textcoords="offset points", fontsize=7,
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.75, lw=0))

    if heatmap.mode == "Strongest AP":
        handles = [Patch(color=heatmap.cmap(i), label=(f'{ap["SSID"] or "<hidden>"} ' if show_names else "") + f'{ap["BSSID"]} ch {ap["Channel"]}')
                   for i, ap in enumerate(heatmap.aps.values())]
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=7, frameon=False)
    else:
        colorbar = fig.colorbar(ScalarMappable(norm=heatmap.norm, cmap=heatmap.cmap), ax=ax,
                                fraction=0.035, pad=0.02, ticks=heatmap.ticks)
        colorbar.set_label(UNITS[heatmap.mode])
        if heatmap.tick_labels:
            colorbar.set_ticklabels(heatmap.tick_labels)

    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.set_axis_off()
    ax.set_title(title or heatmap.mode)
    fig.tight_layout()
    return fig
