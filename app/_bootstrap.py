"""Garante que a raiz do projeto (pasta pai de app/) está no sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ROOT_STR = str(_PROJECT_ROOT)

if _ROOT_STR not in sys.path:
    sys.path.insert(0, _ROOT_STR)
