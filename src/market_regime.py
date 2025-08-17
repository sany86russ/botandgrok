from typing import Dict

def market_regime(inds: Dict) -> str:
    adx = inds.get("adx_15m", 0.0)
    if adx > 25:
        return "trending"
    return "ranging"