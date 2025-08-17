
import numpy as np
from typing import Dict, List

def rolling_corr(returns: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
    syms = list(returns.keys())
    out = {s: {} for s in syms}
    for i,s1 in enumerate(syms):
        r1 = np.array(returns[s1], dtype=float)
        for s2 in syms[i+1:]:
            r2 = np.array(returns[s2], dtype=float)
            if len(r1) != len(r2) or len(r1) < 10:
                c = 0.0
            else:
                c = float(np.corrcoef(r1, r2)[0,1])
            out[s1][s2] = c
            out[s2][s1] = c
    return out

def high_corr_bucket(symbol: str, active: List[str], corr: Dict[str, Dict[str, float]], th: float=0.8) -> List[str]:
    return [s for s in active if abs(corr.get(symbol, {}).get(s, 0.0)) >= th]
