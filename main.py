"""GTA VI Twitch CCU forecast v6: v2 analogue quantiles plus a size regime
switch (v2 + REG-SW200 full regression quantiles).

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
    early-access-contaminated 0.5, weak 0.25, unlabelled 0.5; (b) how close its
    own hour-1 size is to the target's: exp(-|ln(h1_comp) - ln(p1)| / 1.0);
    hour-1 size is the dominant predictor of shape (corr(log h1, log h19/h1)
    = -0.93 across the pool); and (c) platform similarity: a comparable whose
    console-only status matches the target's gets exp(+0.5), one that does not
    gets exp(-0.5). The target's console-only status is parsed from the case
    notes ("console only" / "PS5 only" / a released-on clause naming only
    consoles); if the notes do not say, the factor is skipped.
  * v1 capped the size used for similarity at 300k, on the theory that every
    hour-1 >= 500k launch in the pool is a PC-simultaneous or early-access
    launch whose hour 1 already was the peak, while GTA VI's hour 1 will be
    big for a different reason (New Zealand / Europe already unlocked before
    00:00 UTC; the US unlocks at hours 5 and 9). v2 DROPS the cap: with the
    console-only factor in, the cap no longer changes the 1M-hour-1 shape
    (median h19 1.25x without the cap vs 1.30x with it -- the console-only
    launches, not the flat PC launches, dominate the weighted median), and
    dropping it improves LOCO on every subset (see README.md).
  * v6 REGIME SWITCH: when p1 >= 200,000, the quantiles come from a per-hour
    weighted regression of ln(y_h/y_1) on ln(h1) instead of weighted
    quantiles (same pool weights; slope shrunk toward the pooled all-hours
    slope with alpha = 1.0, i.e. no shrinkage; spread from the weighted
    quantiles of the per-hour residuals around the fitted line). Below
    200,000 the v2 weighted-quantile model is used unchanged. LOCO:
    GTA-like 0.292 (v2: 0.299), rolling 0.240 (0.251), practice-like 0.173
    (0.188), big-h1 0.200 (0.215), overall 0.410 (0.413). KNOWN CONCERN:
    at a synthetic h1 = 1M rolling console-only target the regression
    predicts an h19 median of only 0.88x the hour-1 print (v2: 1.25x),
    while the pool's only big rolling console-only precedent (The Last of
    Us Part II, h1 365,019) really reached h19/h1 = 1.31. The regression
    slope is dominated by big PC-simultaneous launches whose hour 1 is
    already the peak, so linear extrapolation to 1M flattens the evening;
    GTA VI's hour 1 excludes the US audience (US East joins at hour 5-6,
    US West at hour 8-9), so its evening should rise. The user chose this
    exact tested variant knowing that trade-off; no floor, cap or blend
    was added.
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
# Log-weight bonus/penalty for matching / mismatching console-only status.
CONSOLE_MATCH = 0.5
# Hour-1 print at/above which the per-hour log-h1 regression replaces the
# weighted-quantile model (v4 "REG-SW200 full reg" variant).
REGIME_THRESHOLD = 200000.0
# Slope shrinkage toward the pooled all-hours slope in the regression branch
# (alpha = 1.0: no shrinkage, as tested in v4).
REGRESSION_ALPHA = 1.0
TIER_WEIGHT = {
    "comparable": 1.0,
    "early-access-contaminated": 0.5,
    "weak": 0.25,
}
DEFAULT_TIER_WEIGHT = 0.5
_TIER_RE = re.compile(r"Tier:\s*([a-z][a-z-]*)")
_RELEASED_ON_RE = re.compile(r"released\s+\S+\s+on\s+([^;.(]+)", re.IGNORECASE)
_CONSOLE_PHRASES = ("console only", "console-only", "ps5 only", "ps5-only", "ps4 only")
_CONSOLE_NAMES = ("ps5", "ps4", "xbox", "switch")


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


def _is_console_only_platforms(platforms):
    """True when a comparable's platform list names no PC release."""
    return "PC" not in (platforms or "")


def _console_only_target(case):
    """The target's console-only status from its case notes.

    True when the notes say "console only" / "PS5 only", or when the
    released-on clause names only consoles; False when that clause names a
    PC release; None when the notes do not say either way (the similarity
    factor is then skipped). Checked against the four practice cases:
    Wolverine ("PS5 only"), RDR2 ("console only"), GoW Ragnarok (released
    on PS5, PS4), Spider-Man 2 ("PS5 only") all parse True.
    """
    notes = case.get("notes") or ""
    if not notes:
        return None
    text = notes.lower()
    if any(p in text for p in _CONSOLE_PHRASES):
        return True
    m = _RELEASED_ON_RE.search(notes)
    if not m:
        return None
    plat = m.group(1).lower()
    if "pc" in plat:
        return False
    if any(k in plat for k in _CONSOLE_NAMES):
        return True
    return None


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


def _wmean(xs, ws):
    return sum(x * w for x, w in zip(xs, ws)) / sum(ws)


def _wls(xs, ys, ws):
    """Weighted least squares y ~ a + b*x. Returns (a, b)."""
    xb, yb = _wmean(xs, ws), _wmean(ys, ws)
    num = sum(w * (x - xb) * (y - yb) for x, y, w in zip(xs, ys, ws))
    den = sum(w * (x - xb) ** 2 for x, w in zip(xs, ws))
    b = num / den if den > 0 else 0.0
    return yb - b * xb, b


def _regression_log_quantiles(p1, pool):
    """Per-hour log-h1 regression quantiles (v4 "REG-SW200 full reg").

    pool: [(day_hours, weight)] with the same weights as the v2 branch.
    For each hour h, weighted regression of ln(y_h/y_1) on ln(h1); the
    slope is shrunk toward the pooled all-hours slope by REGRESSION_ALPHA
    (1.0: no shrinkage). Median = fitted value at ln(p1); spread = the
    weighted quantiles of the per-hour residuals around the fitted line.
    Returns {tau: {hour: log-ratio}} in the same shape as the v2 branch.
    """
    lp1 = math.log(p1)
    # Pooled slope over all hours, for the shrinkage target.
    px, py, pw = [], [], []
    for day_hours, w in pool:
        lx = math.log(day_hours[1])
        for h in range(2, 25):
            px.append(lx)
            py.append(math.log(day_hours[h] / day_hours[1]))
            pw.append(w)
    _, b_pool = _wls(px, py, pw)
    log_q = {tau: {} for tau in LEVELS}
    for h in range(2, 25):
        xs, ys, ws = [], [], []
        for day_hours, w in pool:
            xs.append(math.log(day_hours[1]))
            ys.append(math.log(day_hours[h] / day_hours[1]))
            ws.append(w)
        _, b = _wls(xs, ys, ws)
        b = REGRESSION_ALPHA * b + (1 - REGRESSION_ALPHA) * b_pool
        a = _wmean(ys, ws) - b * _wmean(xs, ws)
        med = a + b * lp1
        res = [(y - (a + b * x), w) for x, y, w in zip(xs, ys, ws)]
        for tau in LEVELS:
            log_q[tau][h] = med + _weighted_quantile(res, tau)
    return log_q


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

    target_console = _console_only_target(case)

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
        w = _tier_weight(unlock)
        w *= math.exp(-abs(math.log(day_hours[1]) - math.log(p1)) / SIZE_BANDWIDTH)
        if target_console is not None:
            match = _is_console_only_platforms(comp.get("platforms")) == target_console
            w *= math.exp(CONSOLE_MATCH if match else -CONSOLE_MATCH)
        pool.append((day_hours, w))
    if not pool:
        return {"hours": [{"hour": h, "q": _baseline_quantiles(p1, [h])[h]} for h in hours]}

    if p1 >= REGIME_THRESHOLD:
        # Big hour-1 regime: per-hour log-h1 regression quantiles.
        log_q = _regression_log_quantiles(p1, pool)
    else:
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
