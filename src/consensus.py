from typing import List, Dict

def rank_and_filter(candidates: List[Dict], max_per_symbol: int, min_score: float) -> List[Dict]:
    candidates = [c for c in candidates if c.get("score", 0) >= min_score]
    candidates.sort(key=lambda x: x["score"], reverse=True)
    seen = {}
    result = []
    for c in candidates:
        sym = c["symbol"]
        seen[sym] = seen.get(sym, 0) + 1
        if seen[sym] <= max_per_symbol:
            result.append(c)
    return result