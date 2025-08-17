from typing import Dict, List, Tuple

def allocate_risk(deposit: float, allocator_config: Dict, candidates: List[Dict]) -> List[Tuple[Dict, float]]:
    max_alloc = allocator_config.get("max_risk_pct", 0.005)
    return [(c, max_alloc / len(candidates) if candidates else 0) for c in candidates]