import json
import os
from typing import Dict, Any
from datetime import datetime, timedelta
from src.utils import float_safe

def load_state(cfg: Dict) -> Dict:
    path = os.path.join(cfg.get("paths", {}).get("state_dir", "state"), "risk_state.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"signals_today": 0, "last_signal_ts": {}, "blocked_symbols": {}}

def save_state(cfg: Dict, state: Dict):
    path = os.path.join(cfg.get("paths", {}).get("state_dir", "state"), "risk_state.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f)

def new_day(state: Dict):
    now = datetime.utcnow()
    if "last_day" not in state or (now - datetime.fromisoformat(state["last_day"])).days >= 1:
        state["signals_today"] = 0
        state["last_day"] = now.isoformat()

def can_signal(cfg: Dict, state: Dict) -> bool:
    max_signals = cfg.get("risk", {}).get("max_signals_per_day", 10)
    return state.get("signals_today", 0) < max_signals

def register_signal_sent(state: Dict):
    state["signals_today"] = state.get("signals_today", 0) + 1

def register_trade_result(cfg: Dict, state: Dict, R: float):
    pass  # Можно добавить логику для учёта результатов сделок

def outcome_cooldown(cfg: Dict, state: Dict, symbol: str, outcome: str):
    if outcome == "SL":
        state["blocked_symbols"][symbol] = datetime.utcnow().isoformat()

def is_symbol_blocked(state: Dict, symbol: str) -> bool:
    blocked_until = state.get("blocked_symbols", {}).get(symbol)
    if blocked_until:
        block_time = datetime.fromisoformat(blocked_until)
        if (datetime.utcnow() - block_time).total_seconds() < 1800:
            return True
        state["blocked_symbols"].pop(symbol, None)
    return False

def suggest_position_size(deposit: float, entry: float, atr_pct: float, risk_pct: float, leverage: float) -> Tuple[float, float]:
    risk_usdt = deposit * risk_pct
    risk_dist = atr_pct * entry / 100.0
    qty = risk_usdt / risk_dist * leverage
    return qty, risk_usdt