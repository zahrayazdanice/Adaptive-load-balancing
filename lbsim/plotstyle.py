"""Shared figure style: one fixed colour per policy, quiet chrome, thin marks."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
DEEMPH = "#bdbbb3"
ACCENT = "#2a78d6"

# first six categorical slots of the validated palette, in slot order;
# colour follows the policy everywhere (figures and demo)
COLORS = {
    "ased": "#2a78d6",
    "lrt": "#eb6834",
    "lc": "#1baf7a",
    "p2c": "#eda100",
    "wrr": "#e87ba4",
    "rr": "#008300",
}
COLORS_DARK = {"ased": "#3987e5", "lrt": "#d95926", "lc": "#199e70", "p2c": "#c98500",
               "wrr": "#d55181", "rr": "#008300"}
DASHES = {"rr": (1, 1.5), "wrr": (5, 1.5), "lc": (2, 1.2)}
BLUES = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
         "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
ORDINAL = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]


def setup():
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.labelcolor": INK2,
        "axes.titlesize": 10,
        "axes.titleweight": "semibold",
        "axes.titlecolor": INK,
        "axes.titlelocation": "left",
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "grid.linestyle": "-",
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK2,
        "ytick.labelcolor": INK2,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "lines.linewidth": 1.6,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
    })


def hbars(ax, labels, values, colors, err=None, height=0.62, radius_px=3.0, fmt="{:.0f}",
          label_values=True):
    """Thin horizontal bars, square at the baseline and rounded at the data end."""
    n = len(values)
    vmax = max(v + (e if err is not None else 0) for v, e in zip(values, err if err is not None else [0] * n))
    ax.set_xlim(0, vmax * 1.18)
    ax.set_ylim(n - 0.5, -0.5)
    ax.figure.canvas.draw()
    x0, y0 = ax.transData.transform((0, 0))
    x1, y1 = ax.transData.transform((1, 1))
    px_x, px_y = abs(x1 - x0), abs(y1 - y0)
    r = radius_px / px_x
    aspect = px_x / px_y    # y-radius = r * mutation_aspect
    for i, (v, c) in enumerate(zip(values, colors)):
        if v <= 0:
            if label_values:
                ax.text(vmax * 0.01, i, fmt.format(0), va="center", ha="left", fontsize=7.5, color=INK2)
            continue
        rr = min(r, v / 2)
        ax.add_patch(FancyBboxPatch((0, i - height / 2), v, height,
                                    boxstyle=f"round,pad=0,rounding_size={rr}",
                                    mutation_aspect=aspect, linewidth=0, facecolor=c, zorder=2))
        ax.add_patch(Rectangle((0, i - height / 2), min(v, rr * 1.2), height, linewidth=0,
                               facecolor=c, zorder=2))
        if err is not None and err[i] == err[i]:
            ax.plot([v - err[i], v + err[i]], [i, i], color=INK, lw=0.9, zorder=3,
                    solid_capstyle="butt")
        if label_values:
            xe = v + (err[i] if err is not None and err[i] == err[i] else 0)
            ax.text(xe + vmax * 0.02, i, fmt.format(v), va="center", ha="left",
                    fontsize=7.5, color=INK2)
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels)
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)


def end_label(ax, x, y, text, color=INK2, dx=4):
    ax.annotate(text, (x, y), xytext=(dx, 0), textcoords="offset points", va="center",
                ha="left", fontsize=7.5, color=color)


def plain_log(axis, subs=(1.0, 2.0, 5.0)):
    """Log axis with plain numbers (100, 200, 500) instead of powers of ten."""
    axis.set_major_locator(LogLocator(base=10, subs=subs))
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}"))
    axis.set_minor_formatter(NullFormatter())
