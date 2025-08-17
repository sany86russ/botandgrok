
import asyncio
import logging
from typing import Dict, List, Any, Tuple
from datetime import datetime
import numpy as np

from src.api import fetch_klines
from src.config import load_config
from src.indicators import compute_indicators
from src.strategies import ScalpingStrategy, IntradayStrategy, SwingStrategy, PositionStrategy
from src.utils import float_safe

log = logging.getLogger("backtester")

def _candle_high_low(candles):
    highs = [float_safe(c[2]) for c in candles]
    lows = [float_safe(c[3]) for c in candles]
    return highs, lows

def _first_touch(entry_idx: int, candles: List[List[float]], tp: float, sl: float, side: str) -> Tuple[str, int]:
    """
    Returns ("TP"/"SL"/"TTL", idx_of_exit)
    """
    for i in range(entry_idx+1, len(candles)):
        high = float_safe(candles[i][2])
        low = float_safe(candles[i][3])
        if side == "long":
            if high >= tp: return "TP", i
            if low <= sl:  return "SL", i
        else:
            if low <= tp:  return "TP", i
            if high >= sl: return "SL", i
    return "TTL", len(candles)-1

def _atr_to_prices(entry: float, atr_pct: float, rr: float, side: str, atr_mult: float) -> Tuple[float,float]:
    # atr_pct expected as percent (e.g., 1.2 means 1.2% of price)
    risk_dist = (atr_pct / 100.0) * atr_mult * entry
    if side == "long":
        sl = entry - risk_dist
        tp = entry + rr * risk_dist
    else:
        sl = entry + risk_dist
        tp = entry - rr * risk_dist
    return tp, sl

class Backtester:
    def __init__(self, cfg: Dict):
        self.cfg = cfg
        self.loop_tf = cfg.get("testing", {}).get("backtest", {}).get("interval", "15m")
        self.limit = cfg.get("testing", {}).get("backtest", {}).get("limit", 1000)
        self.rr = cfg.get("risk", {}).get("rr_target", 2.0)
        self.atr_mult = cfg.get("risk", {}).get("atr_mult", 1.4)

        # instantiate strategies with their sub-configs
        scfg = cfg.get("strategies", {})
        self.strategies = [
            ScalpingStrategy(scfg.get("scalping", {})),
            IntradayStrategy(scfg.get("intraday", {})),
            SwingStrategy(scfg.get("swing", {})),
            PositionStrategy(scfg.get("position", {})),
        ]

    async def _get_candles(self, session, symbol: str) -> List[List[float]]:
        return await fetch_klines(session, symbol, self.loop_tf, self.limit, self.cfg)

    def _run_strategies_single(self, symbol: str, inds: Dict[str, Any]) -> List[Dict[str, Any]]:
        sigs = []
        for st in self.strategies:
            try:
                res = st.generate_signal(symbol, inds)
                if res and res.get("side"):
                    sigs.append(res)
            except Exception:
                log.exception(f"Strategy error on {symbol}")
        return sigs

    async def run_symbol(self, session, symbol: str) -> Dict[str, Any]:
        candles = await self._get_candles(session, symbol)
        if not candles or len(candles) < 100:
            return {"symbol": symbol, "trades": [], "summary": {"n":0}}

        inds = compute_indicators(candles)
        trades = []
        # we will evaluate signal only on each candle close
        for i in range(100, len(candles)-1):
            # simulate decision based on indicators at i
            inds_i = {k: (v[i] if isinstance(v, list) and len(v) > i else v) for k,v in inds.items()}
            sigs = self._run_strategies_single(symbol, inds_i)
            if not sigs:
                continue
            # pick best by 'score' then ADX, then vratio
            sigs = sorted(sigs, key=lambda s: (float_safe(s.get("score",0)), float_safe(s.get("adx",0)), float_safe(s.get("vratio",0))), reverse=True)
            sig = sigs[0]
            side = sig.get("side")
            entry = float_safe(candles[i][4])  # close price
            atr_pct = float_safe(sig.get("atr_pct") or inds_i.get("atr_pct_15m") or 1.0)
            tp, sl = _atr_to_prices(entry, atr_pct, self.rr, side, self.atr_mult)
            outcome, j = _first_touch(i, candles, tp, sl, side)
            r = 0.0
            if outcome == "TP":
                r = self.rr
            elif outcome == "SL":
                r = -1.0
            else:
                # TTL at end — mark as breakeven
                r = 0.0
            trades.append({"i": i, "exit": j, "side": side, "entry": entry, "tp": tp, "sl": sl, "outcome": outcome, "R": r})

        if not trades:
            return {"symbol": symbol, "trades": [], "summary": {"n":0}}

        # summary stats
        R_list = [t["R"] for t in trades]
        wins = sum(1 for r in R_list if r > 0)
        losses = sum(1 for r in R_list if r < 0)
        wr = wins / len(R_list)
        avg_R = float(np.mean(R_list))
        pf = (sum(r for r in R_list if r>0) / max(1e-9, -sum(r for r in R_list if r<0))) if losses>0 else float('inf')
        cum = np.cumsum(R_list)
        mdd = 0.0
        peak = -1e9
        for x in cum:
            if x > peak: peak = x
            dd = peak - x
            if dd > mdd: mdd = dd

        summary = {"n": len(trades), "wr": wr, "avg_R": avg_R, "pf": pf, "mdd_R": mdd, "R_total": float(cum[-1])}
        return {"symbol": symbol, "trades": trades, "summary": summary}

    async def run(self) -> Dict[str, Any]:
        cfg = self.cfg
        symbols = cfg.get("symbols", [])
        results = {}
        import httpx
        async with httpx.AsyncClient() as session:
            for sym in symbols:
                try:
                    results[sym] = await self.run_symbol(session, sym)
                except Exception:
                    log.exception(f"Backtest failed for {sym}")
        return results

async def run_backtest(cfg: Dict) -> Dict[str, Any]:
    bt = Backtester(cfg)
    results = await bt.run()
    # aggregate summary
    agg = {"n":0, "wr":0.0, "avg_R":0.0, "pf":0.0, "mdd_R":0.0, "R_total":0.0}
    n_syms = 0
    wrs = []
    avgs = []
    pfs = []
    mdds = []
    totals = []
    for sym, res in results.items():
        if res["summary"]["n"]>0:
            n_syms += 1
            wrs.append(res["summary"]["wr"])
            avgs.append(res["summary"]["avg_R"])
            pfs.append(res["summary"]["pf"] if np.isfinite(res["summary"]["pf"]) else 0.0)
            mdds.append(res["summary"]["mdd_R"])
            totals.append(res["summary"]["R_total"])
    if n_syms>0:
        agg["n"] = sum(res["summary"]["n"] for res in results.values())
        agg["wr"] = float(np.mean(wrs))
        agg["avg_R"] = float(np.mean(avgs))
        agg["pf"]  = float(np.mean(pfs))
        agg["mdd_R"] = float(np.mean(mdds))
        agg["R_total"] = float(np.sum(totals))
    return {"per_symbol": results, "aggregate": agg}
