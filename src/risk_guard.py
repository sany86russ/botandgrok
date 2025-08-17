from typing import Dict, List
import logging
from src.utils import float_safe
from src.correlation import compute_correlation

log = logging.getLogger("risk_guard")

async def risk_guard(cfg: Dict, api: Any, risk_state: Dict, signal: Dict, open_signals: Dict) -> bool:
    """
    Проверяет сигнал на дополнительные риски перед отправкой.
    Возвращает True, если сигнал проходит проверки, иначе False.
    """
    symbol = signal["symbol"]
    atr_pct = signal.get("atr_pct", 0.0)
    deposit = cfg.get("deposit_usdt", 1000)

    # 1. Проверка максимальной просадки
    max_drawdown_pct = cfg.get("risk", {}).get("max_drawdown_pct", 5.0)
    total_loss = sum(abs(t["risk_usdt"]) for t in open_signals.values() if t["last_price"] < t["sl"])
    if total_loss / deposit * 100 > max_drawdown_pct:
        log.warning(f"Signal for {symbol} blocked: max drawdown ({total_loss/deposit*100:.2f}%) exceeded")
        return False

    # 2. Проверка корреляции с открытыми позициями
    max_corr = cfg.get("risk", {}).get("max_correlation", 0.9)
    btc_klines = await api.fetch_klines("BTCUSDT", "15m", 20)
    symbol_klines = await api.fetch_klines(symbol, "15m", 20)
    corr = await compute_correlation(api, symbol, btc_klines, symbol_klines)
    for open_signal in open_signals.values():
        if open_signal["symbol"] != symbol:
            open_klines = await api.fetch_klines(open_signal["symbol"], "15m", 20)
            open_corr = await compute_correlation(api, open_signal["symbol"], btc_klines, open_klines)
            if abs(corr - open_corr) > max_corr:
                log.warning(f"Signal for {symbol} blocked: high correlation ({corr:.2f}) with {open_signal['symbol']}")
                return False

    # 3. Проверка волатильности
    max_atr_pct = cfg.get("filters", {}).get("atr_pct_sweet_max", 3.0)
    if atr_pct > max_atr_pct:
        log.warning(f"Signal for {symbol} blocked: high volatility (ATR%={atr_pct:.2f})")
        return False

    # 4. Проверка ликвидности
    depth = await api.exchange.fetch_order_book(symbol, limit=5)
    if not depth or not depth.get("bids") or not depth.get("asks"):
        log.warning(f"Signal for {symbol} blocked: insufficient order book depth")
        return False
    top_bid = float_safe(depth["bids"][0][0]) if depth["bids"] else 0.0
    top_ask = float_safe(depth["asks"][0][0]) if depth["asks"] else 0.0
    spread_bps = (top_ask - top_bid) / top_bid * 10000 if top_bid > 0 else float("inf")
    if spread_bps > cfg.get("filters", {}).get("max_spread_bps", 5):
        log.warning(f"Signal for {symbol} blocked: high spread ({spread_bps:.2f} bps)")
        return False

    return True
