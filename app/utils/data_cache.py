"""Cache leve de consultas ao banco para reduzir trabalho a cada rerun do Streamlit."""

from __future__ import annotations

import streamlit as st

from app.db import database as db


def _current_owner_id() -> str | None:
    from app.utils.auth import get_current_user_id

    return get_current_user_id()


@st.cache_data(ttl=20, show_spinner=False)
def _cached_contracts_for_user(owner_user_id: str | None) -> list:
    return db.get_contracts(owner_user_id=owner_user_id)


def cached_contracts_for_session() -> list:
    return _cached_contracts_for_user(_current_owner_id())


def cached_contracts() -> list:
    return cached_contracts_for_session()


@st.cache_data(ttl=15, show_spinner=False)
def _cached_recent_analyses(limit: int, owner_user_id: str | None) -> list:
    contracts = db.get_contracts(owner_user_id=owner_user_id)
    contract_ids = {c.id for c in contracts}
    rows = db.get_recent_analyses(limit * 3)
    filtered = []
    for rec in rows:
        ver = db.get_version(rec.version_id)
        if ver and ver.contract_id in contract_ids:
            filtered.append(rec)
        if len(filtered) >= limit:
            break
    return filtered


def cached_recent_analyses_for_session(limit: int = 5) -> list:
    return _cached_recent_analyses(limit, _current_owner_id())


def cached_recent_analyses(limit: int = 5) -> list:
    return cached_recent_analyses_for_session(limit)


@st.cache_data(ttl=15, show_spinner=False)
def _cached_analyses_today_count(owner_user_id: str | None) -> int:
    from app.utils.datetime_br import brazil_today, to_brazil_time

    contracts = db.get_contracts(owner_user_id=owner_user_id)
    contract_ids = {c.id for c in contracts}
    today = brazil_today()
    count = 0
    for rec in db.get_recent_analyses(200):
        ver = db.get_version(rec.version_id)
        if not ver or ver.contract_id not in contract_ids:
            continue
        if rec.created_at and to_brazil_time(rec.created_at).date() == today:
            count += 1
    return count


def cached_analyses_today_count_for_session() -> int:
    return _cached_analyses_today_count(_current_owner_id())


def cached_analyses_today_count() -> int:
    return cached_analyses_today_count_for_session()


@st.cache_data(ttl=20, show_spinner=False)
def _cached_version_count(owner_user_id: str | None) -> int:
    total = 0
    for c in db.get_contracts(owner_user_id=owner_user_id):
        total += len(db.get_versions(c.id))
    return total


def cached_version_count_for_session() -> int:
    return _cached_version_count(_current_owner_id())


def cached_version_count() -> int:
    return cached_version_count_for_session()


def clear_data_cache() -> None:
    """Invalida cache após criar contrato, versão ou análise."""
    _cached_contracts_for_user.clear()
    _cached_recent_analyses.clear()
    _cached_analyses_today_count.clear()
    _cached_version_count.clear()
