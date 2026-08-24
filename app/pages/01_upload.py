"""Upload de contrato + análise inicial pela matriz de parâmetros."""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from app.utils.dev_reload import sync_app_modules

sync_app_modules(st.session_state)

from loguru import logger

from app.core import extractor, matrix_checker
from app.core.document_locator import find_in_document
from app.db import database as db
from app.models.schemas import ChangeRisk, ContractMatrixInitialResult, MatrixParameterCheck
from app.utils.helpers import count_tokens
from app.utils.document_ui import render_document_navigator
from app.utils.inline_comments_ui import (
    mark_comment_queue_for_rebuild,
    render_inline_comments_workspace,
)
from app.utils.matrix_ui import render_matrix_editor
from app.utils.settings import get_settings
from app.utils.data_cache import cached_contracts_for_session, clear_data_cache
from app.utils.theme import page_header, render_page_footer, section_title, setup_page
from app.utils.active_contract import (
    CONTRACT_SOURCE_NEW,
    CONTRACT_SOURCE_SAVED,
    PROPOSAL_MODE_NEW,
    PROPOSAL_MODE_NONE,
    PROPOSAL_MODE_SAVED,
    PROPOSAL_SOURCE_NEW,
    PROPOSAL_SOURCE_NONE,
    PROPOSAL_SOURCE_SAVED,
    clear_active_contract_context,
    file_basename,
    get_active_contract,
    get_active_versions,
    get_proposal_for_analysis,
    get_proposal_mode,
    init_upload_version_label_widget,
    on_sidebar_contract_changed,
    proposal_requires_save,
    render_active_contract_banner,
    request_sidebar_contract,
    resolve_contract_for_upload,
    set_active_version,
    set_proposal_mode,
    version_option_label,
    version_select_index,
)
from app.utils.analysis_session import (
    clear_matrix_initial_analysis_results,
    matrix_analysis_matches_version,
    set_matrix_analysis_token,
)
from app.utils.ui import contract_option_label, render_upload_format_notice, save_uploaded_file

setup_page("Upload & Análise")
settings = get_settings()

page_header(
    "Upload & Análise inicial",
    "Escolha um contrato e uma proposta já salvos, ou envie arquivos novos. "
    "A análise só usa o que estiver selecionado abaixo.",
)

init_upload_version_label_widget()

RISK_ICON = {ChangeRisk.HIGH: "🔴", ChangeRisk.MEDIUM: "🟡", ChangeRisk.LOW: "🟢"}


def _render_matrix_check(check: MatrixParameterCheck) -> None:
    icon = "✅" if check.present else "❌"
    risk = RISK_ICON.get(check.risk_level, "")
    with st.expander(f"{icon} {check.categoria} {risk}", expanded=not check.present):
        st.caption(check.parametro_verificacao)
        st.write(check.observation)
        if check.found_excerpt:
            st.code(check.found_excerpt)
        if check.proposal_excerpt:
            st.caption("Na proposta:")
            st.code(check.proposal_excerpt)
        if check.aligns_with_proposal is False:
            st.warning("Desalinhado com a proposta.")


def _render_matrix_summary(result: ContractMatrixInitialResult) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Atendidos", f"{result.items_met}/{result.total_items}")
    c2.metric("Score", f"{result.overall_score:.0%}")
    c3.metric("Alertas", len(result.risk_alerts))
    if result.proposal_used:
        st.caption(f"Proposta consultada: **{result.proposal_label or 'Proposta comercial'}**")
    else:
        st.caption("Análise sem consulta à proposta.")
    if result.executive_summary:
        st.info(result.executive_summary)
    if result.risk_alerts:
        for alert in result.risk_alerts:
            st.warning(alert)
    if result.critical_gaps:
        st.error("Lacunas críticas:\n- " + "\n- ".join(result.critical_gaps))


def _on_contract_source_change() -> None:
    choice = st.session_state.get("upload_contract_source")
    if choice == CONTRACT_SOURCE_NEW:
        clear_active_contract_context()
        st.session_state["upload_contract_source"] = CONTRACT_SOURCE_NEW
        return
    st.session_state.analysis_contract_mode = "saved"


def _on_saved_contract_pick() -> None:
    label = st.session_state.get("upload_saved_contract")
    cid = st.session_state.get("_upload_saved_contract_map", {}).get(label)
    if not cid:
        return
    on_sidebar_contract_changed(cid)
    request_sidebar_contract(cid)
    st.session_state.sidebar_contract_search = ""


def _on_page_version_change(contract_id: str) -> None:
    key = f"upload_analyze_version_{contract_id}"
    chosen = st.session_state.get(key)
    version_id = st.session_state.get(f"_upload_version_map_{contract_id}", {}).get(chosen)
    if version_id:
        set_active_version(version_id)
        sidebar_key = f"sidebar_active_version_{contract_id}"
        st.session_state[sidebar_key] = chosen


def _on_proposal_source_change() -> None:
    choice = st.session_state.get("upload_proposal_source")
    if choice == PROPOSAL_SOURCE_SAVED:
        set_proposal_mode(PROPOSAL_MODE_SAVED)
    elif choice == PROPOSAL_SOURCE_NEW:
        set_proposal_mode(PROPOSAL_MODE_NEW)
    else:
        set_proposal_mode(PROPOSAL_MODE_NONE)


def _persist_new_version(uploaded, contract_id: str, version_label: str):
    path = save_uploaded_file(uploaded, settings.contracts_path)
    text, doc_type = extractor.extract_text(path)
    version = db.add_version(contract_id, version_label, path, doc_type, text)
    clear_data_cache()
    st.session_state.active_version_id = version.id
    st.session_state.upload_version_id = version.id
    st.session_state["upload_version_label_default"] = f"Revisão v{version.version_number + 1}"
    st.session_state.pop(f"upload_analyze_version_{contract_id}", None)
    st.session_state.pop(f"sidebar_active_version_{contract_id}", None)
    return version


def _render_new_contract_upload() -> None:
    st.caption("Cria um contrato novo. Nome e cliente não herdam o que estava na barra lateral.")
    render_upload_format_notice()
    uploaded = st.file_uploader(
        "Arquivo do contrato (PDF ou DOCX — não .doc)",
        type=["pdf", "docx"],
        key="upload_contract_file",
        help="Aceita apenas .pdf e .docx. Arquivos .doc devem ser convertidos para .docx.",
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        contract_name = st.text_input("Nome do contrato", key="upload_contract_name")
    with col2:
        client_name = st.text_input("Nome do cliente", key="upload_client_name")
    with col3:
        version_label = st.text_input("Label da versão", key="upload_version_label")

    if uploaded and contract_name and client_name:
        if st.button("Salvar contrato", type="primary", key="upload_save_contract"):
            try:
                with st.spinner("Extraindo texto..."):
                    contract_id, created_new = resolve_contract_for_upload(
                        contract_name, client_name
                    )
                    version = _persist_new_version(uploaded, contract_id, version_label)
                if created_new:
                    st.success(
                        f"Contrato **{contract_name}** criado — v{version.version_number} salva."
                    )
                else:
                    st.success(f"Versão v{version.version_number} salva.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                logger.exception("Erro no upload")
                msg = str(exc)
                if "session_state" in msg and "upload_version_label" in msg:
                    st.error(
                        "Conflito interno do formulário. Atualize a página (F5) e tente novamente."
                    )
                elif "getvalue" in msg.lower() or "uploadedfile" in msg.lower():
                    st.error(
                        "Arquivo não disponível. Selecione o PDF/DOCX novamente e clique em Salvar."
                    )
                else:
                    st.error(f"Arquivo corrompido ou ilegível: {exc}")
    elif not uploaded:
        st.caption("Selecione o arquivo e preencha nome e cliente para salvar.")


def _render_add_version_form(contract) -> None:
    render_upload_format_notice()
    uploaded = st.file_uploader(
        "Nova versão (PDF ou DOCX — não .doc)",
        type=["pdf", "docx"],
        key=f"upload_add_version_file_{contract.id}",
        help="O arquivo vira uma nova versão deste contrato. Nome e cliente permanecem os mesmos.",
    )
    version_label = st.text_input(
        "Label da nova versão",
        key="upload_version_label",
    )
    if uploaded and st.button("Salvar nova versão", type="primary", key="upload_save_added_version"):
        try:
            with st.spinner("Extraindo texto..."):
                version = _persist_new_version(uploaded, contract.id, version_label)
            st.success(f"Versão v{version.version_number} salva e selecionada para análise.")
            st.rerun()
        except Exception as exc:
            logger.exception("Erro no upload da versão")
            st.error(str(exc))


def _render_saved_contract_panel() -> None:
    contracts = cached_contracts_for_session()
    if not contracts:
        st.info("Nenhum contrato cadastrado. Use **Enviar um novo agora**.")
        return

    placeholder = "Selecione um contrato…"
    labels = [placeholder]
    ids: list[str | None] = [None]
    for rec in contracts:
        labels.append(contract_option_label(rec))
        ids.append(rec.id)
    mapping = dict(zip(labels, ids))
    st.session_state["_upload_saved_contract_map"] = mapping

    active = get_active_contract()
    if "upload_saved_contract" not in st.session_state:
        st.session_state.upload_saved_contract = (
            contract_option_label(active) if active else placeholder
        )
    elif st.session_state.upload_saved_contract not in mapping:
        st.session_state.upload_saved_contract = (
            contract_option_label(active) if active else placeholder
        )

    st.selectbox(
        "Contrato salvo",
        labels,
        key="upload_saved_contract",
        on_change=_on_saved_contract_pick,
        help="Nome e cliente ficam travados. Para outro cliente, envie um contrato novo.",
    )

    contract = get_active_contract()
    if not contract:
        st.warning("Escolha um contrato neste select ou na barra lateral.")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.text_input(
            "Nome do contrato",
            value=contract.name,
            disabled=True,
            key=f"locked_contract_name_{contract.id}",
        )
    with c2:
        st.text_input(
            "Nome do cliente",
            value=contract.client_name,
            disabled=True,
            key=f"locked_client_name_{contract.id}",
        )

    versions = get_active_versions()
    if versions:
        vlabels = [version_option_label(v) for v in versions]
        vmap = {lbl: v.id for lbl, v in zip(vlabels, versions)}
        st.session_state[f"_upload_version_map_{contract.id}"] = vmap
        vkey = f"upload_analyze_version_{contract.id}"
        if vkey not in st.session_state or st.session_state.get(vkey) not in vmap:
            idx = version_select_index(
                versions,
                st.session_state.get("upload_version_id"),
                len(versions) - 1,
            )
            st.session_state[vkey] = vlabels[idx]
        st.selectbox(
            "Versão para analisar",
            vlabels,
            key=vkey,
            on_change=_on_page_version_change,
            args=(contract.id,),
            help="A última versão vem selecionada por padrão.",
        )
    else:
        st.warning("Este contrato ainda não tem arquivo. Adicione a primeira versão abaixo.")

    with st.expander("Adicionar nova versão a este contrato", expanded=not versions):
        _render_add_version_form(contract)


def _render_contract_section() -> None:
    if "upload_contract_source" not in st.session_state:
        st.session_state.upload_contract_source = (
            CONTRACT_SOURCE_SAVED
            if st.session_state.get("active_contract_id")
            else CONTRACT_SOURCE_NEW
        )

    source = st.radio(
        "Origem do contrato",
        [CONTRACT_SOURCE_SAVED, CONTRACT_SOURCE_NEW],
        horizontal=True,
        key="upload_contract_source",
        on_change=_on_contract_source_change,
        help="Salvo: escolhe um cadastro existente. Novo: cria outro contrato.",
    )
    st.session_state.analysis_contract_mode = (
        "saved" if source == CONTRACT_SOURCE_SAVED else "new"
    )
    if source == CONTRACT_SOURCE_SAVED:
        _render_saved_contract_panel()
    else:
        _render_new_contract_upload()


def _render_proposal_section() -> None:
    contract = get_active_contract()
    if not contract:
        st.caption("Salve ou escolha um contrato para vincular a proposta.")
        return

    has_proposal = db.contract_has_proposal(contract)
    options = []
    if has_proposal:
        options.append(PROPOSAL_SOURCE_SAVED)
    options.extend([PROPOSAL_SOURCE_NEW, PROPOSAL_SOURCE_NONE])

    pending = st.session_state.pop("_pending_proposal_source", None)
    if pending and pending in options:
        st.session_state.upload_proposal_source = pending

    if "upload_proposal_source" not in st.session_state:
        mode = get_proposal_mode()
        if mode == PROPOSAL_MODE_SAVED and has_proposal:
            st.session_state.upload_proposal_source = PROPOSAL_SOURCE_SAVED
        elif mode == PROPOSAL_MODE_NEW:
            st.session_state.upload_proposal_source = PROPOSAL_SOURCE_NEW
        else:
            st.session_state.upload_proposal_source = PROPOSAL_SOURCE_NONE
    elif st.session_state.upload_proposal_source not in options:
        st.session_state.upload_proposal_source = options[0]

    chosen = st.selectbox(
        "Origem da proposta",
        options,
        key="upload_proposal_source",
        on_change=_on_proposal_source_change,
        help="Uma proposta por contrato. Enviar outra e salvar substitui a atual. "
        "A análise não usa arquivo que ainda não foi salvo.",
    )
    if chosen == PROPOSAL_SOURCE_SAVED:
        set_proposal_mode(PROPOSAL_MODE_SAVED)
    elif chosen == PROPOSAL_SOURCE_NEW:
        set_proposal_mode(PROPOSAL_MODE_NEW)
    else:
        set_proposal_mode(PROPOSAL_MODE_NONE)

    if chosen == PROPOSAL_SOURCE_SAVED:
        st.success(f"Usando a proposta salva: **{contract.proposal_label}**")
        pfn = file_basename(contract.proposal_file_path)
        if pfn:
            st.caption(f"Arquivo salvo: `{pfn}`")
        if contract.proposal_file_path:
            try:
                with open(contract.proposal_file_path, "rb") as pf:
                    st.download_button(
                        "Baixar proposta salva",
                        pf.read(),
                        file_name=Path(contract.proposal_file_path).name,
                        key=f"dl_proposal_{contract.id}",
                    )
            except OSError:
                st.caption("Arquivo da proposta não está acessível no disco.")
        return

    if chosen == PROPOSAL_SOURCE_NONE:
        st.info(
            "A análise usará **somente a matriz** no texto do contrato, "
            "mesmo que exista uma proposta cadastrada."
        )
        return

    if has_proposal:
        st.warning(
            f"A proposta atual (**{contract.proposal_label}**) só será substituída "
            "depois que você salvar o novo arquivo."
        )
    else:
        st.info("Salve a proposta para ela entrar nesta análise. Sem salvar, a análise segue só com a matriz.")

    render_upload_format_notice()
    prop_file = st.file_uploader(
        "Arquivo da nova proposta (PDF ou DOCX — não .doc)",
        type=["pdf", "docx"],
        key=f"upload_proposal_file_{contract.id}",
        help="Aceita apenas .pdf e .docx. É preciso salvar para a análise usar este arquivo.",
    )
    prop_label = st.text_input(
        "Label da proposta",
        value=contract.proposal_label if contract.proposal_label else "Proposta comercial",
        key=f"upload_proposal_label_{contract.id}",
    )
    if prop_file and st.button("Salvar proposta", type="primary", key=f"save_proposal_{contract.id}"):
        try:
            with st.spinner("Extraindo proposta..."):
                ppath = save_uploaded_file(prop_file, settings.contracts_path)
                ptext, ptype = extractor.extract_text(ppath)
            db.set_contract_proposal(
                contract.id,
                ppath,
                ptype.value,
                ptext,
                prop_label,
            )
            clear_data_cache()
            set_proposal_mode(PROPOSAL_MODE_SAVED)
            st.session_state["_pending_proposal_source"] = PROPOSAL_SOURCE_SAVED
            st.session_state[f"sidebar_proposal_mode_{contract.id}"] = PROPOSAL_SOURCE_SAVED
            st.success("Proposta salva e selecionada para a análise. A anterior deste contrato foi substituída.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    elif not prop_file:
        st.caption("Selecione o arquivo e clique em **Salvar proposta** para usá-lo.")


def _render_analysis_plan(version_id: str | None, matrix_items: list[dict]) -> None:
    ver = db.get_version(version_id) if version_id else None
    contract = get_active_contract()
    if ver and not contract:
        contract = db.get_contract(ver.contract_id)

    lines = []
    if contract and ver:
        lines.append(f"**Contrato salvo:** {contract.name} · {contract.client_name}")
        lines.append(f"**Versão:** {version_option_label(ver)}")
    elif st.session_state.get("analysis_contract_mode") == "new":
        lines.append("**Contrato:** novo envio — salve o arquivo antes de analisar.")
    else:
        lines.append("**Contrato:** nenhum selecionado.")

    if proposal_requires_save():
        lines.append("**Proposta:** nova — **salve** o arquivo. A proposta anterior não será usada.")
    elif contract:
        _text, label, used = get_proposal_for_analysis(contract)
        if used:
            pfn = file_basename(contract.proposal_file_path)
            extra = f" · `{pfn}`" if pfn else ""
            lines.append(f"**Proposta salva:** {label}{extra}")
        else:
            lines.append("**Proposta:** não será consultada.")
    else:
        lines.append("**Proposta:** —")

    if matrix_items:
        lines.append(f"**Matriz:** {len(matrix_items)} parâmetro(s)")
    else:
        lines.append("**Matriz:** configure ao menos um parâmetro.")

    st.markdown("\n\n".join(f"- {line}" for line in lines))


def _render_matrix_section() -> list[dict]:
    return render_matrix_editor(
        section_label="Parâmetros de verificação",
        template_key="upload_matrix_template_choice",
        new_name_key="upload_matrix_new_name",
        new_rows_key="upload_matrix_new_rows",
        new_editor_key="upload_matrix_new_editor",
        save_new_key="upload_matrix_save_new",
    )


def _load_matrix_items() -> list[dict]:
    items = _render_matrix_section()
    if items:
        st.session_state["_upload_matrix_items"] = items
        return items
    return st.session_state.get("_upload_matrix_items", [])


section_title("1. Contrato")
_render_contract_section()

version_id = st.session_state.get("upload_version_id")
active_ver = db.get_version(version_id) if version_id else None
if active_ver and st.session_state.get("active_contract_id"):
    if active_ver.contract_id != st.session_state.active_contract_id:
        version_id = None
        st.session_state.pop("upload_version_id", None)

section_title("2. Proposta comercial")
st.caption(
    "Escolha a proposta salva deste contrato, envie outra (salvar substitui) "
    "ou analise só com a matriz."
)
_render_proposal_section()

render_active_contract_banner(context="upload")

section_title("3. Matriz de parâmetros")
matrix_items = _load_matrix_items()

section_title("4. Analisar")
_render_analysis_plan(version_id, matrix_items)

can_analyze = bool(version_id) and len(matrix_items) > 0
if proposal_requires_save():
    can_analyze = False
    st.warning(
        "Salve a nova proposta para a análise usá-la. "
        "Enquanto esta opção estiver selecionada, a proposta anterior **não** entra na análise."
    )

if can_analyze:
    ver = db.get_version(version_id)
    if ver:
        token_est = count_tokens(ver.extracted_text)
        if token_est > 50000:
            st.warning(f"Contrato grande (~{token_est:,} tokens) — análise pode levar vários minutos.")

if st.button("Analisar contrato", type="primary", disabled=not can_analyze):
    clear_matrix_initial_analysis_results()
    ver = db.get_version(version_id)
    try:
        contract_rec = db.get_contract(ver.contract_id)
        proposal_text, proposal_label, _proposal_used = get_proposal_for_analysis(contract_rec)

        total_items = len(matrix_items)
        section_title("Resultado")
        st.caption(f"Analisando **{total_items}** parâmetros — cada tópico aparece assim que ficar pronto.")

        progress_bar = st.progress(0.0, text="Iniciando...")
        status = st.empty()
        metrics_ph = st.empty()
        checks_ph = st.empty()
        completed: list[MatrixParameterCheck] = []

        def _on_progress(current: int, total: int, label: str) -> None:
            pct = (current - 1) / total if total else 0.0
            progress_bar.progress(
                max(0.0, pct),
                text=f"Analisando {current}/{total}…",
            )
            status.caption(f"Em análise: **{label}**")

        def _on_item_done(check: MatrixParameterCheck, current: int, total: int) -> None:
            if check.found_excerpt:
                check.locations = find_in_document(ver.file_path, check.found_excerpt)
            completed.append(check)
            met = sum(1 for c in completed if c.present)
            progress_bar.progress(
                current / total if total else 1.0,
                text=f"{current}/{total} prontos",
            )
            status.success(f"Pronto ({current}/{total}): **{check.categoria}**")
            with metrics_ph.container():
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Atendidos", f"{met}/{total}")
                mc2.metric("Concluídos", f"{current}/{total}")
                mc3.metric("Pendentes", total - current)
            with checks_ph.container():
                st.markdown("**Parâmetros verificados**")
                for done in completed:
                    _render_matrix_check(done)

        result = matrix_checker.check_matrix_against_contract(
            ver.extracted_text,
            matrix_items,
            ver.contract_id,
            proposal_text=proposal_text or None,
            proposal_label=proposal_label,
            progress_callback=_on_progress,
            item_complete_callback=_on_item_done,
        )

        progress_bar.progress(1.0, text="Análise concluída.")
        status.empty()

        db.save_analysis_result(version_id, "matrix_initial", result)
        clear_data_cache()
        st.session_state.last_matrix_initial_result = result
        st.session_state.checklist_version_id = version_id
        set_matrix_analysis_token(version_id)
        st.session_state.matrix_analysis_saved = True
        mark_comment_queue_for_rebuild(version_id, "upload_mtx")
        st.success("Análise concluída e salva no **Histórico**.")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        logger.exception("Erro na análise")
        st.warning(f"Erro na análise: {exc}. Tente novamente.")

matrix_result: ContractMatrixInitialResult | None = None
if matrix_analysis_matches_version(version_id):
    matrix_result = st.session_state.get("last_matrix_initial_result")
if matrix_result:
    section_title("Resultado")
    if st.session_state.pop("matrix_analysis_saved", False):
        st.caption("Última análise salva automaticamente no Histórico.")
    _render_matrix_summary(matrix_result)

    ver = db.get_version(st.session_state.get("checklist_version_id") or version_id)
    tab_res, tab_doc = st.tabs(["Parâmetros", "Documento"])
    with tab_res:
        for check in matrix_result.checks:
            _render_matrix_check(check)

    with tab_doc:
        if ver:
            all_locs = [loc for check in matrix_result.checks for loc in check.locations]
            if all_locs:
                render_document_navigator(
                    ver.file_path, ver.file_type, excerpt_locations=all_locs, key_prefix="mtx_ini"
                )
            else:
                st.info("Nenhum trecho localizado no documento.")

    if ver:
        render_inline_comments_workspace(
            ver,
            matrix_checks=matrix_result.checks,
            key_prefix="upload_mtx",
            rebuild_queue=False,
        )

elif not can_analyze:
    st.caption("Salve o contrato, defina a proposta (ou analise sem ela) e configure ao menos um parâmetro na matriz.")

render_page_footer()
