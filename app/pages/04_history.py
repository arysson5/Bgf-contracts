"""Histórico de análises por cliente/contrato."""

import streamlit as st

from app.db import database as db
from app.models.schemas import (
    CommentsReviewResult,
    CommentStatus,
    ContractChecklistResult,
    ContractDiffResult,
)
from app.utils.datetime_br import format_brazil_datetime
from app.utils.document_ui import render_document_navigator
from app.utils.pdf_ui import show_pdf
from app.utils.theme import page_header, setup_page
from app.utils.ui import render_contract_selector

setup_page("Histórico de Análises", page_icon="📚")

page_header("Histórico de Análises", "Consulte e recarregue análises anteriores por contrato.")

contracts = db.get_contracts()
if not contracts:
    st.info("Nenhum contrato cadastrado.")
    st.stop()

clients = sorted({c.client_name for c in contracts})
filter_client = st.selectbox("Filtrar por cliente", ["Todos"] + clients)

contract_id = render_contract_selector("history_contract")
if not contract_id:
    st.stop()

contract = db.get_contract(contract_id)
analyses = db.get_analyses_for_contract(contract_id)
if not analyses:
    st.warning("Nenhuma análise salva.")
    st.stop()

type_labels = {"checklist": "Checklist", "diff": "Análise contratual", "comments": "Comentários"}
options = [
    f"{format_brazil_datetime(rec.created_at)} — {type_labels.get(rec.analysis_type, rec.analysis_type)} (v{ver.version_number} {ver.label})"
    for rec, ver in analyses
]
selected = st.selectbox("Análise", options)
idx = options.index(selected)
record, version = analyses[idx]

if st.button("Carregar na sessão", type="primary"):
    data = db.load_analysis_json(record)
    if record.analysis_type == "checklist":
        st.session_state.last_checklist_result = ContractChecklistResult.model_validate(data)
    elif record.analysis_type == "diff":
        st.session_state.last_diff_result = ContractDiffResult.from_stored(data)
    elif record.analysis_type == "comments":
        st.session_state.last_comments_result = CommentsReviewResult.model_validate(data)
        p = data.get("annotated_file_path") or data.get("annotated_pdf_path")
        if p:
            st.session_state.annotated_file_path = p
    st.success("Carregado.")

st.divider()
data = db.load_analysis_json(record)

if record.analysis_type == "checklist":
    result = ContractChecklistResult.model_validate(data)
    st.metric("Score", f"{result.requirements_met}/{result.total_requirements}")
    st.progress(result.overall_score)
    for check in result.checks:
        with st.expander(f"{'✅' if check.present else '❌'} {check.requirement_text}"):
            st.write(check.observation)
            if check.locations:
                render_document_navigator(
                    version.file_path, version.file_type,
                    excerpt_locations=check.locations,
                    key_prefix=f"hist_{check.requirement_id}",
                )

elif record.analysis_type == "diff":
    result = ContractDiffResult.from_stored(data)
    if "contractual_changes" not in data:
        st.warning(
            "Esta análise foi salva no formato antigo (diff textual). "
            "Os trechos abaixo foram convertidos para visualização. "
            "Para análise jurídica completa, execute uma nova comparação."
        )
    summary = result.executive_summary or result.summary
    st.info(summary)
    if result.recommendation:
        st.success(result.recommendation)
    st.metric("Alterações materiais", result.material_changes_count)
    st.metric("Alto risco", result.high_risk_count)

    for ch in result.contractual_changes or []:
        with st.expander(f"{ch.clause_reference} — {ch.title}"):
            st.write(ch.description)
            st.caption(f"Risco: {ch.risk_level} | {ch.legal_impact}")

    versions = db.get_versions(contract_id)
    base_v = versions[0] if versions else version
    if result.contractual_changes:
        t1, t2 = st.tabs([f"Doc: {version.label}", f"Doc: {base_v.label}"])
        with t1:
            render_document_navigator(
                version.file_path, version.file_type,
                result.contractual_changes, version_side="new",
                key_prefix=f"hist_dn_{record.id}",
            )
        with t2:
            render_document_navigator(
                base_v.file_path, base_v.file_type,
                result.contractual_changes, version_side="base",
                key_prefix=f"hist_db_{record.id}",
            )

elif record.analysis_type == "comments":
    result = CommentsReviewResult.model_validate(data)
    st.info(result.admin_summary)
    for rev in result.reviews:
        st.write(f"**{rev.status.value}** — {rev.original_comment}")
        st.code(rev.suggested_response)
    path = result.annotated_file_path or getattr(result, "annotated_pdf_path", None)
    if path:
        if version.file_type == "pdf":
            show_pdf(path, height=500, key=f"hist_c_{record.id}")
        else:
            from app.core.docx_viewer import render_docx_paragraphs_html
            st.markdown(render_docx_paragraphs_html(path), unsafe_allow_html=True)
