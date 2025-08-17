
import os
import yaml
from pydantic import BaseModel, Field, ValidationError, conint, confloat
from typing import List, Optional, Dict, Any

class RiskGuardModel(BaseModel):
    stop_day_R: float = Field(default=-3.0)
    loss_streak_cooldown: conint(ge=1) = 3
    cooldown_sec_after_streak: conint(ge=60) = 1800
    cooldown_sec_after_stop: conint(ge=300) = 8*3600
    max_signals_per_day: conint(ge=1) = 60

class RiskModel(BaseModel):
    leverage: conint(ge=1, le=125) = 20
    atr_mult: confloat(gt=0) = 1.4
    rr_target: confloat(gt=0) = 2.0
    risk_per_trade_pct: confloat(gt=0, le=5) = 0.6
    trailing_init_mult_atr: confloat(gt=0) = 2.5
    trailing_step_mult_atr: confloat(gt=0) = 0.8
    auto: Dict[str, Any] = {}
    guard: RiskGuardModel = RiskGuardModel()

class ConsensusModel(BaseModel):
    min_score: float = 2.0
    max_per_symbol: conint(ge=1) = 1
    per_symbol_cooldown_sec: conint(ge=0) = 600
    anti_reverse_min_sec: conint(ge=0) = 1800
    cooldown_same_sec: conint(ge=0) = 600
    cooldown_opp_sec: conint(ge=0) = 1800

class SessionsModel(BaseModel):
    enabled: bool = False
    allow: List[str] = ["europe","us","asia"]

class PartialTPModel(BaseModel):
    enable: bool = True
    tp1_atr: confloat(gt=0) = 1.0
    tp2_atr: confloat(gt=0) = 2.0
    be_after_tp1: bool = True

class TPModel(BaseModel):
    partial: PartialTPModel = PartialTPModel()

class ConfigModel(BaseModel):
    symbols: List[str]
    scan_interval_sec: conint(ge=1) = 15
    deposit_usdt: confloat(gt=0) = 1000.0
    follow_fast_poll_sec: conint(ge=1) = 3
    follow_enabled: bool = True
    follow_lookahead_min: conint(ge=1) = 60
    exchange: Dict[str, Any] = {}
    network: Dict[str, Any] = {}
    sr: Dict[str, Any] = {}
    tp: TPModel = TPModel()
    strategies: Dict[str, Any] = {}
    telegram: Dict[str, Any] = {}
    risk: RiskModel = RiskModel()
    consensus: ConsensusModel = ConsensusModel()
    sessions: SessionsModel = SessionsModel()
    discovery: Dict[str, Any] = {}
    paths: Dict[str, Any] = {}
    testing: Dict[str, Any] = {}

def _read_yaml() -> dict:
    path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_config() -> dict:
    raw = _read_yaml()
    try:
        m = ConfigModel(**raw)
        return m.model_dump()
    except ValidationError as e:
        # Non-breaking: log-like print and fallback to raw with minimal coerces
        print("Config validation warning:", e)
        return raw
