"""Revisão de comentários — PDF e DOCX."""

import shutil
from pathlib import Path

import streamlit as st
from loguru import logger

from app.core import differ, extractor, reviewer
from app.core.document_annotator import add_comment_to_document
from app.core.document_locator import find_in_document
from app.db import database as db
from app.models.schemas import CommentStatus, CommentsReviewResult
from app.utils.document_ui import render_document_navigator
from app.utils.pdf_ui import show_pdf
from app.utils.settings import get_settings
from app.utils.data_cache import clear_data_cache
from app.utils.theme import page_header, section_title, setup_page
from app.utils.ui import render_contract_selector, save_uploaded_file

setup_page("Revisar Comentários", page_icon="💬")
settings = get_settings()

STATUS_BADGE = {
    CommentStatus.ATTENDED: "✅ ATENDIDO",
    CommentStatus.PARTIALLY: "⚠️ PARCIAL",
    CommentStatus.NOT_ATTENDED: "❌ NÃO ATENDIDO",
}

page_header(
    "Revisar Comentários",
    "PDF ou DOCX — verifique atendimento e insira comentários aprovados no documento.",
)

contract_id = render_contract_selector("comments_contract")
if not contract_id:
    st.stop()

versions = db.get_versions(contract_id)
if not versions:
    st.warning("Cadastre versões do contrato primeiro.")
    st.stop()

section_title("1. Setup")
annotated_file = st.file_uploader(
    "Arquivo com comentários do admin (PDF ou DOCX)", type=["pdf", "docx"]
)
version_labels = [f"v{v.version_number} — {v.label}" for v in versions]
new_lbl = st.selectbox("Versão nova do cliente", version_labels, index=min(1, len(versions) - 1))
new_version = versions[version_labels.index(new_lbl)]
target_path = new_version.file_path
target_type = new_version.file_type

if annotated_file and st.button("Extrair comentários"):
    try:
        with st.spinner("Extraindo anotações..."):
            path = save_uploaded_file(annotated_file, settings.contracts_path)
            comments = extractor.extract_comments(path)
        st.session_state.extracted_comments = comments
        st.success(f"{len(comments)} comentário(s) extraído(s).") if comments else st.warning("Nenhum comentário nativo encontrado.")
    except Exception as exc:
        st.error(str(exc))

comments = st.session_state.extracted_comments
if comments:
    st.dataframe(
        [{"Página/¶": c.get("page"), "Comentário": c["comment_text"][:200]} for c in comments],
        use_container_width=True,
    )

    original_version = versions[0]
    if st.button("Revisar todos os comentários", type="primary"):
        try:
            with st.spinner("Análise contratual e revisão de comentários..."):
                diff_result = differ.compare_versions(
                    original_version.extracted_text,
                    new_version.extracted_text,
                    original_version.label,
                    new_version.label,
                    contract_id,
                    path_a=original_version.file_path,
                    path_b=new_version.file_path,
                )
                review_result = reviewer.review_comments(
                    comments,
                    original_version.extracted_text,
                    new_version.extracted_text,
                    diff_result,
                    contract_id,
                )
                for rev in review_result.reviews:
                    anchor = rev.referenced_excerpt or rev.change_found or rev.original_comment
                    rev.locations = find_in_document(target_path, anchor or "")
                ext = Path(target_path).suffix
                out = Path(target_path).parent / f"{Path(target_path).stem}_revisao_admin{ext}"
                shutil.copy2(target_path, out)
                st.session_state.annotated_file_path = str(out)
                review_result.annotated_file_path = str(out)
                st.session_state.last_comments_result = review_result
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            logger.exception("Revisão falhou")
            st.warning(f"Erro: {exc}")

result: CommentsReviewResult | None = st.session_state.last_comments_result
if result:
    section_title("2. Resultado")
    c1, c2, c3 = st.columns(3)
    c1.metric("Atendidos", result.attended)
    c2.metric("Parcialmente", result.partially)
    c3.metric("Não atendidos", result.not_attended)
    st.info(result.admin_summary)

    work_path = st.session_state.get("annotated_file_path") or result.annotated_file_path

    for idx, rev in enumerate(result.reviews):
        st.subheader(STATUS_BADGE.get(rev.status, rev.status.value))
        st.write("**Comentário:**", rev.original_comment)
        st.write("**Justificativa:**", rev.justification)
        edited = st.text_area("Sugestão (edite antes de aprovar)", rev.suggested_response, key=f"s_{rev.comment_id}", height=90)

        if st.button("✅ Aprovar e inserir no documento", key=f"ap_{rev.comment_id}", disabled=not work_path or rev.comment_approved):
            try:
                work_path = add_comment_to_document(
                    work_path, edited,
                    anchor_text=rev.referenced_excerpt or rev.change_found,
                    locations=rev.locations,
                    output_path=work_path,
                )
                st.session_state.annotated_file_path = work_path
                result.annotated_file_path = work_path
                rev.comment_approved = True
                st.session_state.last_comments_result = result
                st.success("Comentário inserido.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        if rev.locations:
            with st.expander("Ver no documento"):
                render_document_navigator(target_path, target_type, excerpt_locations=rev.locations, key_prefix=f"cmt_{idx}")

    if work_path and Path(work_path).exists():
        st.subheader("Documento anotado")
        if target_type == "pdf":
            show_pdf(work_path, height=600, key="cmt_final_pdf")
        else:
            from app.core.docx_viewer import render_docx_paragraphs_html
            st.markdown(render_docx_paragraphs_html(work_path), unsafe_allow_html=True)
        with open(work_path, "rb") as f:
            st.download_button("⬇️ Baixar", f.read(), file_name=Path(work_path).name)

    if st.button("Salvar revisão"):
        db.save_analysis_result(new_version.id, "comments", result)
        clear_data_cache()
        st.success("Salva no histórico.")
