from typing import List, Dict
import pandas as pd
import numpy as np

def compute_indicators_extras(kl_15m: List) -> Dict:
    if not kl_15m or len(kl_15m) < 20:
        return {}
    
    df = pd.DataFrame(kl_15m, columns=["timestamp", "open", "high", "low", "close", "volume"])
    result = {}
    
    # VWAP
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    result["vwap_15m"] = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum().iloc[-1]
    
    # Volume Ratio
    short_vol = df["volume"].rolling(window=5).mean().iloc[-1]
    long_vol = df["volume"].rolling(window=20).mean().iloc[-1]
    result["vratio_15m"] = short_vol / long_vol if long_vol > 0 else 1.0
    
    # BBW Percentile
    bb_width = (df["high"] - df["low"]) / df["close"] * 100
    result["bbw_pctile_15m"] = pd.Series(bb_width).rank(pct=True).iloc[-1] * 100
    
    return result