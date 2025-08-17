from typing import Dict

def strategy_weight(cfg: Dict, strategy: str) -> float:
    weights = cfg.get("weights", {}).get("enable", False)
    if not weights:
        return 1.0
    min_factor = cfg.get("weights", {}).get("min_factor", 0.85)
    max_factor = cfg.get("weights", {}).get("max_factor", 1.15)
    return min(max_factor, max(min_factor, 1.0))  # Заглушка для весов