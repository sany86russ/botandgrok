
import os
from typing import Dict, Any, Optional
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt

def _fmt(x: float) -> str:
    if x is None: return "-"
    if x >= 1: return f"{x:.4f}"
    return f"{x:.6f}"

def render_signal_plan(payload: Dict[str, Any], out_dir: str, fname: Optional[str]=None) -> Optional[str]:
    """
    Draws a clean plan image with Entry / TP1 / TP2 / TP3 / SL + R-levels (1R/2R/3R)
    and fraction annotations for TP1/TP2/TP3.
    Returns path to saved PNG.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:
        # Matplotlib not available; caller should handle None
        return None
    os.makedirs(out_dir, exist_ok=True)
    sym = payload.get("symbol","SYMBOL")
    side = (payload.get("side") or "").upper()
    entry = float(payload.get("entry", 0) or 0)
    tp1 = float(payload.get("tp1", 0) or 0)
    tp2 = float(payload.get("tp2", 0) or 0)
    tp3 = float(payload.get("tp3", 0) or 0)
    sl  = float(payload.get("sl", 0) or 0)
    rr  = float(payload.get("R_target", 2.0) or 2.0)
    f1  = float(payload.get("frac1", 0.5) or 0.5)
    f2  = float(payload.get("frac2", 0.3) or 0.3)
    regime = payload.get("regime","-")
    strategy = (payload.get("strategy_type") or "UNKNOWN").upper()

    # fallback if tp3 not present
    if (not tp3) and entry and payload.get("atr_pct"):
        try:
            atrp = float(payload.get("atr_pct"))
            step = entry * (atrp/100.0) * 3.0
            tp3 = entry + step if side=="LONG" else entry - step
        except Exception:
            tp3 = 0.0

    # Compute R levels
    risk_dist = abs(entry - sl) if entry and sl else 0.0
    r_levels = []
    if risk_dist > 0:
        direction = 1 if side=="LONG" else -1
        for k in (1,2,3):
            r_levels.append((k, entry + direction * risk_dist * k))

    levels = [x for x in [sl, entry, tp1, tp2, tp3] if x]
    levels += [lv for _, lv in r_levels if lv]  # include for bounds
    if not levels:
        levels = [1.0, 1.0]
    lo = min(levels)
    hi = max(levels)
    pad = (hi - lo) * 0.2 if hi > lo else (lo*0.03 if lo>0 else 1.0)
    lo -= pad
    hi += pad

    fig = plt.figure(figsize=(7.5, 6.5), dpi=150)
    ax = plt.gca()
    ax.set_title(f"{sym} | {strategy} | {side}\nEntry/TP/SL plan (R={rr}  f1={f1:.2f}  f2={f2:.2f})", loc="left")

    # draw horizontal levels
    def hline(y, label, lw=2.0, style='-'):
        ax.axhline(y, linestyle=style, linewidth=lw)
        ax.text(0.02, y, f" {label} {_fmt(y)}", va='center', ha='left', transform=ax.get_yaxis_transform())

    # Core levels
    if sl:   hline(sl, "SL", 2.5)
    if entry:hline(entry, "ENTRY", 2.5)
    if tp1:  hline(tp1, f"TP1  (f1={f1:.0%})", 2.0)
    if tp2:  hline(tp2, f"TP2  (f2={f2:.0%})", 2.0)
    rest = max(0.0, 1.0 - f1 - f2)
    if tp3:  hline(tp3, f"TP3  (rest={rest:.0%})", 2.0)

    # R-levels as dashed lines with labels on the right
    for k, y in r_levels:
        hline(y, f"{k}R", 1.5, style='--')
        ax.text(0.98, y, f"{k}R", va='center', ha='right', transform=ax.get_yaxis_transform())

    ax.set_ylim(lo, hi)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_xlabel(f"Regime: {regime} | Fractions: {f1:.2f}/{f2:.2f}/{rest:.2f}")
    ax.grid(False)

    fname = fname or f"{sym}_{strategy}_{side}.png"
    out_path = os.path.join(out_dir, fname)
    plt.tight_layout()
    plt.savefig(out_path, bbox_inches='tight')
    plt.close(fig)
    return out_path
