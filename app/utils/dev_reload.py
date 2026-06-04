"""Sincroniza módulos app.* com o disco quando fileWatcherType=none no Streamlit."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _PROJECT_ROOT / "app"
_MTIMES_KEY = "_dev_module_mtimes"
_INIT_KEY = "_dev_reload_initialized"


def _module_name_for(py: Path) -> str:
    rel = py.relative_to(_PROJECT_ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        return ".".join(parts[:-1])
    parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _drop_app_modules() -> None:
    for name in list(sys.modules):
        if name.startswith("app.") and name != "app":
            del sys.modules[name]


def _disk_mtimes() -> dict[str, float]:
    out: dict[str, float] = {}
    for py_file in _APP_DIR.rglob("*.py"):
        try:
            out[_module_name_for(py_file)] = py_file.stat().st_mtime
        except OSError:
            continue
    return out


def sync_app_modules(session_store: dict | None = None) -> None:
    """
    Invalida cache de import quando arquivos em app/ mudaram.

    Deve ser chamado no início de cada script Streamlit (antes de outros imports app.*),
    passando st.session_state para persistir mtimes entre reruns.
    """
    store = session_store if session_store is not None else {}

    if not store.get(_INIT_KEY):
        store[_INIT_KEY] = True
        _drop_app_modules()
        store[_MTIMES_KEY] = _disk_mtimes()
        return

    mtimes: dict[str, float] = store.setdefault(_MTIMES_KEY, {})
    current = _disk_mtimes()
    changed = any(current.get(m, 0) > mtimes.get(m, 0) + 1e-6 for m in current)

    if changed:
        _drop_app_modules()
        store[_MTIMES_KEY] = current
