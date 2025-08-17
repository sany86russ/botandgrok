import logging
from typing import Dict, List, Tuple
import asyncio
import ccxt.async_support as ccxt
from src.utils import float_safe
from src.indicators import compute_indicators

log = logging.getLogger("discovery")

async def discover_symbols(cfg: Dict, api: Any) -> Tuple[List[str], List[str], List[str], Dict[str, List[str]]]:
    try:
        await api.exchange.load_markets()
        symbols = []
        for sym in api.exchange.markets:
            if sym.endswith('USDT') and api.exchange.markets[sym].get('contract'):
                symbols.append(sym)
        log.info(f"[discover] total perp USDT: {len(symbols)}")

        tickers = await api.exchange.fetch_tickers(symbols)
        log.info(f"[discover] with 24h stats: {len(tickers)}")
        pool = []
        for sym in tickers:
            t = tickers[sym]
            quote_vol = float_safe(t.get("quoteVolume", 0.0))
            n_trades = float_safe(t.get("info", {}).get("count", 0))
            if quote_vol >= cfg.get("filters", {}).get("min_quote_volume_24h", 30000000) and \
               n_trades >= cfg.get("discovery", {}).get("hard_filters", {}).get("min_trades_24h", 5000):
                pool.append({"symbol": sym, "quoteVolume": quote_vol, "trades": n_trades})
        log.info(f"[discover] after volume filter: {len(pool)}")

        filtered = []
        strategy_symbols = {
            "scalping": [], "intraday": [], "swing": [], "position": [], "arbitrage": [], "hedging": []
        }
        for p in pool:
            sym = p["symbol"]
            depth = await api.exchange.fetch_order_book(sym, limit=5)
            if not depth or not depth.get("bids") or not depth.get("asks"):
                continue
            top_bid = float_safe(depth["bids"][0][0]) if depth["bids"] else 0.0
            top_ask = float_safe(depth["asks"][0][0]) if depth["asks"] else 0.0
            spread_bps = (top_ask - top_bid) / top_bid * 10000 if top_bid > 0 else float("inf")
            if spread_bps > cfg.get("filters", {}).get("max_spread_bps", 5):
                continue
            kl_15m = await api.fetch_klines(sym, "15m", 672)
            kl_1h = await api.fetch_klines(sym, "1h", 672)
            kl_4h = await api.fetch_klines(sym, "4h", 672)
            kl_1d = await api.fetch_klines(sym, "1d", 672)
            inds = compute_indicators([], [], kl_15m, kl_1h, kl_4h, kl_1d, [])
            atr_pct = inds.get("atr_pct_15m", 0.0)
            adx = inds.get("adx_15m", 0.0)
            vratio = inds.get("vratio_15m", 1.0)
            ema50 = inds.get("ema50_4h", inds.get("close_4h", [0])[-1])
            ema200 = inds.get("ema200_4h", inds.get("close_4h", [0])[-1])
            if cfg.get("filters", {}).get("atr_pct_sweet_min", 0.4) <= atr_pct <= cfg.get("filters", {}).get("atr_pct_sweet_max", 3.0):
                filtered.append(p)
            for strat, filters in cfg.get("discovery", {}).get("strategy_filters", {}).items():
                if strat == "scalping" and filters.get("atr_pct_min", 0.8) <= atr_pct <= filters.get("atr_pct_max", 3.0) and vratio >= filters.get("min_volume_mult", 1.5):
                    strategy_symbols[strat].append(sym)
                elif strat == "intraday" and filters.get("atr_pct_min", 0.5) <= atr_pct <= filters.get("atr_pct_max", 2.0) and adx >= filters.get("adx_min", 25):
                    strategy_symbols[strat].append(sym)
                elif strat == "swing" and filters.get("atr_pct_min", 0.4) <= atr_pct <= filters.get("atr_pct_max", 1.5) and ema50 > ema200:
                    strategy_symbols[strat].append(sym)
                elif strat == "position" and atr_pct <= filters.get("atr_pct_max", 1.0) and inds.get("close_1d", [0])[-1] > inds.get("ema200_1d", 0):
                    strategy_symbols[strat].append(sym)
                elif strat == "arbitrage" and vratio >= filters.get("min_volume_mult", 2.0):
                    strategy_symbols[strat].append(sym)
                elif strat == "hedging" and inds.get("corr_btc", 0.7) >= filters.get("beta_min", 0.8):
                    strategy_symbols[strat].append(sym)
        log.info(f"[discover] after depth filter: {len(filtered)}")

        filtered.sort(key=lambda x: float_safe(x["quoteVolume"]), reverse=True)
        tier_a_size = cfg.get("discovery", {}).get("top_n", 12)
        tier_a = [x["symbol"] for x in filtered[:tier_a_size]]
        tier_b = [x["symbol"] for x in filtered[tier_a_size:]]
        return filtered[:50], tier_a, tier_b, strategy_symbols
    except Exception:
        log.exception("Discovery failed")
        return [], [], [], {}