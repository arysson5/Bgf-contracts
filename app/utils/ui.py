"""Utilitários de UI compartilhados entre páginas Streamlit."""

from pathlib import Path

import streamlit as st

from app.db import database as db
from app.utils.data_cache import cached_contracts, clear_data_cache
from app.utils.security import safe_temp_path, safe_upload_path


def init_session_state() -> None:
    defaults = {
        "active_contract_id": None,
        "active_version_id": None,
        "last_checklist_result": None,
        "last_diff_result": None,
        "last_comments_result": None,
        "selected_template_id": None,
        "extracted_comments": None,
        "annotated_pdf_path": None,
        "annotated_file_path": None,
        "compare_base_version_id": None,
        "compare_new_version_id": None,
        "checklist_version_id": None,
        "quick_compare_ctx": None,
        "compare_mode_kind": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def render_contract_selector(key: str = "contract_select") -> str | None:
    contracts = cached_contracts()
    if not contracts:
        st.info("Nenhum contrato cadastrado. Faça upload na página de Checklist.")
        return None
    options = {f"{c.name} ({c.client_name})": c.id for c in contracts}
    labels = list(options.keys())
    default_idx = 0
    if st.session_state.active_contract_id:
        for i, label in enumerate(labels):
            if options[label] == st.session_state.active_contract_id:
                default_idx = i
                break
    selected_label = st.selectbox("Contrato", labels, index=default_idx, key=key)
    contract_id = options[selected_label]
    st.session_state.active_contract_id = contract_id
    return contract_id


def save_uploaded_file(uploaded_file, contracts_dir) -> str:
    root = Path(contracts_dir)
    root.mkdir(parents=True, exist_ok=True)
    dest = safe_upload_path(root, uploaded_file.name)
    dest.write_bytes(uploaded_file.getvalue())
    clear_data_cache()
    return str(dest)


def save_temp_upload(uploaded_file, contracts_dir, prefix: str = "cmp") -> str:
    """Salva arquivo temporário para comparação rápida (path seguro)."""
    root = Path(contracts_dir)
    dest = safe_temp_path(root, uploaded_file.name, prefix=prefix)
    dest.write_bytes(uploaded_file.getvalue())
    return str(dest)
