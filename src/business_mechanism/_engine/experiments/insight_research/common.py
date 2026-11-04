"""Small storage primitives; old implementation is imported, never rewritten."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
for directory in ('business_team', 'capability_lab'):
    location = str(ROOT / 'experiments' / directory)
    if location not in sys.path:
        sys.path.append(location)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.pending')
    temporary.write_text(encoded(value) + '\n')
    temporary.replace(path)


class Pending(RuntimeError):
    """Execution cannot safely advance; this is not a scientific refutation."""
