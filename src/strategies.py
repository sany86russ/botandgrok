from typing import Dict, List, Any
from src.indicators import compute_indicators
from src.signals import compute_pre_signal, volume_breakout_ok
from src.utils import float_safe
import logging
import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator
from ta.trend import IchimokuIndicator

log = logging.getLogger("strategies")

class ScalpingStrategy:
    def __init__(self, cfg: Dict, api):
        self.cfg = cfg.get("strategies", {}).get("scalping", {})
        self.api = api
        self.l2_data = {}

    async def generate_signal(self, session, symbol: str, kl_1m: List, kl_5m: List, kl_15m: List, kl_1h: List, kl_4h: List, kl_1d: List, kl_1w: List, oi_hist: List) -> Dict:
        inds = compute_indicators(kl_1m, kl_5m, kl_15m, kl_1h, kl_4h, kl_1d, kl_1w)
        if not inds:
            return {}
        rsi = inds.get("rsi_5m", 50.0)
        stoch = inds.get("stoch_5m", 50.0)
        vwap = inds.get("vwap_5m", inds["close_5m"][-1])
        atr_pct = inds.get("atr_pct_5m", 0.0)
        ema5 = inds.get("ema5_5m", inds["close_5m"][-1])
        ema20 = inds.get("ema20_5m", inds["close_5m"][-1])
        macd = inds.get("macd_5m", 0.0)
        adx_15m = inds.get("adx_15m", 0.0)
        obv = inds.get("obv_5m", 0)
        score = 0
        reasons = []
        rsi_threshold = max(self.cfg.get("rsi_th", 20), 50 - atr_pct * 100)
        if rsi < rsi_threshold:
            score += 2
            reasons.append("RSI oversold")
        if stoch < self.cfg.get("stoch_th", 20):
            score += 2
            reasons.append("Stochastic low")
        if inds["close_5m"][-1] < vwap:
            score += 1
            reasons.append("Below VWAP")
        if ema5 > ema20:
            score += 1
            reasons.append("EMA5 > EMA20")
        if macd > 0:
            score += 1
            reasons.append("MACD bullish")
        if adx_15m > 20:
            score += 1
            reasons.append("ADX 15m confirms trend")
        if obv > 0:
            score += 1
            reasons.append("OBV bullish")
        if volume_breakout_ok(inds.get("vratio_5m", 1.0), inds.get("bbw_pctile_5m", 50.0), self.cfg)[0]:
            score += 2
            reasons.append("Volume breakout")
        if score >= self.cfg.get("min_score", 5):
            return {
                "strategy_type": "SCALPING",
                "symbol": symbol,
                "side": "long",
                "score": score,
                "reasons": reasons,
                "atr_pct": atr_pct,
                "adx": inds.get("adx_5m", 0.0),
                "corr_btc": inds.get("corr_btc", 0.7),
                "obv": obv
            }
        return {}

class IntradayStrategy:
    def __init__(self, cfg: Dict, api):
        self.cfg = cfg.get("strategies", {}).get("intraday", {})
        self.api = api

    async def generate_signal(self, session, symbol: str, kl_1m: List, kl_5m: List, kl_15m: List, kl_1h: List, kl_4h: List, kl_1d: List, kl_1w: List, oi_hist: List) -> Dict:
        inds = compute_indicators(kl_1m, kl_5m, kl_15m, kl_1h, kl_4h, kl_1d, kl_1w)
        if not inds:
            return {}
        adx = inds.get("adx_15m", 0.0)
        bbw = inds.get("bbw_15m", 0.0)
        atr_pct = inds.get("atr_pct_15m", 0.0)
        macd = inds.get("macd_15m", 0.0)
        rsi = inds.get("rsi_15m", 50.0)
        obv = inds.get("obv_15m", 0)
        score = 0
        reasons = []
        if adx > self.cfg.get("adx_min", 25):
            score += 2
            reasons.append("ADX trend")
        if bbw > self.cfg.get("bbw_pctile_min", 30):
            score += 1
            reasons.append("BBW expansion")
        if atr_pct > 0.5:
            score += 1
            reasons.append("ATR spike")
        if macd > 0:
            score += 1
            reasons.append("MACD bullish")
        if rsi > 50:
            score += 1
            reasons.append("RSI bullish")
        if obv > 0:
            score += 1
            reasons.append("OBV bullish")
        if volume_breakout_ok(inds.get("vratio_15m", 1.0), inds.get("bbw_pctile_15m", 50.0), self.cfg)[0]:
            score += 2
            reasons.append("Volume breakout")
        if score >= self.cfg.get("min_score", 3.5):
            return {
                "strategy_type": "INTRADAY",
                "symbol": symbol,
                "side": "long",
                "score": score,
                "reasons": reasons,
                "atr_pct": atr_pct,
                "adx": adx,
                "corr_btc": inds.get("corr_btc", 0.7),
                "obv": obv
            }
        return {}

class SwingStrategy:
    def __init__(self, cfg: Dict, api):
        self.cfg = cfg.get("strategies", {}).get("swing", {})
        self.api = api

    async def generate_signal(self, session, symbol: str, kl_1m: List, kl_5m: List, kl_15m: List, kl_1h: List, kl_4h: List, kl_1d: List, kl_1w: List, oi_hist: List) -> Dict:
        inds = compute_indicators(kl_1m, kl_5m, kl_15m, kl_1h, kl_4h, kl_1d, kl_1w)
        if not inds:
            return {}
        ema50 = float_safe(inds.get("ema50_4h", inds["close_4h"][-1]))
        ema200 = float_safe(inds.get("ema200_4h", inds["close_4h"][-1]))
        rsi = inds.get("rsi_4h", 50.0)
        macd = inds.get("macd_4h", 0.0)
        fib_618 = inds.get("fib_618_4h", inds["close_4h"][-1])
        obv = inds.get("obv_4h", 0)
        ichimoku = inds.get("ichimoku_4h", 0)
        score = 0
        reasons = []
        if ema50 > ema200:
            score += 2
            reasons.append("EMA50 > EMA200")
        if rsi > self.cfg.get("rsi_min", 50):
            score += 1
            reasons.append("RSI bullish")
        if macd > 0:
            score += 1
            reasons.append("MACD bullish")
        if abs(inds["close_4h"][-1] - fib_618) / fib_618 < 0.01:
            score += 1
            reasons.append("Near Fibonacci 61.8%")
        if obv > 0:
            score += 1
            reasons.append("OBV bullish")
        if ichimoku > inds["close_4h"][-1]:
            score += 1
            reasons.append("Above Ichimoku Cloud")
        if score >= self.cfg.get("min_score", 2.5):
            return {
                "strategy_type": "SWING",
                "symbol": symbol,
                "side": "long",
                "score": score,
                "reasons": reasons,
                "atr_pct": inds.get("atr_pct_4h", 0.0),
                "adx": inds.get("adx_4h", 0.0),
                "corr_btc": inds.get("corr_btc", 0.7),
                "obv": obv,
                "ichimoku": "Above" if ichimoku > inds["close_4h"][-1] else "Below"
            }
        return {}

class PositionStrategy:
    def __init__(self, cfg: Dict, api):
        self.cfg = cfg.get("strategies", {}).get("position", {})
        self.api = api

    async def generate_signal(self, session, symbol: str, kl_1m: List, kl_5m: List, kl_15m: List, kl_1h: List, kl_4h: List, kl_1d: List, kl_1w: List, oi_hist: List) -> Dict:
        inds = compute_indicators(kl_1m, kl_5m, kl_15m, kl_1h, kl_4h, kl_1d, kl_1w)
        if not inds:
            return {}
        close = inds["close_1d"][-1]
        ema200 = float_safe(inds.get("ema200_1d", close))
        rsi = inds.get("rsi_1d", 50.0)
        obv = inds.get("obv_1d", 0)
        ichimoku = inds.get("ichimoku_1d", 0)
        score = 0
        reasons = []
        if close > ema200:
            score += 2
            reasons.append("Above EMA200")
        if rsi > 50:
            score += 1
            reasons.append("RSI bullish")
        if obv > 0:
            score += 1
            reasons.append("OBV bullish")
        if ichimoku > close:
            score += 1
            reasons.append("Above Ichimoku Cloud")
        if score >= self.cfg.get("min_score", 2):
            return {
                "strategy_type": "POSITION",
                "symbol": symbol,
                "side": "long",
                "score": score,
                "reasons": reasons,
                "atr_pct": inds.get("atr_pct_1d", 0.0),
                "adx": inds.get("adx_1d", 0.0),
                "corr_btc": inds.get("corr_btc", 0.7),
                "obv": obv,
                "ichimoku": "Above" if ichimoku > close else "Below"
            }
        return {}

class ArbitrageStrategy:
    def __init__(self, cfg: Dict, api):
        self.cfg = cfg.get("strategies", {}).get("arbitrage", {})
        self.api = api

    async def generate_signal(self, session, symbol: str, kl_1m: List, kl_5m: List, kl_15m: List, kl_1h: List, kl_4h: List, kl_1d: List, kl_1w: List, oi_hist: List) -> Dict:
        inds = compute_indicators(kl_1m, kl_5m, kl_15m, kl_1h, kl_4h, kl_1d, kl_1w)
        if not inds:
            return {}
        spot_price = await self.api.fetch_spot_price(symbol)
        futures_price = inds["close_5m"][-1]
        basis = abs(futures_price - spot_price) / spot_price if spot_price > 0 else 0
        z_score = float_safe(inds.get("zscore_basis", 0.0))
        score = 0
        reasons = []
        if basis > self.cfg.get("basis_th", 0.0006):
            score += 2
            reasons.append("Basis divergence")
        if z_score > self.cfg.get("z_score_min", 1.5):
            score += 2
            reasons.append("Z-score high")
        if score >= self.cfg.get("min_score", 4):
            side = "long" if futures_price < spot_price else "short"
            return {
                "strategy_type": "ARBITRAGE",
                "symbol": symbol,
                "side": side,
                "score": score,
                "reasons": reasons,
                "atr_pct": inds.get("atr_pct_5m", 0.0),
                "adx": inds.get("adx_5m", 0.0),
                "corr_btc": inds.get("corr_btc", 0.7)
            }
        return {}

class HedgingStrategy:
    def __init__(self, cfg: Dict, api):
        self.cfg = cfg.get("strategies", {}).get("hedging", {})
        self.api = api

    async def generate_signal(self, session, symbol: str, kl_1m: List, kl_5m: List, kl_15m: List, kl_1h: List, kl_4h: List, kl_1d: List, kl_1w: List, oi_hist: List) -> Dict:
        inds = compute_indicators(kl_1m, kl_5m, kl_15m, kl_1h, kl_4h, kl_1d, kl_1w)
        if not inds:
            return {}
        beta = float_safe(inds.get("corr_btc", 0.7))
        btc_price = await self.api.fetch_spot_price("BTCUSDT")
        btc_trend = inds.get("macd_1h", 0.0)
        score = 0
        reasons = []
        if beta > self.cfg.get("beta_th", 0.8):
            score += 2
            reasons.append("High BTC beta")
        if btc_trend < 0:
            score += 2
            reasons.append("BTC bearish trend")
        if score >= self.cfg.get("min_score", 3):
            return {
                "strategy_type": "HEDGING",
                "symbol": symbol,
                "side": "short",
                "score": score,
                "reasons": reasons,
                "atr_pct": inds.get("atr_pct_1h", 0.0),
                "adx": inds.get("adx_1h", 0.0),
                "corr_btc": beta
            }
        return {}
