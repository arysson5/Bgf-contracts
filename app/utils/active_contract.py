"""Contexto do contrato ativo — preenche análise inicial e comparação de versões."""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from app.db import database as db
from app.db.models import Contract, ContractVersion

MODE_COMPARE_SAVED = "📁 Contrato salvo"
MODE_MATRIX_SAVED = "📁 Contrato salvo + proposta"
MODE_COMPARE_QUICK = "📎 Upload rápido (sem salvar)"
MODE_MATRIX_QUICK = "📎 Upload rápido (sem salvar)"

SIDEBAR_NONE_LABEL = "— Nenhum (começar do zero) —"
PENDING_SIDEBAR_CONTRACT_KEY = "_pending_sidebar_contract_id"
SIDEBAR_LABEL_MAP_KEY = "_sidebar_label_to_id"

CONTRACT_SOURCE_SAVED = "Usar contrato salvo"
CONTRACT_SOURCE_NEW = "Enviar um novo agora"

PROPOSAL_SOURCE_SAVED = "Usar proposta salva"
PROPOSAL_SOURCE_NEW = "Enviar uma nova agora"
PROPOSAL_SOURCE_NONE = "Analisar sem proposta"

PROPOSAL_MODE_SAVED = "saved"
PROPOSAL_MODE_NEW = "new"
PROPOSAL_MODE_NONE = "none"

_UPLOAD_VERSION_LABEL_KEY = "upload_version_label"
_UPLOAD_VERSION_LABEL_DEFAULT_KEY = "upload_version_label_default"


def _prepare_upload_version_label(default: str) -> None:
    """
    Atualiza a sugestão do label e reseta o widget.

    Só pode ser chamado antes de instanciar st.text_input(key=upload_version_label).
    """
    st.session_state[_UPLOAD_VERSION_LABEL_DEFAULT_KEY] = default
    st.session_state.pop(_UPLOAD_VERSION_LABEL_KEY, None)


def init_upload_version_label_widget() -> None:
    """Inicializa o widget do label após apply_active_contract (antes do text_input)."""
    if _UPLOAD_VERSION_LABEL_KEY not in st.session_state:
        st.session_state[_UPLOAD_VERSION_LABEL_KEY] = st.session_state.get(
            _UPLOAD_VERSION_LABEL_DEFAULT_KEY, "Original"
        )


def _owner_user_id() -> str | None:
    from app.utils.auth import get_current_user_id

    return get_current_user_id()


def file_basename(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).name


def get_active_contract() -> Contract | None:
    cid = st.session_state.get("active_contract_id")
    if not cid:
        return None
    return db.get_contract(cid, owner_user_id=_owner_user_id())


def get_active_versions() -> list[ContractVersion]:
    cid = st.session_state.get("active_contract_id")
    if not cid:
        return []
    return db.get_versions(cid)


def get_active_version() -> ContractVersion | None:
    vid = st.session_state.get("upload_version_id") or st.session_state.get(
        "active_version_id"
    )
    if not vid:
        return None
    ver = db.get_version(vid)
    contract_id = st.session_state.get("active_contract_id")
    if ver and contract_id and ver.contract_id != contract_id:
        return None
    return ver


def _default_version_indices(count: int) -> tuple[int, int]:
    """Base = penúltima versão, nova = última (padrão para revisão)."""
    if count <= 0:
        return 0, 0
    if count == 1:
        return 0, 0
    return count - 2, count - 1


def request_sidebar_contract(contract_id: str | None) -> None:
    """Agenda o select da sidebar para o próximo render (antes do widget)."""
    st.session_state[PENDING_SIDEBAR_CONTRACT_KEY] = contract_id


def set_active_version(version_id: str | None) -> None:
    """Define a versão usada na análise inicial sem resetar o contrato."""
    if not version_id:
        return
    ver = db.get_version(version_id)
    if not ver:
        return
    st.session_state.upload_version_id = ver.id
    st.session_state.active_version_id = ver.id
    st.session_state.checklist_version_id = ver.id


def get_proposal_mode() -> str:
    mode = st.session_state.get("analysis_proposal_mode", PROPOSAL_MODE_NONE)
    if mode in {PROPOSAL_MODE_SAVED, PROPOSAL_MODE_NEW, PROPOSAL_MODE_NONE}:
        return mode
    return PROPOSAL_MODE_NONE


def proposal_requires_save() -> bool:
    return get_proposal_mode() == PROPOSAL_MODE_NEW


def get_proposal_for_analysis(
    contract: Contract | None,
) -> tuple[str, str, bool]:
    """Retorna (texto, rótulo, usada) conforme o select da sessão."""
    if get_proposal_mode() != PROPOSAL_MODE_SAVED:
        return "", "Proposta comercial", False
    if not contract or not db.contract_has_proposal(contract):
        return "", "Proposta comercial", False
    return (
        contract.proposal_extracted_text or "",
        contract.proposal_label or "Proposta comercial",
        True,
    )


def set_proposal_mode(mode: str) -> None:
    if mode not in {PROPOSAL_MODE_SAVED, PROPOSAL_MODE_NEW, PROPOSAL_MODE_NONE}:
        mode = PROPOSAL_MODE_NONE
    st.session_state.analysis_proposal_mode = mode


def _set_analysis_modes_for_contract(contract: Contract) -> None:
    st.session_state.analysis_contract_mode = "saved"
    st.session_state["upload_contract_source"] = CONTRACT_SOURCE_SAVED
    if db.contract_has_proposal(contract):
        set_proposal_mode(PROPOSAL_MODE_SAVED)
    else:
        set_proposal_mode(PROPOSAL_MODE_NONE)


def apply_active_contract(
    contract_id: str | None,
    *,
    force: bool = False,
    reset_source_widgets: bool = False,
) -> bool:
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

    contract = db.get_contract(contract_id, owner_user_id=_owner_user_id())
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
        _prepare_upload_version_label(f"Revisão v{next_num}")
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
        _prepare_upload_version_label("Original")

    st.session_state.compare_mode = MODE_COMPARE_SAVED
    st.session_state.matrix_mode = MODE_MATRIX_SAVED
    st.session_state._applied_contract_id = contract_id
    _set_analysis_modes_for_contract(contract)

    if reset_source_widgets:
        st.session_state.pop(f"sidebar_active_version_{contract_id}", None)
        st.session_state.pop(f"sidebar_proposal_mode_{contract_id}", None)
        st.session_state.pop(f"upload_analyze_version_{contract_id}", None)
        st.session_state.pop("upload_proposal_source", None)

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
        apply_active_contract(contract_id, force=True, reset_source_widgets=True)


def contract_identity_matches(
    contract_name: str,
    client_name: str,
    contract: Contract | None,
) -> bool:
    """True se nome e cliente coincidem com o contrato informado."""
    if not contract:
        return False
    return (
        contract_name.strip().casefold() == contract.name.strip().casefold()
        and client_name.strip().casefold() == contract.client_name.strip().casefold()
    )


def resolve_contract_for_upload(contract_name: str, client_name: str) -> tuple[str, bool]:
    """
    Resolve o contrato alvo do upload.

    Reutiliza o contrato ativo somente se nome e cliente forem iguais.
    Caso contrário, cria um novo contrato (proposta própria, sem herdar a anterior).
    Retorna (contract_id, created_new).
    """
    name = contract_name.strip()
    client = client_name.strip()
    if not name or not client:
        raise ValueError("Informe nome do contrato e do cliente.")

    active = get_active_contract()
    if active and contract_identity_matches(name, client, active):
        return active.id, False

    contract = db.create_contract(name, client, owner_user_id=_owner_user_id())
    st.session_state.active_contract_id = contract.id
    st.session_state._applied_contract_id = contract.id
    for key in (
        "upload_version_id",
        "active_version_id",
        "checklist_version_id",
        "last_matrix_initial_result",
        "last_checklist_result",
    ):
        st.session_state.pop(key, None)
    st.session_state[_UPLOAD_VERSION_LABEL_DEFAULT_KEY] = "Original"
    st.session_state.analysis_contract_mode = "saved"
    st.session_state["upload_contract_source"] = CONTRACT_SOURCE_SAVED
    set_proposal_mode(PROPOSAL_MODE_NONE)
    request_sidebar_contract(contract.id)
    from app.utils.data_cache import clear_data_cache

    clear_data_cache()
    return contract.id, True


def clear_active_contract_context(*, sync_sidebar: bool = True) -> None:
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
        "last_matrix_initial_result",
        "last_checklist_result",
        "upload_proposal_source",
        "upload_saved_contract",
    ):
        st.session_state.pop(key, None)
    st.session_state.analysis_contract_mode = "new"
    st.session_state["upload_contract_source"] = CONTRACT_SOURCE_NEW
    set_proposal_mode(PROPOSAL_MODE_NONE)
    _prepare_upload_version_label("Original")
    if sync_sidebar:
        request_sidebar_contract(None)


def version_option_label(version: ContractVersion) -> str:
    """Rótulo legível para selectbox de versão (número, nome, data e arquivo)."""
    from app.utils.datetime_br import format_brazil_datetime

    when = format_brazil_datetime(version.uploaded_at, "%d/%m/%Y")
    fname = file_basename(version.file_path)
    base = f"v{version.version_number} — {version.label}"
    if fname:
        return f"{base} ({when} · {fname})"
    return f"{base} ({when})"


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


def _on_sidebar_contract_select() -> None:
    lbl = st.session_state.get("sidebar_contract")
    cid = st.session_state.get(SIDEBAR_LABEL_MAP_KEY, {}).get(lbl)
    if not cid:
        clear_active_contract_context(sync_sidebar=False)
        st.session_state["upload_contract_source"] = CONTRACT_SOURCE_NEW
        return
    on_sidebar_contract_changed(cid)
    st.session_state["upload_contract_source"] = CONTRACT_SOURCE_SAVED
    contract = get_active_contract()
    if contract:
        from app.utils.ui import contract_option_label

        st.session_state["upload_saved_contract"] = contract_option_label(contract)


def _on_sidebar_version_select(contract_id: str) -> None:
    key = f"sidebar_active_version_{contract_id}"
    chosen = st.session_state.get(key)
    mapping = st.session_state.get(f"_sidebar_version_map_{contract_id}", {})
    version_id = mapping.get(chosen)
    if version_id:
        set_active_version(version_id)
        page_key = f"upload_analyze_version_{contract_id}"
        if page_key in st.session_state:
            st.session_state[page_key] = chosen


def _on_sidebar_proposal_select(contract_id: str) -> None:
    key = f"sidebar_proposal_mode_{contract_id}"
    chosen = st.session_state.get(key)
    if chosen == PROPOSAL_SOURCE_SAVED:
        set_proposal_mode(PROPOSAL_MODE_SAVED)
    else:
        set_proposal_mode(PROPOSAL_MODE_NONE)
    st.session_state.pop("upload_proposal_source", None)


def render_sidebar_contract_controls() -> None:
    """Selects da sidebar: contrato (com Nenhum), versão e proposta em uso."""
    from app.utils.data_cache import cached_contracts_for_session
    from app.utils.ui import contract_option_label, filter_contracts_by_search

    contracts = cached_contracts_for_session()
    sb_search = st.text_input(
        "Buscar",
        key="sidebar_contract_search",
        placeholder="Contrato ou cliente…",
        label_visibility="collapsed",
    )

    filtered = filter_contracts_by_search(contracts, sb_search) if contracts else []
    active_id = st.session_state.get("active_contract_id")
    if active_id and not any(c.id == active_id for c in filtered):
        active_obj = next((c for c in contracts if c.id == active_id), None)
        if active_obj:
            filtered = [active_obj, *filtered]

    labels = [SIDEBAR_NONE_LABEL]
    ids: list[str | None] = [None]
    for c in filtered:
        labels.append(contract_option_label(c))
        ids.append(c.id)
    label_to_id = dict(zip(labels, ids))
    st.session_state[SIDEBAR_LABEL_MAP_KEY] = label_to_id

    pending = st.session_state.pop(PENDING_SIDEBAR_CONTRACT_KEY, "__absent__")
    if pending != "__absent__":
        if pending is None:
            st.session_state["sidebar_contract"] = SIDEBAR_NONE_LABEL
        else:
            match = next(
                (lbl for lbl, cid in zip(labels, ids) if cid == pending),
                SIDEBAR_NONE_LABEL,
            )
            st.session_state["sidebar_contract"] = match

    if "sidebar_contract" not in st.session_state:
        st.session_state["sidebar_contract"] = SIDEBAR_NONE_LABEL
        if active_id:
            match = next(
                (lbl for lbl, cid in zip(labels, ids) if cid == active_id),
                None,
            )
            if match:
                st.session_state["sidebar_contract"] = match

    current_lbl = st.session_state.get("sidebar_contract")
    if current_lbl not in label_to_id:
        st.session_state["sidebar_contract"] = SIDEBAR_NONE_LABEL
        if active_id:
            match = next(
                (lbl for lbl, cid in zip(labels, ids) if cid == active_id),
                None,
            )
            if match:
                st.session_state["sidebar_contract"] = match

    if not contracts:
        st.caption("Nenhum contrato cadastrado")
        st.selectbox(
            "Contrato em uso",
            [SIDEBAR_NONE_LABEL],
            key="sidebar_contract",
            disabled=True,
        )
        return

    st.selectbox(
        "Contrato em uso",
        labels,
        key="sidebar_contract",
        on_change=_on_sidebar_contract_select,
        help="Escolha um contrato salvo ou «Nenhum» para começar do zero. "
        "O primeiro da lista não é mais aplicado automaticamente.",
    )

    contract = get_active_contract()
    if not contract:
        st.caption("Nenhum contrato em uso. Envie um novo na análise inicial.")
        return

    versions = get_active_versions()
    version = get_active_version()
    if versions:
        vlabels = [version_option_label(v) for v in versions]
        vmap = dict(zip(vlabels, [v.id for v in versions]))
        st.session_state[f"_sidebar_version_map_{contract.id}"] = vmap
        vkey = f"sidebar_active_version_{contract.id}"
        if vkey not in st.session_state:
            idx = version_select_index(
                versions,
                st.session_state.get("upload_version_id"),
                len(versions) - 1,
            )
            st.session_state[vkey] = vlabels[idx]
        elif st.session_state.get(vkey) not in vmap:
            idx = version_select_index(
                versions,
                st.session_state.get("upload_version_id"),
                len(versions) - 1,
            )
            st.session_state[vkey] = vlabels[idx]
        st.selectbox(
            "Versão em uso",
            vlabels,
            key=vkey,
            on_change=_on_sidebar_version_select,
            args=(contract.id,),
            help="Padrão: última versão salva.",
        )
        version = get_active_version() or versions[-1]
    else:
        st.caption("Este contrato ainda não tem versão. Envie o arquivo na página.")

    has_proposal = db.contract_has_proposal(contract)
    if has_proposal:
        pkey = f"sidebar_proposal_mode_{contract.id}"
        p_options = [PROPOSAL_SOURCE_SAVED, PROPOSAL_SOURCE_NONE]
        if pkey not in st.session_state:
            st.session_state[pkey] = (
                PROPOSAL_SOURCE_SAVED
                if get_proposal_mode() == PROPOSAL_MODE_SAVED
                else PROPOSAL_SOURCE_NONE
            )
        elif st.session_state.get(pkey) not in p_options:
            st.session_state[pkey] = p_options[0]
        if get_proposal_mode() == PROPOSAL_MODE_NEW:
            st.caption("Trocando proposta — salve o arquivo na página.")
        else:
            st.selectbox(
                "Proposta em uso",
                p_options,
                key=pkey,
                on_change=_on_sidebar_proposal_select,
                args=(contract.id,),
                help="Uma proposta por contrato. Enviar outra substitui a atual após salvar.",
            )
    else:
        if get_proposal_mode() == PROPOSAL_MODE_NEW:
            st.caption("Nova proposta — salve o arquivo na página.")
        else:
            st.caption("Sem proposta cadastrada")

    _render_sidebar_context_card(contract, version, has_proposal)


def _render_sidebar_context_card(
    contract: Contract,
    version: ContractVersion | None,
    has_proposal: bool,
) -> None:
    ver_txt = "sem versão"
    if version:
        fname = file_basename(version.file_path)
        ver_txt = f"v{version.version_number} — {html.escape(version.label)}"
        if fname:
            ver_txt += f" · {html.escape(fname)}"

    mode = get_proposal_mode()
    if mode == PROPOSAL_MODE_NEW:
        prop_txt = "nova proposta (salvar na página)"
    elif mode == PROPOSAL_MODE_SAVED and has_proposal:
        prop_txt = html.escape(contract.proposal_label or "Proposta comercial")
        pfn = file_basename(contract.proposal_file_path)
        if pfn:
            prop_txt += f" · {html.escape(pfn)}"
    else:
        prop_txt = "sem proposta"

    st.markdown(
        f"""
        <div class="ca-sidebar-context">
            <div class="kicker">Em uso nesta sessão</div>
            <div class="title">{html.escape(contract.name)}</div>
            <div class="meta">{html.escape(contract.client_name)}</div>
            <div class="row"><span>Versão</span>{ver_txt}</div>
            <div class="row"><span>Proposta</span>{prop_txt}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_analysis_context_card() -> None:
    """Card da análise inicial: deixa explícito se o arquivo é salvo ou novo."""
    contract = get_active_contract()
    version = get_active_version()
    contract_mode = st.session_state.get("analysis_contract_mode", "new")
    proposal_mode = get_proposal_mode()

    if contract_mode == "new" and not contract:
        st.markdown(
            """
            <div class="ca-source-card is-new">
                <div class="ca-source-head">
                    <span class="ca-pill ca-pill-new">Novo envio</span>
                    <strong>Nenhum contrato salvo em uso</strong>
                </div>
                <p>Envie um PDF/DOCX, informe nome e cliente e salve para criar o contrato.
                A análise só roda depois que a versão estiver salva.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    if not contract:
        return

    ver_label = "Nenhuma versão salva ainda"
    ver_file = ""
    if version:
        ver_label = f"v{version.version_number} — {version.label}"
        ver_file = file_basename(version.file_path)

    has_proposal = db.contract_has_proposal(contract)
    if proposal_mode == PROPOSAL_MODE_NEW:
        prop_status = "nova"
        prop_label = "Enviar e salvar uma nova proposta (substitui a atual)"
        prop_file = ""
    elif proposal_mode == PROPOSAL_MODE_SAVED and has_proposal:
        prop_status = "salva"
        prop_label = contract.proposal_label or "Proposta comercial"
        prop_file = file_basename(contract.proposal_file_path)
    else:
        prop_status = "nenhuma"
        prop_label = "Esta análise não consulta proposta"
        prop_file = ""

    contract_pill = "salvo" if contract_mode == "saved" else "novo"
    version_pill = "salva" if version else "pendente"

    def _row(kind: str, title: str, detail: str, extra: str = "") -> str:
        extra_html = f'<span class="ca-source-file">{html.escape(extra)}</span>' if extra else ""
        return (
            f'<div class="ca-source-row">'
            f'<span class="ca-pill ca-pill-{kind}">{html.escape(title)}</span>'
            f'<div><strong>{html.escape(detail)}</strong>{extra_html}</div>'
            f"</div>"
        )

    st.markdown(
        f"""
        <div class="ca-source-card is-{html.escape(contract_pill)}">
            <div class="ca-source-head">
                <span class="ca-pill ca-pill-{contract_pill}">Arquivos em uso</span>
                <strong>{html.escape(contract.name)}</strong>
                <span class="ca-source-client">{html.escape(contract.client_name)}</span>
            </div>
            {_row(version_pill, f"Contrato {version_pill}", ver_label, ver_file)}
            {_row(prop_status, f"Proposta {prop_status}", prop_label, prop_file)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_active_contract_banner(
    *,
    context: str = "upload",
    show_versions: bool = True,
) -> None:
    """Exibe resumo do contrato ativo. Na análise inicial usa o card de origem."""
    if context == "upload":
        render_analysis_context_card()
        return

    contract = get_active_contract()
    if not contract:
        return

    versions = get_active_versions()
    proposal_note = ""
    if db.contract_has_proposal(contract):
        proposal_note = f" · {contract.proposal_label}"
    elif context == "upload":
        proposal_note = " · sem proposta"

    ver_line = ""
    if show_versions and versions:
        latest = versions[-1]
        ver_line = f" · v{latest.version_number} — {latest.label} ({len(versions)} versões)"

    st.caption(
        f"**Ativo:** {contract.name} ({contract.client_name}){proposal_note}{ver_line}"
    )
