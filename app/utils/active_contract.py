"""Contexto do contrato ativo — preenche análise inicial e comparação de versões."""

from __future__ import annotations

import streamlit as st

from app.db import database as db
from app.db.models import Contract, ContractVersion

MODE_COMPARE_SAVED = "📁 Contrato salvo"
MODE_MATRIX_SAVED = "📁 Contrato salvo + proposta"
MODE_COMPARE_QUICK = "📎 Upload rápido (sem salvar)"
MODE_MATRIX_QUICK = "📎 Upload rápido (sem salvar)"


def get_active_contract() -> Contract | None:
    cid = st.session_state.get("active_contract_id")
    if not cid:
        return None
    return db.get_contract(cid)


def get_active_versions() -> list[ContractVersion]:
    cid = st.session_state.get("active_contract_id")
    if not cid:
        return []
    return db.get_versions(cid)


def _default_version_indices(count: int) -> tuple[int, int]:
    """Base = penúltima versão, nova = última (padrão para revisão)."""
    if count <= 0:
        return 0, 0
    if count == 1:
        return 0, 0
    return count - 2, count - 1


def apply_active_contract(contract_id: str | None, *, force: bool = False) -> bool:
    """
    Preenche session_state para análise inicial (última versão) e comparação (base × nova).
    Retorna True se aplicou um contrato válido.
    """
    if not contract_id:
        return False

    if not force and st.session_state.get("_applied_contract_id") == contract_id:
        vid = st.session_state.get("upload_version_id")
        if vid:
            ver = db.get_version(vid)
            if ver and ver.contract_id == contract_id:
                return True

    contract = db.get_contract(contract_id)
    if not contract:
        return False

    versions = db.get_versions(contract_id)
    st.session_state.active_contract_id = contract_id
    st.session_state["upload_contract_name"] = contract.name
    st.session_state["upload_client_name"] = contract.client_name

    if versions:
        latest = versions[-1]
        base_i, new_i = _default_version_indices(len(versions))
        st.session_state.upload_version_id = latest.id
        st.session_state.active_version_id = latest.id
        st.session_state.checklist_version_id = latest.id
        st.session_state.compare_base_version_id = versions[base_i].id
        st.session_state.compare_new_version_id = versions[new_i].id
        st.session_state.compare_base_idx = base_i
        st.session_state.compare_new_idx = new_i
        st.session_state.mtx_contract_ver_idx = len(versions) - 1
        next_num = latest.version_number + 1
        st.session_state["upload_version_label_default"] = f"Revisão v{next_num}"
        st.session_state["upload_version_label"] = st.session_state["upload_version_label_default"]
    else:
        for key in (
            "upload_version_id",
            "active_version_id",
            "checklist_version_id",
            "compare_base_version_id",
            "compare_new_version_id",
        ):
            st.session_state.pop(key, None)
        st.session_state.compare_base_idx = 0
        st.session_state.compare_new_idx = 0
        st.session_state.mtx_contract_ver_idx = 0
        st.session_state["upload_version_label_default"] = "Original"
        st.session_state["upload_version_label"] = "Original"

    st.session_state.compare_mode = MODE_COMPARE_SAVED
    st.session_state.matrix_mode = MODE_MATRIX_SAVED
    st.session_state._applied_contract_id = contract_id
    return True


def ensure_active_contract_applied() -> None:
    """Garante contexto do contrato ativo após navegação entre páginas."""
    cid = st.session_state.get("active_contract_id")
    if cid:
        apply_active_contract(cid)


def on_sidebar_contract_changed(contract_id: str) -> None:
    """Chamado quando o usuário troca o contrato na sidebar."""
    prev = st.session_state.get("_applied_contract_id")
    st.session_state.active_contract_id = contract_id
    if contract_id != prev:
        apply_active_contract(contract_id, force=True)


def clear_active_contract_context() -> None:
    """Novo contrato do zero — limpa vínculos de preenchimento."""
    st.session_state.active_contract_id = None
    st.session_state._applied_contract_id = None
    for key in (
        "upload_version_id",
        "active_version_id",
        "checklist_version_id",
        "compare_base_version_id",
        "compare_new_version_id",
        "upload_contract_name",
        "upload_client_name",
    ):
        st.session_state.pop(key, None)


def version_select_index(
    versions: list[ContractVersion],
    version_id: str | None,
    fallback_idx: int,
) -> int:
    if not versions:
        return 0
    if version_id:
        for i, v in enumerate(versions):
            if v.id == version_id:
                return i
    return min(max(0, fallback_idx), len(versions) - 1)


def render_active_contract_banner(
    *,
    context: str = "upload",
    show_versions: bool = True,
) -> None:
    """Exibe resumo do contrato ativo e atalhos de contexto."""
    contract = get_active_contract()
    if not contract:
        return

    versions = get_active_versions()
    proposal_note = ""
    if db.contract_has_proposal(contract):
        proposal_note = f" · Proposta: **{contract.proposal_label}**"
    elif context == "upload":
        proposal_note = " · ⚠️ Sem proposta na seção 1b"

    ver_line = ""
    if show_versions and versions:
        latest = versions[-1]
        base_i, new_i = _default_version_indices(len(versions))
        if len(versions) >= 2:
            ver_line = (
                f" · Versões: **{len(versions)}** "
                f"(análise inicial → v{latest.version_number} «{latest.label}»; "
                f"comparar → v{versions[base_i].version_number} × v{versions[new_i].version_number})"
            )
        else:
            ver_line = f" · Versão: **v{latest.version_number}** — {latest.label}"

    st.info(
        f"**Contrato ativo:** {contract.name} ({contract.client_name}){proposal_note}{ver_line}"
    )
