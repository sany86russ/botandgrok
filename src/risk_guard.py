import json
import os
import time
from typing import Dict

_STATE = {"date": "", "R_day": 0.0, "loss_streak": 0, "cooldown_until": 0.0, "signals_sent": 0, "last_outcomes": {}}

def _state_path(cfg: Dict) -> str:
    d = cfg.get("paths", {}).get("state_dir", ".")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "risk_state.json")

def load_state(cfg: Dict) -> Dict:
    p = _state_path(cfg)
    if os.path.exists(p):
        try:
            return json.load(open(p, "r", encoding="utf-8"))
        except Exception:
            pass
    return dict(_STATE)

def save_state(cfg: Dict, st: Dict):
    json.dump(st, open(_state_path(cfg), "w", encoding="utf-8"))

def new_day(st: Dict):
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if st.get("date") != today:
        st.update({"date": today, "R_day": 0.0, "loss_streak": 0, "cooldown_until": 0.0, "signals_sent": 0})

def can_signal(cfg: Dict, st: Dict) -> bool:
    guard = cfg.get("risk", {}).get("guard", {})
    now = time.time()
    if st.get("cooldown_until", 0.0) > now:
        return False
    max_signals = guard.get("max_signals_per_day", 50)
    if st.get("signals_sent", 0) >= max_signals:
        return False
    return True

def register_signal_sent(st: Dict):
    st["signals_sent"] = int(st.get("signals_sent", 0)) + 1

def register_trade_result(cfg: Dict, st: Dict, R: float):
    guard = cfg.get("risk", {}).get("guard", {})
    st["R_day"] = float(st.get("R_day", 0.0) + R)
    if R < 0:
        st["loss_streak"] = int(st.get("loss_streak", 0) + 1)
    else:
        st["loss_streak"] = 0

    max_dd_R = guard.get("stop_day_R", -3.0)
    max_mdd_pct = guard.get("max_mdd_pct", 20.0)
    if st["R_day"] <= max_dd_R or st["R_day"] <= -max_mdd_pct / 100 * cfg.get("deposit_usdt", 1000):
        st["cooldown_until"] = time.time() + guard.get("cooldown_sec_after_stop", 8*3600)
    elif st["loss_streak"] >= guard.get("loss_streak_cooldown", 3):
        st["cooldown_until"] = time.time() + guard.get("cooldown_sec_after_streak", 1800)

def outcome_cooldown(cfg: Dict, st: Dict, symbol: str, outcome: str):
    g = cfg.get("risk", {}).get("guard", {})
    now = time.time()
    after_tp = g.get("cooldown_after_tp_sec", 0)
    after_sl = g.get("cooldown_after_sl_sec", 0)
    if outcome == "TP" and after_tp > 0:
        st["last_outcomes"][symbol] = now + after_tp
    elif outcome == "SL" and after_sl > 0:
        st["last_outcomes"][symbol] = now + after_sl

def is_symbol_blocked(st: Dict, symbol: str) -> bool:
    ts = st.get("last_outcomes", {}).get(symbol, 0.0)
    return time.time() < ts