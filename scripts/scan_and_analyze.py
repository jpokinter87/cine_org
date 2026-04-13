#!/usr/bin/env python3
"""Régénère le cache scan qualité et analyse les patterns."""
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infrastructure.persistence.database import get_session
from src.services.association_checker import AssociationChecker

session = next(get_session())
try:
    checker = AssociationChecker(session)

    def progress(i, t, label):
        if i % 200 == 0 or i == t:
            print(f"  {i}/{t}  {label}", flush=True)

    results = checker.scan_suspicious(on_progress=progress)
finally:
    session.close()

print(f"\n{len(results)} associations suspectes détectées")

cache_data = {
    "time": time.time(),
    "results": [asdict(r) for r in results],
}
cache_path = Path.home() / ".cineorg" / "quality_scan_cache.json"
cache_path.write_text(json.dumps(cache_data, ensure_ascii=False))
print(f"Cache : {cache_path}")
