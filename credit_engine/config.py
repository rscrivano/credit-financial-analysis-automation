"""Environment loading. Looks for .env in the repo folder first, then one folder up
(the course's submissions/.env layout). Existing environment variables win.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def load_env() -> list[Path]:
    """Load .env files (repo first, then parent). Returns the files that were read."""
    loaded = []
    for path in (REPO_ROOT / ".env", REPO_ROOT.parent / ".env"):
        if path.is_file():
            for k, v in _parse(path).items():
                if v and not os.environ.get(k):
                    os.environ[k] = v
            loaded.append(path)
    return loaded
