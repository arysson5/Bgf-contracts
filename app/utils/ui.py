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
        "last_matrix_result": None,
        "last_matrix_initial_result": None,
        "selected_matrix_template_id": None,
        "matrix_mode_kind": None,
        "matrix_quick_ctx": None,
        "matrix_saved_ctx": None,
        "last_regression_result": None,
        "last_comment_verification": None,
        "compare_base_idx": 0,
        "compare_new_idx": 0,
        "mtx_contract_ver_idx": 0,
        "_applied_contract_id": None,
        "upload_contract_name": "",
        "upload_client_name": "",
        "upload_version_label_default": "Original",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _unique_sorted_clients(contracts) -> list[str]:
    names = {c.client_name.strip() for c in contracts if c.client_name and c.client_name.strip()}
    return sorted(names, key=str.lower)


@st.cache_data(ttl=20, show_spinner=False)
def _version_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in cached_contracts():
        counts[c.id] = len(db.get_versions(c.id))
    return counts


def _contract_label(c, *, show_client: bool = True) -> str:
    n_ver = _version_counts().get(c.id, 0)
    ver_tag = f"{n_ver}v" if n_ver else "0v"
    if show_client:
        return f"{c.name} · {c.client_name} ({ver_tag})"
    return f"{c.name} ({ver_tag})"


def _filter_contracts(
    contracts,
    *,
    client: str | None = None,
    search_q: str = "",
) -> list:
    filtered = list(contracts)
    if client and client != "— Todos —":
        filtered = [c for c in filtered if c.client_name.strip() == client]
    if search_q.strip():
        q = search_q.strip().lower()
        filtered = [
            c
            for c in filtered
            if q in c.name.lower()
            or q in (c.client_name or "").lower()
            or q in c.id.lower()
        ]
    return filtered


def render_contract_browse_selector(
    key_prefix: str = "browse",
    *,
    sync_active: bool = True,
    show_search: bool = True,
) -> str | None:
    """
    Seleciona contrato salvo por cliente, busca e nome.
    """
    contracts = cached_contracts()
    if not contracts:
        st.info("Nenhum contrato cadastrado. Comece em **Upload & Análise inicial**.")
        return None

    clients = _unique_sorted_clients(contracts)
    client_options = ["— Todos —", *clients]

    active = db.get_contract(st.session_state.active_contract_id) if st.session_state.get(
        "active_contract_id"
    ) else None
    default_client_idx = 0
    if active and active.client_name.strip() in clients:
        default_client_idx = client_options.index(active.client_name.strip())

    c1, c2 = st.columns([1, 2])
    with c1:
        selected_client = st.selectbox(
            "Cliente",
            client_options,
            index=default_client_idx,
            key=f"{key_prefix}_client",
        )
    with c2:
        search_q = ""
        if show_search:
            search_q = st.text_input(
                "Buscar contrato",
                key=f"{key_prefix}_search",
                placeholder="Nome, cliente ou ID…",
            )

    filtered = _filter_contracts(
        contracts,
        client=selected_client,
        search_q=search_q,
    )

    if not filtered:
        st.warning("Nenhum contrato encontrado. Ajuste os filtros.")
        return None

    show_client_in_label = selected_client == "— Todos —"
    contract_labels = [
        _contract_label(c, show_client=show_client_in_label) for c in filtered
    ]
    label_to_id = {lbl: filtered[i].id for i, lbl in enumerate(contract_labels)}

    default_contract_idx = 0
    if active:
        for i, c in enumerate(filtered):
            if c.id == active.id:
                default_contract_idx = i
                break

    contract_id = label_to_id[
        st.selectbox(
            "Contrato",
            contract_labels,
            index=default_contract_idx,
            key=f"{key_prefix}_contract",
        )
    ]

    if sync_active:
        from app.utils.active_contract import on_sidebar_contract_changed

        on_sidebar_contract_changed(contract_id)

    rec = db.get_contract(contract_id)
    if rec:
        n_ver = _version_counts().get(contract_id, 0)
        has_prop = db.contract_has_proposal(rec)
        prop_hint = "com proposta" if has_prop else "sem proposta"
        st.caption(f"**{rec.name}** — {rec.client_name} · {n_ver} versão(ões) · {prop_hint}")

    return contract_id


def render_contract_selector(key: str = "contract_select") -> str | None:
    """Atalho unificado — mesma experiência de busca em todas as páginas."""
    return render_contract_browse_selector(key, sync_active=True)


def save_uploaded_file(uploaded_file, contracts_dir) -> str:
    root = Path(contracts_dir)
    root.mkdir(parents=True, exist_ok=True)
    dest = safe_upload_path(root, uploaded_file.name)
    dest.write_bytes(uploaded_file.getvalue())
    clear_data_cache()
    return str(dest)


def render_compare_version_pair(
    versions,
    *,
    base_key: str = "base_ver",
    new_key: str = "new_ver",
) -> tuple:
    """Dois selectboxes: versão com comentários × versão revisada."""
    from app.utils.active_contract import version_option_label, version_select_index

    labels = [version_option_label(v) for v in versions]
    id_map = {lbl: v.id for lbl, v in zip(labels, versions)}

    base_idx = version_select_index(
        versions,
        st.session_state.get("compare_base_version_id"),
        st.session_state.get("compare_base_idx", max(0, len(versions) - 2)),
    )
    new_idx = version_select_index(
        versions,
        st.session_state.get("compare_new_version_id"),
        st.session_state.get("compare_new_idx", len(versions) - 1),
    )
    c1, c2 = st.columns(2)
    with c1:
        bl = st.selectbox(
            "Com comentários",
            labels,
            base_idx,
            key=base_key,
        )
    with c2:
        nl = st.selectbox(
            "Revisado",
            labels,
            new_idx,
            key=new_key,
        )
    st.session_state.compare_base_idx = labels.index(bl)
    st.session_state.compare_new_idx = labels.index(nl)
    st.session_state.compare_base_version_id = id_map[bl]
    st.session_state.compare_new_version_id = id_map[nl]
    va = db.get_version(id_map[bl])
    vb = db.get_version(id_map[nl])
    return va, vb


def save_temp_upload(uploaded_file, contracts_dir, prefix: str = "cmp") -> str:
    """Salva arquivo temporário para comparação rápida (path seguro)."""
    root = Path(contracts_dir)
    dest = safe_temp_path(root, uploaded_file.name, prefix=prefix)
    dest.write_bytes(uploaded_file.getvalue())
    return str(dest)
