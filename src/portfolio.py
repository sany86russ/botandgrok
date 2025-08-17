import logging
from datetime import datetime
from typing import Dict  # Добавлен импорт
from src.utils import float_safe
from src.api import fetch

log = logging.getLogger("portfolio")

_DAY_STATE = {"date": None, "risk_used": 0.0, "open_signals": 0}

def _day_state_now():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _DAY_STATE["date"] != today:
        _DAY_STATE["date"] = today
        _DAY_STATE["risk_used"] = 0.0
        _DAY_STATE["open_signals"] = 0
    return _DAY_STATE

def day_risk_allowed(cfg: dict, add_risk_pct: float) -> bool:
    st = _day_state_now()
    cap = float_safe((cfg.get("portfolio") or {}).get("day_max_risk_pct", 1.5))
    return (st["risk_used"] + float_safe(add_risk_pct)) <= cap

def day_risk_add(cfg: dict, add_risk_pct: float):
    st = _day_state_now()
    st["risk_used"] += float_safe(add_risk_pct)

def open_signal_allowed(cfg: dict) -> bool:
    st = _day_state_now()
    limit = int((cfg.get("portfolio") or {}).get("max_open_signals", 3))
    return st["open_signals"] < limit

def open_signal_inc():
    st = _day_state_now()
    st["open_signals"] += 1

def open_signal_dec():
    st = _day_state_now()
    st["open_signals"] = max(0, st["open_signals"] - 1)

def portfolio_corr_risk_ok(cfg: dict, symbol: str, side: str, beta_to_group: float) -> bool:
    c_cfg = cfg.get("risk", {}).get("corr_cap", {})
    if not c_cfg.get("enable", True):
        return True
    th = float_safe(c_cfg.get("beta_th", 0.8))
    if beta_to_group > th:
        log.debug(f"Blocked {symbol} {side} due to high correlation beta {beta_to_group:.2f} > {th:.2f}")
        return False
    return True

def dynamic_leverage(atr_pct: float, cfg: dict) -> int:
    auto = cfg.get("risk", {}).get("auto", {})
    if not auto.get("enable", True):
        return auto.get("leverage", 20)
    bands = auto.get("atr_pct_bands", [0.003, 0.006, 0.01])
    mults = auto.get("multipliers", [1.0, 0.75, 0.5, 0.33])
    for i, b in enumerate(bands):
        if atr_pct < b:
            return min(auto.get("max_leverage", 30), max(auto.get("min_leverage", 5), auto.get("leverage", 20) * mults[i]))
    return auto.get("min_leverage", 5)

def position_sizing(cfg: dict, entry: float, sl: float, deposit: float, atr_pct: float) -> tuple[float, float, float, float]:
    risk_pct = cfg.get("risk", {}).get("risk_per_trade_pct", 0.6) / 100
    risk_usdt = deposit * risk_pct
    leverage = dynamic_leverage(atr_pct, cfg)
    qty = risk_usdt / abs(entry - sl) * leverage
    notional = qty * entry
    im = notional / leverage
    return qty, notional, im, risk_usdt

def trailing_stop(atr_pct: float, cfg: dict, entry: float, current_price: float, side: str) -> float:
    mult = cfg.get("risk", {}).get("trailing_init_mult_atr", 2.5)
    stop = entry - (atr_pct * mult * entry / 100) if side == "long" else entry + (atr_pct * mult * entry / 100)
    return stop

async def check_margin_ratio(session, cfg: Dict) -> bool:
    try:
        data = await fetch(session, "https://fapi.binance.com/fapi/v2/balance", cfg=cfg)
        margin_ratio = float_safe(data.get("marginRatio", 100))
        return margin_ratio < 80
    except Exception:
        log.exception("Ошибка проверки маржинального соотношения")
        return True