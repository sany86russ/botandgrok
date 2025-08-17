import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import asyncio
import time
import logging
import csv
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
import httpx
import ccxt.async_support as ccxt
from src.config import load_config
from src.api import BingXAPI, BinanceAPI
from src.discovery import discover_symbols
from src.indicators import compute_indicators
from src.indicators_extras import compute_indicators_extras
from src.strategies import ScalpingStrategy, IntradayStrategy, SwingStrategy, PositionStrategy, ArbitrageStrategy, HedgingStrategy
from src.telegram import send_tg, send_signal, command_loop
from src.consensus import rank_and_filter
from src.risk_manager import suggest_position_size, load_state, save_state, new_day, can_signal, register_signal_sent, register_trade_result, outcome_cooldown, is_symbol_blocked
from src.rate_limiter import RateLimiter
from src.metrics import init_db, insert_signal, close_signal, analyze_recent_performance
from src.utils import float_safe
from src.portfolio_allocator import allocate_risk
from src.session import session_allowed
from src.weights import strategy_weight
from src.execution import get_executor
from src.market_regime import market_regime
import numpy as np

log = logging.getLogger("main_pro")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

def ensure_dirs():
    os.makedirs("logs", exist_ok=True)
    os.makedirs("state", exist_ok=True)

def log_signal_csv(payload: Dict[str, Any]):
    ensure_dirs()
    path = os.path.join("logs", "signals_log.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "symbol", "side", "score", "atr_pct", "adx", "vratio", "entry", "tp1", "sl", "qty_hint", "leverage", "R_target", "strategy_type"])
        w.writerow([
            datetime.utcnow().isoformat(), payload.get("symbol"), payload.get("side"),
            payload.get("score"), payload.get("atr_pct"), payload.get("adx"), payload.get("vratio"),
            payload.get("entry"), payload.get("tp1"), payload.get("sl"), payload.get("qty_hint"), payload.get("leverage"), payload.get("R_target"), payload.get("strategy_type")
        ])

async def monitor_open_signals(api: Any, cfg: Dict, open_map: Dict, executor: Any, risk_state: Dict):
    fast_poll = cfg.get("follow_fast_poll_sec", 3)
    while True:
        try:
            to_remove = []
            for signal_id, sig in list(open_map.items()):
                sym = sig["symbol"]
                side = sig["side"]
                entry = float_safe(sig["entry"])
                sl = float_safe(sig["sl"])
                tp1 = float_safe(sig["tp1"])
                tp2 = float_safe(sig["tp2"])
                tp3 = float_safe(sig["tp3"])
                ttl_at = sig["ttl_at"]
                px = await api.fetch_spot_price(sym)
                if not px:
                    continue
                sig["last_price"] = px
                if side == "long":
                    if px >= tp1 and not sig.get("tp1_hit"):
                        sig["tp1_hit"] = True
                        await send_tg(cfg, f"[{sym}] {sig['strategy_type']} TP1 hit @ {px:.6f} (f={sig['frac1']:.2f})")
                        if cfg.get("risk", {}).get("partial_tp", {}).get("be_after_tp1", True):
                            sl_new = entry
                            sig["sl"] = sl_new
                            await send_tg(cfg, f"[{sym}] {sig['strategy_type']} SL moved to BE @ {sl_new:.6f}")
                    elif px >= tp2 and sig.get("tp1_hit") and not sig.get("tp2_hit"):
                        sig["tp2_hit"] = True
                        await send_tg(cfg, f"[{sym}] {sig['strategy_type']} TP2 hit @ {px:.6f} (f={sig['frac2']:.2f})")
                    elif px >= tp3 and sig.get("tp2_hit"):
                        close_signal(cfg, signal_id, px, datetime.utcnow().isoformat(), "TP")
                        outcome_cooldown(cfg, risk_state, sym, "TP")
                        register_trade_result(cfg, risk_state, sig["R_target"] * (1 - sig["frac1"] - sig["frac2"]))
                        to_remove.append(signal_id)
                        await send_tg(cfg, f"[{sym}] {sig['strategy_type']} TP3 hit @ {px:.6f}, closed")
                    elif px <= sl:
                        close_signal(cfg, signal_id, px, datetime.utcnow().isoformat(), "SL")
                        outcome_cooldown(cfg, risk_state, sym, "SL")
                        register_trade_result(cfg, risk_state, -1.0)
                        to_remove.append(signal_id)
                        await send_tg(cfg, f"[{sym}] {sig['strategy_type']} SL hit @ {px:.6f}, closed")
                else:  # short
                    if px <= tp1 and not sig.get("tp1_hit"):
                        sig["tp1_hit"] = True
                        await send_tg(cfg, f"[{sym}] {sig['strategy_type']} TP1 hit @ {px:.6f} (f={sig['frac1']:.2f})")
                        if cfg.get("risk", {}).get("partial_tp", {}).get("be_after_tp1", True):
                            sl_new = entry
                            sig["sl"] = sl_new
                            await send_tg(cfg, f"[{sym}] {sig['strategy_type']} SL moved to BE @ {sl_new:.6f}")
                    elif px <= tp2 and sig.get("tp1_hit") and not sig.get("tp2_hit"):
                        sig["tp2_hit"] = True
                        await send_tg(cfg, f"[{sym}] {sig['strategy_type']} TP2 hit @ {px:.6f} (f={sig['frac2']:.2f})")
                    elif px <= tp3 and sig.get("tp2_hit"):
                        close_signal(cfg, signal_id, px, datetime.utcnow().isoformat(), "TP")
                        outcome_cooldown(cfg, risk_state, sym, "TP")
                        register_trade_result(cfg, risk_state, sig["R_target"] * (1 - sig["frac1"] - sig["frac2"]))
                        to_remove.append(signal_id)
                        await send_tg(cfg, f"[{sym}] {sig['strategy_type']} TP3 hit @ {px:.6f}, closed")
                    elif px >= sl:
                        close_signal(cfg, signal_id, px, datetime.utcnow().isoformat(), "SL")
                        outcome_cooldown(cfg, risk_state, sym, "SL")
                        register_trade_result(cfg, risk_state, -1.0)
                        to_remove.append(signal_id)
                        await send_tg(cfg, f"[{sym}] {sig['strategy_type']} SL hit @ {px:.6f}, closed")
                if time.time() > ttl_at:
                    close_signal(cfg, signal_id, px, datetime.utcnow().isoformat(), "TTL")
                    to_remove.append(signal_id)
                    await send_tg(cfg, f"[{sym}] {sig['strategy_type']} TTL expired @ {px:.6f}, closed")
            for signal_id in to_remove:
                open_map.pop(signal_id, None)
            save_state(cfg, risk_state)
            await asyncio.sleep(fast_poll)
        except Exception:
            log.exception("Monitor loop error")
            await asyncio.sleep(fast_poll)

async def main():
    cfg = load_config()
    init_db(cfg)
    ensure_dirs()
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    api = BingXAPI(cfg) if cfg.get("api", {}).get("provider", "bingx") == "bingx" else BinanceAPI(cfg)
    STRATEGIES = [
        ScalpingStrategy(cfg, api),
        IntradayStrategy(cfg, api),
        SwingStrategy(cfg, api),
        PositionStrategy(cfg, api),
        ArbitrageStrategy(cfg, api),
        HedgingStrategy(cfg, api)
    ]
    executor = get_executor(cfg)
    risk_state = load_state(cfg)
    open_map = {}
    recent_same = {}
    recent_opp = {}
    tick_latencies = []
    error_ts = []
    rate_limiter = RateLimiter()
    scan_interval = cfg.get("scan_interval_sec", 15)
    last_analysis = 0
    analysis_interval = 3600

    price_data = {}
    def price_callback(message):
        symbol = message.get("symbol")
        price = float_safe(message.get("lastPrice"))
        if symbol and price:
            price_data[symbol] = price

    async with httpx.AsyncClient() as session:
        watchlist, tier_a, tier_b, strategy_symbols = await discover_symbols(cfg, api)
        for sym in watchlist:
            api.subscribe_book_ticker(sym, price_callback)
        
        asyncio.create_task(monitor_open_signals(api, cfg, open_map, executor, risk_state))
        asyncio.create_task(command_loop(cfg))
        while True:
            try:
                start_time = time.time()
                new_day(risk_state)
                if not can_signal(cfg, risk_state):
                    await asyncio.sleep(scan_interval)
                    continue
                now = datetime.utcnow()
                if not session_allowed(cfg, now):
                    await asyncio.sleep(scan_interval)
                    continue
                watchlist, tier_a, tier_b, strategy_symbols = await discover_symbols(cfg, api)
                candidates = []
                for strat in STRATEGIES:
                    strat_name = strat.__class__.__name__.replace("Strategy", "").upper()
                    symbols = strategy_symbols.get(strat_name.lower(), watchlist)
                    for sym in symbols:
                        if is_symbol_blocked(risk_state, sym):
                            continue
                        same_key = f"{sym}:long"
                        opp_key = f"{sym}:short"
                        if time.time() < recent_same.get(same_key, 0):
                            continue
                        if time.time() < recent_opp.get(opp_key, 0):
                            continue
                        await rate_limiter.acquire()
                        klines = await asyncio.gather(
                            api.fetch_klines(sym, "1m", 672),
                            api.fetch_klines(sym, "5m", 672),
                            api.fetch_klines(sym, "15m", 672),
                            api.fetch_klines(sym, "1h", 672),
                            api.fetch_klines(sym, "4h", 672),
                            api.fetch_klines(sym, "1d", 672),
                            api.fetch_klines(sym, "1w", 672)
                        )
                        oi_hist = await api.fetch_oi_hist(sym, "15m", 96)
                        inds = compute_indicators(*klines)
                        inds.update(compute_indicators_extras(klines[2]))  # 15m
                        regime = market_regime(inds)
                        w = strategy_weight(cfg, strat_name)
                        s = await strat.generate_signal(session, sym, *klines, oi_hist)
                        if s and s.get("score", 0) >= cfg.get("strategies", {}).get(strat_name.lower(), {}).get("min_score", 2.0):
                            s["score"] = s["score"] * w
                            s["regime"] = regime
                            s["entry"] = float_safe(price_data.get(sym, await api.fetch_spot_price(sym)))
                            candidates.append(s)
                candidates = rank_and_filter(candidates, cfg.get("consensus", {}).get("max_per_symbol", 1), cfg.get("consensus", {}).get("min_score", 2.0))
                risk_alloc = allocate_risk(cfg.get("deposit_usdt", 1000), cfg.get("allocator", {}), candidates)
                for s, risk_pct in risk_alloc:
                    sym = s["symbol"]
                    side = s["side"]
                    atr_pct = float_safe(s.get("atr_pct", 0.0))
                    adx = float_safe(s.get("adx", 0.0))
                    entry = s["entry"]
                    strategy_type = s["strategy_type"]
                    leverage = min(cfg.get("risk", {}).get("max_leverage", 45),
                                 max(cfg.get("risk", {}).get("min_leverage", 20),
                                     int(20 + (atr_pct * 1000) * (adx / 50))))
                    qty_hint, risk_usdt = suggest_position_size(
                        cfg.get("deposit_usdt", 1000),
                        entry,
                        atr_pct,
                        risk_pct,
                        leverage
                    )
                    if qty_hint * entry < cfg.get("risk", {}).get("min_notional_usdt", 5.0):
                        log.warning(f"Skipping signal for {sym}: position size {qty_hint * entry:.2f} USDT below minimum")
                        continue
                    risk_dist = atr_pct * entry / 100.0 * cfg.get("strategies", {}).get(strategy_type.lower(), {}).get("atr_mult_sl", 1.0)
                    sl_init = entry - risk_dist if side == "long" else entry + risk_dist
                    rr = cfg.get("risk", {}).get("rr_target", 2.0)
                    tp1 = entry + rr * risk_dist if side == "long" else entry - rr * risk_dist
                    tp2 = entry + 2 * rr * risk_dist if side == "long" else entry - 2 * rr * risk_dist
                    tp3 = entry + 3 * rr * risk_dist if side == "long" else entry - 3 * rr * risk_dist
                    if strategy_type == "ARBITRAGE":
                        tp1 = entry + (0.0006 * entry) if side == "long" else entry - (0.0006 * entry)
                        tp2 = tp1
                        tp3 = tp1
                    payload = dict(
                        s,
                        entry=entry,
                        tp1=tp1,
                        tp2=tp2,
                        tp3=tp3,
                        sl=sl_init,
                        qty_hint=qty_hint,
                        risk_usdt=risk_usdt,
                        leverage=leverage,
                        R_target=rr
                    )
                    log_signal_csv(payload)
                    await send_signal(cfg, payload)
                    signal_id = insert_signal(cfg, dict(payload, symbol=sym))
                    ttl_at = time.time() + cfg.get("follow_lookahead_min", 60) * 60
                    open_map[signal_id] = {
                        "symbol": sym,
                        "side": side,
                        "entry": entry,
                        "atr_pct": atr_pct,
                        "tp1": tp1,
                        "tp2": tp2,
                        "tp3": tp3,
                        "sl": sl_init,
                        "ttl_at": ttl_at,
                        "strategy_type": strategy_type,
                        "tp1_hit": False,
                        "tp2_hit": False,
                        "risk_dist": abs(entry - sl_init),
                        "frac1": float(cfg.get("risk", {}).get("partial_tp", {}).get("fraction1", 0.5)),
                        "frac2": float(cfg.get("risk", {}).get("partial_tp", {}).get("fraction2", 0.3))
                    }
                    recent_same[f"{sym}:{side}"] = time.time() + cfg.get("consensus", {}).get("cooldown_same_sec", 600)
                    recent_opp[f"{sym}:{'short' if side == 'long' else 'long'}"] = time.time() + cfg.get("consensus", {}).get("cooldown_opp_sec", 1800)
                    register_signal_sent(risk_state)
                    save_state(cfg, risk_state)
                if time.time() - last_analysis > analysis_interval:
                    performance = analyze_recent_performance(cfg, days=7)
                    for strat, metrics in performance.items():
                        msg = (
                            f"📈 Анализ стратегии {strat} (7 дней):\n"
                            f"Сигналов: {metrics['n']}\n"
                            f"Win Rate: {metrics['win_rate']:.2%}\n"
                            f"Средний R: {metrics['avg_R']:.2f}\n"
                            f"Макс. R: {metrics['max_R']:.2f}\n"
                            f"Мин. R: {metrics['min_R']:.2f}"
                        )
                        await send_tg(cfg, msg)
                    last_analysis = time.time()
                elapsed = time.time() - start_time
                tick_latencies.append(elapsed)
                if len(tick_latencies) > 100:
                    tick_latencies.pop(0)
                log.debug(f"Scan took {elapsed:.2f}s, p95 latency: {np.percentile(tick_latencies, 95):.2f}s")
                await asyncio.sleep(scan_interval)
            except Exception:
                log.exception("Main loop error")
                error_ts.append(time.time())
                error_ts = [t for t in error_ts if time.time() - t < 300]
                if len(error_ts) >= 5:
                    await asyncio.sleep(max(60, scan_interval))
                else:
                    await asyncio.sleep(scan_interval)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bye")
    except Exception:
        log.exception("Fatal error")