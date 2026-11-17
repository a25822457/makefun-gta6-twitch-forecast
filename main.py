"""GTA VI Twitch CCU forecast: hour-1-anchored, size-weighted analogue quantiles.

Design (validated leave-one-comparable-out on the 37 launch comparables shipped
in the kit; see README.md for the numbers):

  * The target is NOT a static pre-launch forecast. At runtime the program sees
    only the case file: hour 1's print (p1), the game's pre-launch history, and
    38-42 past launches' full hourly curves ("comparables"). No network, no
    LightGBM, no Google Trends -- none of those exist inside the sandbox.
  * For each comparable launch, take its release-day log-ratio curve
    r_h = ln(y_h / y_1), h = 2..24. Anchor the forecast at the target's own
    hour-1 print: q_tau(h) = p1 * exp(weighted-quantile_tau(r_h)).
  * Weight each comparable by (a) its kit tier -- comparable 1.0,
    early-access-contaminated 0.5, weak 0.25, unlabelled 0.5 -- and (b) how close
    its own hour-1 size is to the target's: exp(-|ln(h1_comp) - ln(p1_eff)| / 1.0),
    where p1_eff = min(p1, 300_000). The cap is the one deliberate prior in the
    program (see README.md): hour-1 size is the dominant predictor of shape,
    but it is confounded with unlock type -- every hour-1 >= 500k in the pool
    is a PC-simultaneous or early-access launch whose hour 1 already was the
    peak, while GTA VI's hour 1 will be big for a different reason (New Zealand
    / Europe already unlocked before 00:00 UTC; the US, the largest Twitch
    audience, unlocks at hours 5 and 9). Without the cap a 1M hour 1 freezes
    the shape at the flat PC launches (median h19 ratio 0.99x); with it the
    shape is that of a ~300k launch (median h19 ratio 1.30x). The cap costs
    0.002 of LOCO loss on GTA-like targets (0.308 -> 0.310) and 0.014 on big
    targets, i.e. almost nothing if the flat pattern is the true one, and it
    buys ~0.25 of pinball at the evening hours if the rolling pattern is.
  * Smooth each quantile curve with a 3-hour moving average in log space (the
    diurnal curve is smooth; raw weighted quantiles wiggle hour to hour),
    enforce non-decreasing quantiles, round to 2 decimals half-up, clamp to
    (0, 1e9]. Deterministic, stdlib only, ~0.05 s per case.

Fallbacks (a crash or missing output is scored as a constant p1 and takes no
prize, so this program never raises on a case): if there is no usable
comparable pool it falls back to the house baseline (persistence, sigma 0.15);
if hour 1 is missing it uses the last history_hourly print, else 1 viewer.

Run: mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
Grader: python3 -P -s /bot/main.py, Python 3.13 stdlib only, no network, 8 s.
"""

import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a helper
# module shipped beside this file would import (none is shipped; kept for
# parity with the starter).
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]
BASELINE_SIGMA = 0.15
# Log-distance (in ln viewers) over which a comparable's weight falls by e.
SIZE_BANDWIDTH = 1.0
# Hour-1 size used for similarity weighting is capped here (the anchor still
# uses the true hour-1 print). See the module docstring for why.
SIZE_CAP = 300000.0
TIER_WEIGHT = {
    "comparable": 1.0,
    "early-access-contaminated": 0.5,
    "weak": 0.25,
}
DEFAULT_TIER_WEIGHT = 0.5
_TIER_RE = re.compile(r"Tier:\s*([a-z][a-z-]*)")


def round2(x):
    """x rounded to 2 decimals, half up (as the starter rounds it)."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value == int(value) else value


def _parse_time(text):
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def _tier_weight(unlock):
    if not unlock:
        return DEFAULT_TIER_WEIGHT
    m = _TIER_RE.search(unlock)
    if not m:
        return DEFAULT_TIER_WEIGHT
    return TIER_WEIGHT.get(m.group(1), DEFAULT_TIER_WEIGHT)


def _release_day_hours(comp):
    """{hour: viewers} for the comparable's release day, or None if incomplete."""
    try:
        day_start = _parse_time(comp["day_start"])
    except Exception:
        return None
    hours = {}
    for row in comp.get("hourly") or []:
        try:
            t = _parse_time(row["from"])
            viewers = row["viewers"]
        except Exception:
            continue
        if viewers is None or viewers <= 0:
            continue
        h = int((t - day_start).total_seconds() // 3600) + 1
        if 1 <= h <= 24:
            hours[h] = viewers
    if len(hours) != 24 or 1 not in hours:
        return None
    return hours


def _weighted_quantile(pairs, q):
    """Smallest value whose cumulative weight reaches q of the total weight."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    threshold = q * total
    acc = 0.0
    for value, w in pairs:
        acc += w
        if acc >= threshold:
            return value
    return pairs[-1][0]


def _smooth_log(curve):
    """3-hour moving average over hours 2..24 (curve: {hour: log value})."""
    out = {}
    for h in range(2, 25):
        xs = [curve[hh] for hh in range(max(2, h - 1), min(24, h + 1) + 1)]
        out[h] = sum(xs) / len(xs)
    return out


def _baseline_quantiles(p1, hours):
    return {
        h: [round2(min(1e9, max(1.0, p1 * math.exp(z * BASELINE_SIGMA * math.sqrt(h - 1)))))
            for z in Z]
        for h in hours
    }


def forecast_case(case):
    hours = [row["hour"] for row in case.get("forecast") or []]
    if not hours:
        hours = list(range(2, 25))
    # Hour-1 print; fall back to the last pre-checkpoint hourly print, else 1.
    p1 = None
    for k in case.get("known") or []:
        if k.get("hour") == 1 and k.get("viewers"):
            p1 = max(1.0, float(k["viewers"]))
            break
    if p1 is None:
        hist = case.get("history_hourly") or []
        if hist and hist[-1].get("viewers"):
            p1 = max(1.0, float(hist[-1]["viewers"]))
        else:
            p1 = 1.0

    # Comparable pool: complete release-day curves, excluding the target's own
    # pre-release history (Tier: target-history, i.e. the GTA VI category
    # itself before launch -- it has no release day to learn a shape from).
    pool = []
    for comp in case.get("comparables") or []:
        unlock = comp.get("unlock") or ""
        if "target-history" in unlock:
            continue
        name = (comp.get("name") or "")
        if name.startswith("Grand Theft Auto VI"):
            continue
        day_hours = _release_day_hours(comp)
        if day_hours is None:
            continue
        tier_w = _tier_weight(unlock)
        p1_eff = min(p1, SIZE_CAP)
        size_w = math.exp(-abs(math.log(day_hours[1]) - math.log(p1_eff)) / SIZE_BANDWIDTH)
        pool.append((day_hours, tier_w * size_w))
    if not pool:
        return {"hours": [{"hour": h, "q": _baseline_quantiles(p1, [h])[h]} for h in hours]}

    # Weighted quantiles of the log-ratio curves, per hour.
    log_q = {tau: {} for tau in LEVELS}
    for h in range(2, 25):
        pairs = [(math.log(day_hours[h] / day_hours[1]), w) for day_hours, w in pool]
        for tau in LEVELS:
            log_q[tau][h] = _weighted_quantile(pairs, tau)
    # Smooth each quantile curve in log space, then rebuild, sort (monotone),
    # round and clamp. Hours outside 2..24 (should not happen) use the baseline.
    for tau in LEVELS:
        log_q[tau] = _smooth_log(log_q[tau])
    out = []
    for h in hours:
        if h in log_q[LEVELS[0]]:
            qs = sorted(round2(min(1e9, max(1.0, p1 * math.exp(log_q[tau][h])))) for tau in LEVELS)
        else:
            qs = _baseline_quantiles(p1, [h])[h]
        out.append({"hour": h, "q": qs})
    return {"hours": out}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            forecast = forecast_case(case)
        except Exception:
            # Never fail a case: emit the house baseline shape around 1 viewer
            # (a valid file) rather than no file at all.
            forecast = {"hours": [{"hour": h, "q": [1, 1, 1, 1, 1]} for h in range(2, 25)]}
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
