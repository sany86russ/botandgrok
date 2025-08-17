import logging
from typing import Dict, List, Any, Optional
from src.utils import float_safe
import numpy as np

log = logging.getLogger("signals")

def oi_divergence_signal(oi_hist: List[Dict], close_15m: List[float], lookback_min: int = 15) -> tuple[int, str]:
    try:
        if not oi_hist or not close_15m or len(close_15m) < 2:
            return 0, ""
        def _val(x): return float_safe(x.get("sumOpenInterest") or x.get("openInterest") or 0.0)
        oi_vals = [_val(x) for x in oi_hist[-3:]]
        if len(oi_vals) < 2 or oi_vals[-2] <= 0 or oi_vals[-1] <= 0:
            return 0, ""
        d_oi_pct = (oi_vals[-1] - oi_vals[-2]) / oi_vals[-2]
        d_px_pct = (float_safe(close_15m[-1]) - float_safe(close_15m[-2])) / max(1e-9, float_safe(close_15m[-2]))
        th_oi = 0.01
        th_px_flat = 0.002
        note_parts = []
        pts = 0
        if d_oi_pct >= th_oi and abs(d_px_pct) <= th_px_flat:
            pts += 6; note_parts.append("OI up + flat price (energy)")
        if d_px_pct > 0 and d_oi_pct <= -th_oi:
            pts -= 6; note_parts.append("Price up + OI down (distribution)")
        if d_px_pct < 0 and d_oi_pct >= th_oi:
            pts -= 4; note_parts.append("Price down + OI up (short pressure)")
        if pts == 0:
            return 0, ""
        return pts, " | ".join(note_parts)
    except Exception:
        log.exception("Failed to compute OI divergence signal")
        return 0, ""

def volume_breakout_ok(vratio: float, bbw_pctile: float, cfg: Dict) -> tuple[bool, str]:
    if vratio >= float(cfg.get("filters", {}).get("volume_breakout_mult", 1.7)) and bbw_pctile <= float(cfg.get("filters", {}).get("bbw_squeeze_pctile", 20)):
        return True, "volume breakout + squeeze"
    return False, ""

def liquidity_sweep_signal(close_15m: List[float], vol_15m: List[float], lookback: int = 5) -> tuple[int, str]:
    try:
        if len(close_15m) < lookback or len(vol_15m) < lookback:
            return 0, ""
        d_px = abs(close_15m[-1] - close_15m[-2]) / close_15m[-2]
        vol_avg = np.mean(vol_15m[-lookback:-1])
        if d_px > 0.01 and vol_15m[-1] < vol_avg * 0.5:
            return 4, "Liquidity sweep detected"
        return 0, ""
    except Exception:
        log.exception("Failed to compute liquidity sweep")
        return 0, ""

def _last(lst: List) -> float:
    return float_safe(lst[-1]) if lst else 0.0

def compute_pre_signal(inds: Dict[str, float], horizon_min: int, cfg: Dict) -> Dict[str, Any]:
    macd = float_safe(inds.get("macd_15m", 0.0))
    adx = float_safe(inds.get("adx_15m", 0.0))
    bbp = float_safe(inds.get("bbw_pctile_15m", 50.0))
    atrp = float_safe(inds.get("atr_pct_15m", 0.0))
    rsi = float_safe(inds.get("rsi_15m", 50.0))
    stoch = float_safe(inds.get("stoch_15m", 50.0))
    close = float_safe(_last(inds.get("close_15m")))
    ema200_1h = float_safe(inds.get("ema200_1h"))
    dir_ = "long" if macd > 0 else ("short" if macd < 0 else "flat")
    note = []
    score = 0
    if dir_ == "long":
        note.append("MACD>0")
        score += 1
        if rsi >= 60:
            note.append("RSI strong")
            score += 1
        if stoch >= 80:
            note.append("Stochastic high")
            score += 1
    elif dir_ == "short":
        note.append("MACD<0")
        score += 1
        if rsi <= 40:
            note.append("RSI weak")
            score += 1
        if stoch <= 20:
            note.append("Stochastic low")
            score += 1
    if adx >= 20:
        note.append("trend ADX≥20")
        score += 1
    if bbp <= 20:
        note.append("squeeze")
        score += 1
    if close == close and ema200_1h == ema200_1h:
        if (dir_ == "long" and close >= ema200_1h) or (dir_ == "short" and close <= ema200_1h):
            note.append("above/below 1h EMA200 in trend")
            score += 1
    mode = "watch" if score >= 2 else "idle"
    return {
        "dir": dir_,
        "mode": mode,
        "score": int(score),
        "note": ", ".join(note) if note else "no edge",
        "target": close,
        "eta_min": int(horizon_min),
        "atr_pct": atrp,
    }