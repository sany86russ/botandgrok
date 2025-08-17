import sqlite3
import os
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta
import math
from src.utils import float_safe

def _db_path(cfg: Dict) -> str:
    d = cfg.get("paths", {}).get("state_dir", "state")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "metrics.sqlite")

def init_db(cfg: Dict):
    path = _db_path(cfg)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS signals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        symbol TEXT,
        side TEXT,
        entry REAL,
        tp REAL,
        sl REAL,
        strategy_type TEXT,
        score REAL,
        adx REAL,
        vratio REAL,
        atr_pct REAL,
        leverage REAL,
        status TEXT DEFAULT 'open',
        exit_ts TEXT,
        R REAL
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_sym_ts ON signals(symbol, ts);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);")
    con.commit()
    con.close()

def insert_signal(cfg: Dict, payload: Dict[str, Any]) -> int:
    path = _db_path(cfg)
    con = sqlite3.connect(path)
    cur = con.cursor()
    row = (
        datetime.utcnow().isoformat(),
        payload.get("symbol"),
        payload.get("side"),
        float_safe(payload.get("entry", 0.0)),
        float_safe(payload.get("tp1", 0.0)),
        float_safe(payload.get("sl", 0.0)),
        payload.get("strategy_type", ""),
        float_safe(payload.get("score", 0.0)),
        float_safe(payload.get("adx", 0.0)),
        float_safe(payload.get("vratio", 0.0)),
        float_safe(payload.get("atr_pct", 0.0)),
        float_safe(payload.get("leverage", 20.0)),
    )
    cur.execute("INSERT INTO signals(ts,symbol,side,entry,tp,sl,strategy_type,score,adx,vratio,atr_pct,leverage) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", row)
    signal_id = cur.lastrowid
    con.commit()
    con.close()
    return signal_id

def close_signal(cfg: Dict, signal_id: int, exit_price: float, exit_ts: str, outcome: str):
    path = _db_path(cfg)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("SELECT entry,sl FROM signals WHERE id=?", (signal_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return
    entry, sl = row
    R = (exit_price - entry) / (entry - sl) if sl != entry else 0.0
    if outcome == "SL":
        R = -1.0
    cur.execute("UPDATE signals SET status=?, exit_ts=?, R=? WHERE id=?", (outcome, exit_ts, R, signal_id))
    con.commit()
    con.close()

def analyze_recent_performance(cfg: Dict, days: int = 7) -> Dict[str, float]:
    path = _db_path(cfg)
    con = sqlite3.connect(path)
    cur = con.cursor()
    q = """
    SELECT strategy_type, COUNT(*) as n, AVG(R) as avgR, 
           SUM(CASE WHEN R > 0 THEN 1 ELSE 0 END) as wins,
           MAX(R) as maxR, MIN(R) as minR
    FROM signals 
    WHERE ts > ? AND status != 'open'
    GROUP BY strategy_type
    """
    params = [(datetime.utcnow() - timedelta(days=days)).isoformat()]
    cur.execute(q, params)
    rows = cur.fetchall()
    con.close()
    result = {}
    for row in rows:
        strat, n, avgR, wins, maxR, minR = row
        wr = wins / n if n > 0 else 0.0
        result[strat] = {
            "n": n,
            "win_rate": wr,
            "avg_R": avgR,
            "max_R": maxR,
            "min_R": minR
        }
    return result