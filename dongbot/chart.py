"""Render the card attached to each post: overhead spray chart + side view at the wall."""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from . import park  # noqa: E402
from .judge import FENCE_CALIBRATION, BattedBall, Verdict  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
FIELD_LINE = "#8a8984"
GRID = "#e4e3df"
BALL = "#d03b3b"
# Wall height: one hue, light -> dark (taller = darker).
WALL_COLORS = {park.CF_RF_WALL_FT: "#7fb0ea", park.RF_CORNER_WALL_FT: "#2a78d6", park.LF_WALL_FT: "#123a73"}


def _verdict_label(v: Verdict) -> tuple[str, str]:
    if v.too_close:
        return "TOO CLOSE TO CALL", INK_2
    return ("✓ DONG", "#1e7a3c") if v.is_dong else ("✗ NOT A DONG", BALL)


def render(ball: BattedBall, v: Verdict, path: str | Path, handle: str = "") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(12, 12), dpi=100, facecolor=SURFACE)
    field = fig.add_axes([0.04, 0.27, 0.92, 0.64])
    side = fig.add_axes([0.09, 0.085, 0.86, 0.14])

    # ---------- header ----------
    label, color = _verdict_label(v)
    fig.text(0.05, 0.955, "Would it dong at Progressive Field?", fontsize=25, weight="bold", color=INK, va="center")
    fig.text(0.95, 0.955, label, fontsize=25, weight="bold", color=color, va="center", ha="right")

    # ---------- overhead view ----------
    field.set_facecolor(SURFACE)
    for name, pts in park.outline().items():
        if name == "outfield_outer":
            continue
        field.plot([p[0] for p in pts], [p[1] for p in pts], color=FIELD_LINE, lw=1.3, solid_capstyle="round")
    stands = park.outline()["outfield_outer"]
    field.plot([p[0] for p in stands], [p[1] for p in stands], color=FIELD_LINE, lw=1.3)

    # the outfield wall, colored by height (one continuous stroke per height)
    run_x: list[float] = []
    run_y: list[float] = []
    run_h = park.wall_height(-45)
    for step in range(-450, 451):
        ang = step / 10
        d, r = park.fence_distance(ang), math.radians(ang)
        h = park.wall_height(min(ang, 44.99))
        if h != run_h:
            field.plot(run_x, run_y, color=WALL_COLORS[run_h], lw=7, solid_capstyle="butt", zorder=3)
            run_x, run_y, run_h = run_x[-1:], run_y[-1:], h
        run_x.append(d * math.sin(r))
        run_y.append(d * math.cos(r))
    field.plot(run_x, run_y, color=WALL_COLORS[run_h], lw=7, solid_capstyle="butt", zorder=3)

    # the batted ball
    r = math.radians(v.spray_angle)
    bx, by = ball.distance * math.sin(r), ball.distance * math.cos(r)
    field.plot([0, bx], [0, by], color=BALL, lw=4, solid_capstyle="round", zorder=4)
    field.plot([bx], [by], marker="x", ms=20, mew=5, color=BALL, zorder=5)
    field.plot([bx], [by], marker="x", ms=20, mew=9, color=SURFACE, zorder=4.5)  # surface ring

    field.set_aspect("equal")
    field.set_xlim(-330, 330)
    field.set_ylim(-95, max(455, by + 25))
    field.axis("off")

    actual = f"{ball.event} at {ball.venue}" if ball.venue else ball.event
    field.text(0.0, 0.17, ball.batter, transform=field.transAxes, fontsize=22, weight="bold", color=INK)
    field.text(0.0, 0.115, actual, transform=field.transAxes, fontsize=16, color=INK_2)
    field.text(0.0, 0.065, f"{ball.exit_velo:.1f} mph  ·  {ball.launch_angle:.0f}°  ·  {ball.distance:.0f} ft",
               transform=field.transAxes, fontsize=16, color=INK_2)

    handles = [Line2D([0], [0], color=c, lw=7, label=f"{h:.0f} ft") for h, c in sorted(WALL_COLORS.items())]
    legend = field.legend(handles=handles, title="Wall height", loc="lower right", bbox_to_anchor=(1.0, 0.03),
                          frameon=False, fontsize=14, title_fontsize=14, labelcolor=INK_2, handlelength=1.6)
    legend.get_title().set_color(INK)

    # ---------- side view ----------
    fl = v.flight
    wall_x = v.fence_ft * FENCE_CALIBRATION
    side.set_facecolor(SURFACE)
    side.plot(fl.xs, fl.ys, color=BALL, lw=2.5, solid_capstyle="round", zorder=3)
    side.plot([wall_x, wall_x], [0, v.wall_ft], color=WALL_COLORS[v.wall_ft], lw=7, solid_capstyle="butt", zorder=4)
    x_max = max(fl.landing_distance, wall_x) + 25
    top = max(fl.apex * 1.18, v.wall_ft * 2.5)
    if v.reaches_wall:
        side.plot([wall_x], [v.height_at_wall], marker="o", ms=9, color=BALL, mec=SURFACE, mew=2, zorder=5)
        height = f"{v.height_at_wall:.1f}" if v.too_close else f"{v.height_at_wall:.0f}"
        note = f"{height} ft high at the {v.wall_ft:.0f}-ft wall"
    else:
        note = f"lands {max(1, round(v.short_by_ft))} ft short of the {v.wall_ft:.0f}-ft wall"
    # label sits in the empty space under the arc, with a leader to the wall
    side.annotate(note, xy=(wall_x, max(v.height_at_wall or 0, v.wall_ft)), xytext=(wall_x * 0.84, top * 0.22),
                  ha="right", va="center", fontsize=14, color=INK,
                  arrowprops=dict(arrowstyle="-", color=INK_2, lw=1, shrinkB=7))
    side.set_xlim(0, x_max)
    side.set_ylim(0, top)
    side.set_xlabel("Distance from home plate (ft)", fontsize=13, color=INK_2)
    side.set_ylabel("Height (ft)", fontsize=13, color=INK_2)
    side.tick_params(colors=INK_2, labelsize=12, length=0)
    side.yaxis.set_major_locator(MaxNLocator(3))
    side.grid(axis="y", color=GRID, lw=1)
    side.set_axisbelow(True)
    for name, spine in side.spines.items():
        spine.set_visible(name == "bottom")
        spine.set_color(FIELD_LINE)

    fig.text(0.05, 0.014, "Flight fitted to Statcast exit velocity, launch angle and projected distance.",
             fontsize=11, color=INK_2)
    if handle:
        fig.text(0.95, 0.014, handle, fontsize=12, color=INK_2, ha="right")

    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path
