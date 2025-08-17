from datetime import datetime
from typing import Dict

def session_allowed(cfg: Dict, now: datetime) -> bool:
    sessions = cfg.get("sessions", {})
    if not sessions.get("enabled", False):
        return True
    allowed_hours = sessions.get("allow_hours", [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21])
    return now.hour in allowed_hours