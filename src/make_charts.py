"""Figures for the README.

1. cost_curve.png              -- annual cost by staffing quantile, showing the
                                  newsvendor optimum and why the mean is wrong.
2. storm_distribution.png      -- storm-day volume ratios against ordinary days,
                                  the reason a generic surge undershoots.
3. shortfall_concentration.png -- cumulative curve showing that half of all
                                  unmet demand comes from 5% of days.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"

CONTACTS_PER_AGENT_DAY = 55
COST_OVER_AGENT_DAY = 21.53 * 1.35 * 8.0
COST_PER_CONTACT = 4.15
UNDER_MULTIPLIER = 2.5

INK = "#1a1a1a"
ACCENT = "#c1440e"
BLUE = "#2b6cb0"
GREY = "#9aa0a6"
GRID = "#d9d9d9"


def style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)


def policy_cost(actual, staffed, m=UNDER_MULTIPLIER):
    c_over = COST_OVER_AGENT_DAY / CONTACTS_PER_AGENT_DAY
    over = np.maximum(staffed - actual, 0) * c_over
    under = np.maximum(actual - staffed, 0) * COST_PER_CONTACT * m
    return over + under


def chart_cost_curve(ev):
    qs = [50, 60, 70, 75, 80, 85, 90, 95]
    a = ev["contacts"].to_numpy()
    costs, overs, unders = [], [], []
    c_over_pc = COST_OVER_AGENT_DAY / CONTACTS_PER_AGENT_DAY
    for q in qs:
        s = ev[f"fq{q}"].to_numpy()
        overs.append(np.maximum(s - a, 0).mean() * c_over_pc * 250)
        unders.append(np.maximum(a - s, 0).mean() * COST_PER_CONTACT
                      * UNDER_MULTIPLIER * 250)
        costs.append(policy_cost(a, s).mean() * 250)

    point = policy_cost(a, ev["f_dow_med"].to_numpy()).mean() * 250
    best_i = int(np.argmin(costs))

    fig, ax = plt.subplots(figsize=(7.6, 5.2), dpi=160)
    style(ax)

    ax.plot(qs, np.array(costs) / 1000, marker="o", markersize=7, linewidth=2.2,
            color=BLUE, label="total cost", zorder=3)
    ax.plot(qs, np.array(overs) / 1000, linewidth=1.4, linestyle="--",
            color=GREY, label="cost of idle capacity", zorder=2)
    ax.plot(qs, np.array(unders) / 1000, linewidth=1.4, linestyle=":",
            color=ACCENT, label="cost of unmet demand", zorder=2)

    ax.scatter([qs[best_i]], [costs[best_i] / 1000], s=170, facecolors="none",
               edgecolors=ACCENT, linewidths=2.2, zorder=4)
    ax.annotate(f"optimum: staff to the {qs[best_i]}th percentile",
                (qs[best_i], costs[best_i] / 1000),
                textcoords="offset points", xytext=(10, -34),
                fontsize=9.5, color=INK)

    ax.axhline(point / 1000, color=INK, linewidth=1.2, alpha=0.5)
    ax.annotate(f"point forecast (mean-optimal): \\${point / 1000:.0f}k",
                (95, point / 1000), textcoords="offset points",
                xytext=(-6, 8), fontsize=9, color=INK, ha="right")

    ax.set_xlabel("Staffing level (percentile of the forecast demand distribution)",
                  fontsize=10, color=INK)
    ax.set_ylabel("Annual cost (\\$ thousands)", fontsize=10, color=INK)
    ax.set_title("When the costs of being wrong are asymmetric,\n"
                 "the best forecast is not the most accurate one",
                 fontsize=12, color=INK, pad=12, loc="left")
    ax.legend(frameon=False, fontsize=9, loc="upper left")

    fig.text(0.01, -0.06,
             "3,165 weekdays, 2014-2026. Costs anchored to BLS median CSR wage "
             "(\\$21.53/hr, May 2025, loaded 1.35x)\nand the published "
             "\\$2.70-\\$5.60 cost-per-call benchmark. Unhandled contacts assumed "
             "to cost 2.5x a handled one.",
             fontsize=8, color="#666666", ha="left")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "cost_curve.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"saved: {out}", flush=True)


def chart_storm_distribution(ev):
    storm = ev.loc[ev["snow_trigger"], "ratio"].dropna()
    normal = ev.loc[~ev["snow_trigger"], "ratio"].dropna()

    fig, ax = plt.subplots(figsize=(7.6, 5.0), dpi=160)
    style(ax)

    bins = np.arange(0.6, 2.8, 0.06)
    ax.hist(normal, bins=bins, density=True, color=GREY, alpha=0.55,
            label=f"ordinary days (n={len(normal):,})")
    ax.hist(storm, bins=bins, density=True, color=ACCENT, alpha=0.75,
            label=f'days after 4"+ snow (n={len(storm)})')

    ax.axvline(normal.quantile(0.90), color=INK, linewidth=1.3, linestyle="--")
    ax.annotate("90th pct of an\nordinary day: 1.14x",
                (normal.quantile(0.90), 3.1), textcoords="offset points",
                xytext=(8, 0), fontsize=9, color=INK)

    ax.axvline(storm.quantile(0.90), color=ACCENT, linewidth=1.3, linestyle="--")
    ax.annotate("90th pct of a\nstorm day: 1.93x",
                (storm.quantile(0.90), 2.0), textcoords="offset points",
                xytext=(8, 0), fontsize=9, color=ACCENT)

    ax.set_xlim(0.6, 2.8)
    ax.set_xlabel("Actual volume / forecast volume", fontsize=10, color=INK)
    ax.set_ylabel("Density", fontsize=10, color=INK)
    ax.set_title("Storm days are drawn from a different distribution",
                 fontsize=12, color=INK, pad=12, loc="left")
    ax.legend(frameon=False, fontsize=9, loc="upper right")

    fig.text(0.01, -0.06,
             "This is why a surge sized from the ordinary-day distribution "
             "undershoots. Staffing storm days to the\n90th percentile of NORMAL "
             "variation buys 1.14x capacity for an event that routinely runs 1.9x "
             "and reached 2.6x.",
             fontsize=8, color="#666666", ha="left")

    out = REPORTS / "storm_distribution.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"saved: {out}", flush=True)


def chart_concentration(ev):
    short = np.maximum(ev["contacts"] - ev["fq70"], 0).to_numpy()
    short = np.sort(short)[::-1]
    cum = np.cumsum(short) / short.sum()
    x = np.arange(1, len(short) + 1) / len(short) * 100

    fig, ax = plt.subplots(figsize=(7.6, 5.0), dpi=160)
    style(ax)

    ax.plot(x, cum * 100, linewidth=2.4, color=BLUE, zorder=3)
    ax.plot([0, 100], [0, 100], linewidth=1, linestyle="--",
            color=INK, alpha=0.4, label="if spread evenly across days")

    for pct in (1, 5, 10):
        i = max(0, int(len(short) * pct / 100) - 1)
        y = cum[i] * 100
        ax.scatter([pct], [y], s=60, color=ACCENT, zorder=4)
        ax.annotate(f"{pct}% of days -> {y:.0f}% of unmet demand",
                    (pct, y), textcoords="offset points", xytext=(12, -4),
                    fontsize=9.5, color=INK)

    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Days, ranked worst first (%)", fontsize=10, color=INK)
    ax.set_ylabel("Cumulative share of unmet demand (%)", fontsize=10, color=INK)
    ax.set_title("Unmet demand is concentrated, so the answer is a surge plan -\n"
                 "not more baseline headcount",
                 fontsize=12, color=INK, pad=12, loc="left")
    ax.legend(frameon=False, fontsize=9, loc="lower right")

    fig.text(0.01, -0.06,
             "Under the recommended 70th-percentile policy. Baseline staffing "
             "absorbs routine variation; the\nresidual risk sits almost entirely "
             "in a handful of days, and those days are predictable from weather.",
             fontsize=8, color="#666666", ha="left")

    out = REPORTS / "shortfall_concentration.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"saved: {out}", flush=True)


def main():
    ev = pd.read_parquet(PROC / "storm_model_eval.parquet")
    print(f"days: {len(ev):,}", flush=True)
    chart_cost_curve(ev)
    chart_storm_distribution(ev)
    chart_concentration(ev)


if __name__ == "__main__":
    main()