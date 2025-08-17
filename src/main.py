import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
import logging
import time
import csv
import json
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any
import httpx
from src.config import load_config
from src.api import fetch_klines, fetch_oi_hist, fetch
from src.indicators import compute_indicators
from src.signals import compute_pre_signal, volume_breakout_ok, oi_divergence_signal
from src.portfolio import day_risk_allowed, day_risk_add, open_signal_allowed, open_signal_inc, portfolio_corr_risk_ok, position_sizing, dynamic_leverage, trailing_stop, check_margin_ratio
from src.telegram import send_tg
from src.discovery import discover_symbols
from src.strategies import ScalpingStrategy, IntradayStrategy, SwingStrategy, PositionStrategy, ArbitrageStrategy, HedgingStrategy, AlgorithmicStrategy, NewsStrategy
from src.utils import float_safe, utcnow

log = logging.getLogger("main")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
os.makedirs("logs", exist_ok=True)
file_handler = logging.FileHandler(os.path.join("logs", f"bot_{datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}.log"))
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
log.addHandler(file_handler)

FUNDING_HOURS_UTC = (0, 8, 16)

def is_funding_blackout(now_utc: datetime, minutes: int) -> bool:
    if minutes <= 0:
        return False
    candidates = []
    for h in FUNDING_HOURS_UTC:
        t = now_utc.replace(hour=h, minute=0, second=0, microsecond=0)
        candidates.extend([t, t + timedelta(days=1), t - timedelta(days=1)])
    nearest = min(candidates, key=lambda t: abs((t - now_utc).total_seconds()))
    return abs((nearest - now_utc).total_seconds()) <= minutes * 60

def log_top_candidates(log, tradables: List[Dict], top_k: int = 3):
    try:
        if not tradables:
            log.info("no candidates to log (empty list)")
            return
        top_view = sorted(tradables, key=lambda r: r.get("_final_score", r.get("score", 0.0)), reverse=True)[:max(1, int(top_k))]
        if not top_view:
            log.info("no candidates to log (sorted empty)")
            return
        log.info("TOP-%d candidates this pass:", len(top_view))
        for i, rr in enumerate(top_view, 1):
            pre = rr.get("pre_signal") or {}
            try:
                tp = pre.get("target_price", None)
                eta = pre.get("eta_min", None)
                side_ps = pre.get("side", None)
                conf_ps = pre.get("confidence", 0.0)
                if tp is not None and eta is not None and side_ps:
                    pre_txt = f" | pre_signal: {side_ps}/{int(eta)}m @ {float_safe(tp):.6f} (conf {float_safe(conf_ps):.2f})"
                else:
                    pre_txt = ""
            except Exception:
                pre_txt = ""
            try:
                bbw = rr.get("bbw_pctile", None)
                bbw_txt = f" | bbw_pctile: {float_safe(bbw):.1f}" if bbw is not None else ""
            except Exception:
                bbw_txt = ""
            reasons_txt = str(rr.get("reasons") or "").replace(";", ", ")
            try:
                score_v = rr.get("_final_score", rr.get("score", 0.0))
                score_v = float_safe(score_v) if score_v is not None else 0.0
            except Exception:
                score_v = 0.0
            log.info("  %d) %s %s  score=%+.0f%s%s | reasons: %s",
                     i, rr.get("symbol"), rr.get("side"), score_v, bbw_txt, pre_txt, reasons_txt)
    except Exception:
        log.exception("TOP-K logging failed")

def log_signal_csv(payload: Dict):
    try:
        fname = os.path.join("logs", "signals.csv")
        is_new = not os.path.exists(fname)
        with open(fname, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["ts", "symbol", "side", "entry", "sl", "tp", "qty", "atr", "adx", "reasons", "strategy_type"])
            if is_new:
                writer.writeheader()
            writer.writerow(payload)
    except Exception:
        log.exception("Failed to log signal to CSV")

async def main():
    cfg = load_config()
    tick_latencies = []
    last_signal = {}
    strategies = {
        "scalping": ScalpingStrategy(cfg),
        "intraday": IntradayStrategy(cfg),
        "swing": SwingStrategy(cfg),
        "position": PositionStrategy(cfg),
        "arbitrage": ArbitrageStrategy(cfg),
        "hedging": HedgingStrategy(cfg),
        "algorithmic": AlgorithmicStrategy(cfg),
        "news": NewsStrategy(cfg)
    }

    # Start WebSocket for scalping
    if cfg.get("strategies", {}).get("scalping", {}).get("enabled", False):
        asyncio.create_task(strategies["scalping"].start_websocket())

    async with httpx.AsyncClient() as session:
        while True:
            try:
                start_time = time.time()
                now_utc = utcnow()
                fast_poll_sec = cfg.get("follow_fast_poll_sec", 3)
                scan_interval = cfg.get("scan_interval_sec", 15)

                # Check margin ratio for cross margin
                if not await check_margin_ratio(session, cfg):
                    log.warning("Margin ratio too high, skipping scan")
                    await asyncio.sleep(scan_interval)
                    continue

                symbols, explain = await discover_symbols(session, cfg)
                tradables = []
                for s in symbols:
                    try:
                        kl_15m = await fetch_klines(session, s, "15m", cfg.get("discovery", {}).get("performance", {}).get("kline_limit", 60), cfg)
                        kl_1h = await fetch_klines(session, s, "1h", 200, cfg)
                        oi_hist = await fetch_oi_hist(session, s, "15m", cfg.get("discovery", {}).get("performance", {}).get("oi_limit", 64), cfg)
                        inds = compute_indicators(kl_15m, kl_1h)
                        if not inds:
                            continue

                        for strat_name, strat in strategies.items():
                            if cfg.get("strategies", {}).get(strat_name, {}).get("enabled", False):
                                signal = await strat.generate_signal(session, s, kl_15m, kl_1h, oi_hist)
                                if signal:
                                    pre = compute_pre_signal(inds, cfg, horizon_min=cfg.get("strategies", {}).get(strat_name, {}).get("horizon_min", 5))
                                    signal["pre_signal"] = pre
                                    signal["atr_pct"] = inds.get("atr_pct_15m", 0.0)
                                    signal["adx"] = inds.get("adx_15m", 0.0)
                                    signal["bbw_pctile"] = inds.get("bb_width_pctile_15m", 50.0)
                                    tradables.append(signal)
                    except Exception as e:
                        log.error(f"Ошибка обработки символа {s}: {str(e)}")
                        continue

                log_top_candidates(log, tradables, cfg.get("portfolio", {}).get("top_k_per_pass", 3))
                any_signal = False
                for r in sorted(tradables, key=lambda x: x.get("score", 0), reverse=True):
                    s = r["symbol"]
                    side = r["side"]
                    pre = r.get("pre_signal", {})
                    if is_funding_blackout(now_utc, cfg.get("filters", {}).get("funding_blackout_min", 30)):
                        continue
                    if not day_risk_allowed(cfg, cfg.get("risk", {}).get("risk_per_trade_pct", 0.6)):
                        continue
                    if not open_signal_allowed(cfg):
                        continue
                    if not portfolio_corr_risk_ok(cfg, s, side, r.get("corr_btc", 0.0)):
                        continue
                    entry = float_safe(pre.get("target", 0.0))
                    atr = float_safe(r.get("atr_pct", 0.0)) * entry / 100
                    sl = entry - atr * cfg.get("risk", {}).get("atr_mult", 1.4) if side == "long" else entry + atr * cfg.get("risk", {}).get("atr_mult", 1.4)
                    tp = entry + atr * cfg.get("risk", {}).get("rr_target", 2.0) if side == "long" else entry - atr * cfg.get("risk", {}).get("rr_target", 2.0)
                    qty, notional, im, risk_usdt = position_sizing(cfg, entry, sl, cfg.get("deposit_usdt", 66), r.get("atr_pct", 0.0))
                    key = f"{s}:{side}"
                    if not last_signal.get(key) or (utcnow() - last_signal[key]["ts"]).total_seconds() > cfg.get("anti_spam", {}).get("per_key_cooldown_sec", 90):
                        lines = [
                            f"[{r['strategy_type'].upper()}] {s} → {side.upper()} | Entry: {entry:.6f} | SL: {sl:.6f} | TP: {tp:.6f}",
                            f"ADX: {r['adx']:.1f} | ATR%: {r['atr_pct']:.2f}% | qVol24h: {r.get('qv24h', 0)/1e6:.1f}m",
                            f"Контекст: {', '.join(r['reasons'])}",
                        ]
                        payload = {
                            "ts": utcnow().isoformat(),
                            "symbol": s,
                            "side": side,
                            "entry": entry,
                            "sl": sl,
                            "tp": tp,
                            "qty": qty,
                            "atr": r["atr_pct"],
                            "adx": r["adx"],
                            "reasons": ", ".join(r["reasons"]),
                            "strategy_type": r["strategy_type"]
                        }
                        log_signal_csv(payload)
                        await send_tg(cfg, "\n".join(lines), payload=payload)
                        last_signal[key] = {"ts": utcnow(), "entry": entry}
                        any_signal = True
                        open_signal_inc()
                        asyncio.create_task(monitor_entry_window(session, s, side, entry, sl, tp, cfg.get("alerts", {}).get("entry_window_ping", {}).get("window_sec", 120), cfg.get("alerts", {}).get("entry_hint", {}).get("ttl_sec", 120), cfg))
                if not any_signal:
                    log.info("Сигналов для торговли на этом проходе нет")
            except Exception as e:
                log.exception(f"Ошибка итерации сканирования: {str(e)}")
            finally:
                elapsed = time.time() - start_time
                tick_latencies.append(elapsed)
                if len(tick_latencies) > 100:
                    tick_latencies.pop(0)
                log.debug(f"Сканирование заняло {elapsed:.2f}с, p95 задержка: {np.percentile(tick_latencies, 95):.2f}с")
                await asyncio.sleep(scan_interval)

async def monitor_entry_window(session, symbol: str, side: str, entry: float, sl: float, tp: float, window_sec: int, ttl_sec: int, cfg: Dict):
    try:
        start_time = time.time()
        while time.time() - start_time < window_sec:
            price_data = await fetch(session, f"https://fapi.binance.com/fapi/v1/ticker/price", {"symbol": symbol}, cfg=cfg)
            current_price = float_safe(price_data.get("price", 0.0))
            if not current_price:
                await asyncio.sleep(1)
                continue
            if (side == "long" and current_price >= entry) or (side == "short" and current_price <= entry):
                await send_tg(cfg, f"[{side.upper()}] {symbol} Вход сработал @ {current_price:.6f}", payload={"symbol": symbol, "side": side, "entry": current_price})
                break
            if (side == "long" and current_price <= sl) or (side == "short" and current_price >= sl):
                await send_tg(cfg, f"[{side.upper()}] {symbol} Стоп-лосс сработал @ {current_price:.6f}", payload={"symbol": symbol, "side": side, "sl": current_price})
                break
            if time.time() - start_time > ttl_sec:
                break
            await asyncio.sleep(1)
    except Exception:
        log.exception(f"Ошибка мониторинга окна входа для {symbol}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Пока!")
    except Exception:
        log.exception("Ошибка главного цикла")