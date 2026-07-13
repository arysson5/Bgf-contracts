"""Verifica imports dos módulos de serviço (sem páginas Streamlit)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Módulos que dependem de Streamlit runtime ou side-effects na importação
SKIP_MODULES = {
    "app.main",
    "app.pages.01_upload",
    "app.pages.02_compare",
    "app.pages.04_history",
}


def _core_modules() -> list[str]:
    app_dir = ROOT / "app"
    modules: list[str] = []
    for py in sorted(app_dir.rglob("*.py")):
        if py.name == "__init__.py":
            continue
        if py.parent.name == "pages":
            continue
        rel = py.relative_to(ROOT).with_suffix("")
        mod = ".".join(rel.parts)
        if mod in SKIP_MODULES:
            continue
        modules.append(mod)
    return modules


@pytest.mark.parametrize("module_name", _core_modules())
def test_core_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)


def test_third_party_dependencies() -> None:
    """Bibliotecas críticas declaradas em requirements.txt."""
    for pkg in (
        "streamlit",
        "diff_match_patch",
        "bcrypt",
        "rapidfuzz",
        "sqlmodel",
        "pydantic",
        "fitz",
        "pdfplumber",
        "docx",
        "langchain_google_genai",
    ):
        importlib.import_module(pkg)
