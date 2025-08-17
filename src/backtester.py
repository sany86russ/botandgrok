from typing import Dict, List
import pandas as pd
from src.strategies import ScalpingStrategy, IntradayStrategy, SwingStrategy, PositionStrategy, ArbitrageStrategy, HedgingStrategy
from src.utils import float_safe

async def backtest(cfg: Dict, api: Any, symbol: str, start_date: str, end_date: str) -> Dict:
    interval = cfg.get("testing", {}).get("backtest", {}).get("interval", "15m")
    klines = await api.fetch_klines(symbol, interval, limit=1000)
    df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume"])
    results = {"trades": [], "win_rate": 0.0, "avg_R": 0.0}
    strategies = [
        ScalpingStrategy(cfg, api),
        IntradayStrategy(cfg, api),
        SwingStrategy(cfg, api),
        PositionStrategy(cfg, api),
        ArbitrageStrategy(cfg, api),
        HedgingStrategy(cfg, api)
    ]
    for strat in strategies:
        for i in range(20, len(df)):
            kl_1m = df.iloc[:i].values.tolist() if interval == "1m" else []
            kl_5m = df.iloc[:i].values.tolist() if interval == "5m" else []
            kl_15m = df.iloc[:i].values.tolist() if interval == "15m" else []
            kl_1h = df.iloc[:i].values.tolist() if interval == "1h" else []
            kl_4h = df.iloc[:i].values.tolist() if interval == "4h" else []
            kl_1d = df.iloc[:i].values.tolist() if interval == "1d" else []
            kl_1w = df.iloc[:i].values.tolist() if interval == "1w" else []
            signal = await strat.generate_signal(None, symbol, kl_1m, kl_5m, kl_15m, kl_1h, kl_4h, kl_1d, kl_1w, [])
            if signal:
                results["trades"].append({
                    "symbol": symbol,
                    "strategy": strat.__class__.__name__,
                    "score": signal["score"],
                    "side": signal["side"],
                    "entry": signal["entry"],
                    "tp1": signal.get("tp1", 0),
                    "sl": signal.get("sl", 0)
                })
    results["win_rate"] = len([t for t in results["trades"] if t["score"] > 0]) / len(results["trades"]) if results["trades"] else 0.0
    results["avg_R"] = sum([t["score"] for t in results["trades"]]) / len(results["trades"]) if results["trades"] else 0.0
    return results
