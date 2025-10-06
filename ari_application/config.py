from pathlib import Path
from functools import lru_cache
import os, yaml

DEFAULTS = [
    os.getenv("FREYA_CONFIG", ""),            
    "/etc/asterisk/freya.yaml",               
    "../asterisk/etc/freya.yaml",    
]

@lru_cache(maxsize=1)
def cfg() -> dict:
    for cand in DEFAULTS:
        if cand and Path(cand).exists():
            with open(cand, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    raise FileNotFoundError(f"Config not found in any of: {', '.join([p for p in DEFAULTS if p])}")