"""Cache leve de consultas ao banco para reduzir trabalho a cada rerun do Streamlit."""

from __future__ import annotations

import streamlit as st

from app.db import database as db


@st.cache_data(ttl=20, show_spinner=False)
def cached_contracts() -> list:
    return db.get_contracts()


@st.cache_data(ttl=15, show_spinner=False)
def cached_recent_analyses(limit: int = 5) -> list:
    return db.get_recent_analyses(limit)


@st.cache_data(ttl=15, show_spinner=False)
def cached_analyses_today_count() -> int:
    return db.count_analyses_today()


@st.cache_data(ttl=20, show_spinner=False)
def cached_version_count() -> int:
    total = 0
    for c in cached_contracts():
        total += len(db.get_versions(c.id))
    return total


def clear_data_cache() -> None:
    """Invalida cache após criar contrato, versão ou análise."""
    cached_contracts.clear()
    cached_recent_analyses.clear()
    cached_analyses_today_count.clear()
    cached_version_count.clear()
