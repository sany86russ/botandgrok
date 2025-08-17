import pandas as pd
from typing import Dict, List
from src.utils import float_safe

async def compute_correlation(api: Any, symbol: str, btc_data: List, klines: List) -> float:
    if not klines or not btc_data or len(klines) < 20 or len(btc_data) < 20:
        return 0.7  # Заглушка
    df_symbol = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_btc = pd.DataFrame(btc_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    returns_symbol = df_symbol["close"].pct_change().dropna()
    returns_btc = df_btc["close"].pct_change().dropna()
    if len(returns_symbol) != len(returns_btc):
        return 0.7
    return float_safe(returns_symbol.corr(returns_btc))
