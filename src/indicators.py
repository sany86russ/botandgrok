from typing import List, Dict
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator, ADXIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange

def compute_indicators(kl_1m: List, kl_5m: List, kl_15m: List, kl_1h: List, kl_4h: List, kl_1d: List, kl_1w: List) -> Dict:
    result = {}
    for timeframe, klines in [
        ("1m", kl_1m), ("5m", kl_5m), ("15m", kl_15m), ("1h", kl_1h),
        ("4h", kl_4h), ("1d", kl_1d), ("1w", kl_1w)
    ]:
        if not klines or len(klines) < 20:
            continue
        df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume"])
        result[f"close_{timeframe}"] = df["close"].values
        result[f"rsi_{timeframe}"] = RSIIndicator(df["close"], window=7 if timeframe in ["1m", "5m"] else 14).rsi().iloc[-1]
        result[f"stoch_{timeframe}"] = StochasticOscillator(df["high"], df["low"], df["close"], window=14).stoch().iloc[-1]
        result[f"adx_{timeframe}"] = ADXIndicator(df["high"], df["low"], df["close"], window=14).adx().iloc[-1]
        result[f"macd_{timeframe}"] = MACD(df["close"], window_fast=5 if timeframe in ["1m", "5m"] else 12).macd().iloc[-1]
        result[f"atr_{timeframe}"] = AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range().iloc[-1]
        result[f"atr_pct_{timeframe}"] = result[f"atr_{timeframe}"] / df["close"].iloc[-1] * 100
        result[f"bbw_{timeframe}"] = (BollingerBands(df["close"], window=20).bollinger_hband() - BollingerBands(df["close"], window=20).bollinger_lband()) / BollingerBands(df["close"], window=20).bollinger_mavg() * 100
        result[f"ema5_{timeframe}"] = EMAIndicator(df["close"], window=5).ema_indicator().iloc[-1]
        result[f"ema20_{timeframe}"] = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
        result[f"ema50_{timeframe}"] = EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1]
        result[f"ema200_{timeframe}"] = EMAIndicator(df["close"], window=200).ema_indicator().iloc[-1]
        # Fibonacci Retracement (для свинга)
        if timeframe == "4h":
            high = df["high"].max()
            low = df["low"].min()
            diff = high - low
            result[f"fib_618_{timeframe}"] = high - 0.618 * diff
        result["corr_btc"] = 0.7  # Заглушка для корреляции
    return result