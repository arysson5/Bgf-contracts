"""UI unificada para PDF e DOCX."""

import base64
import os
from pathlib import Path

import streamlit as st

from app.core.docx_viewer import render_docx_paragraphs_html
from app.core.pdf_viewer import COLOR_ADDED, COLOR_REMOVED
from app.models.schemas import ChangeRisk, CommentReview, ContractualChange, TextLocation
from app.utils.pdf_ui import page_count_cached, render_page_image_cached, show_pdf
from app.utils.sync_scroll import (
    ensure_sync_scroll_handler,
    render_sync_scroll_controls,
)

_FULL_DOC_CSS = """
<style>
.bgf-doc-full { min-height: 90vh; max-height: 90vh; overflow-y: auto;
  border: 1px solid #D6E2F0; border-radius: 8px; padding: 8px; background: #fff; }
</style>
"""


@st.cache_data(show_spinner=False, max_entries=64)
def _cached_docx_html(file_path: str, _sig: float, highlight_key: tuple, color: str) -> str:
    return render_docx_paragraphs_html(file_path, set(highlight_key), color)


def docx_html_cached(
    file_path: str,
    highlight_indices: set[int] | None = None,
    color: str = "#fff3cd",
) -> str:
    """HTML de parágrafos do DOCX com cache (evita reparsing a cada rerun)."""
    try:
        sig = os.path.getmtime(file_path)
    except OSError:
        sig = 0.0
    key = tuple(sorted(highlight_indices or set()))
    return _cached_docx_html(file_path, sig, key, color)


def render_focused_excerpt(
    file_path: str,
    file_type: str,
    locations: list[TextLocation],
    *,
    highlight_color: tuple[float, float, float] | str = (1.0, 0.85, 0.2),
    caption: str = "Trecho marcado para comentário",
) -> None:
    """Visualização focada em um único trecho (comentário inline)."""
    if not file_path or not Path(file_path).exists():
        st.warning("Arquivo não encontrado.")
        return
    ft = file_type.lower() if file_type else Path(file_path).suffix.lower().lstrip(".")
    st.markdown(f"**{caption}**")
    if locations and locations[0].text:
        st.info(locations[0].text[:500])
    if ft == "pdf":
        page_num = locations[0].page if locations else 1
        rects = locations[0].rects if locations else []
        color = highlight_color if isinstance(highlight_color, tuple) else (1.0, 0.85, 0.2)
        try:
            total = page_count_cached(file_path)
            page_num = min(max(1, page_num), total)
            img = render_page_image_cached(file_path, page_num, rects or None, color)
            st.image(img, caption=f"Página {page_num} de {total}", width="stretch")
        except Exception as exc:
            st.error(str(exc))
    elif ft == "docx":
        highlight: set[int] = set()
        for loc in locations:
            if loc.paragraph_index is not None:
                highlight.add(loc.paragraph_index)
        color = highlight_color if isinstance(highlight_color, str) else "#fde68a"
        st.markdown(docx_html_cached(file_path, highlight, color), unsafe_allow_html=True)


def _doc_full_height(key: str) -> int:
    """Altura do painel de documento conforme checkbox 'documento completo'."""
    if st.session_state.get(key):
        return 900
    return 500


def _show_pdf_sync_scroll(
    file_path: str,
    *,
    height: int,
    key: str,
    sync_group: str,
) -> None:
    """PDF em painel rolável com scroll sincronizado (Shift + roda)."""
    path = Path(file_path)
    if not path.exists():
        st.warning("PDF não encontrado.")
        return
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        inner_h = max(400, height - 24)
        st.markdown(
            f'<div class="bgf-sync-scroll" data-sync-group="{sync_group}" '
            f'style="max-height:{height}px;overflow-y:auto;border:1px solid #D6E2F0;'
            f'border-radius:8px;padding:4px;background:#fff;">'
            f'<iframe src="data:application/pdf;base64,{b64}" width="100%" '
            f'height="{inner_h}" style="border:none;"></iframe></div>',
            unsafe_allow_html=True,
        )
    except OSError as exc:
        st.error(str(exc))
        show_pdf(file_path, height=height, key=key)


def render_side_by_side_documents(
    path_a: str,
    type_a: str,
    path_b: str,
    type_b: str,
    *,
    label_a: str = "Versão base",
    label_b: str = "Versão revisada",
    changes: list[ContractualChange] | None = None,
    text_diff_html: str | None = None,
    comment_reviews: list[CommentReview] | None = None,
    new_version=None,
    key_prefix: str = "sbs",
) -> None:
    """Layout unificado: dois documentos lado a lado ou diff textual HTML."""
    ensure_sync_scroll_handler()
    sync_group = key_prefix

    if comment_reviews:
        from app.utils.comment_balloons import (
            close_comment_modal_overlay,
            render_side_by_side_with_comment_balloons,
        )

        close_comment_modal_overlay()
        render_side_by_side_with_comment_balloons(
            path_a,
            type_a,
            path_b,
            type_b,
            comment_reviews,
            label_a=label_a,
            label_b=label_b,
            sync_group=sync_group,
            new_version=new_version,
        )
        return

    if text_diff_html:
        render_sync_scroll_controls(key=f"{key_prefix}_sync_scroll")
        st.markdown(text_diff_html, unsafe_allow_html=True)
        return

    full_key_a = f"{key_prefix}_full_a"
    full_key_b = f"{key_prefix}_full_b"
    c_opts, c_sync = st.columns([2, 3])
    with c_opts:
        st.checkbox("Documento completo (altura expandida)", key=full_key_a)
        st.checkbox("Documento completo — revisada", key=full_key_b)
    with c_sync:
        render_sync_scroll_controls(key=f"{key_prefix}_sync_scroll")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown(f"**{label_a}**")
        _render_document_column(
            path_a,
            type_a,
            changes,
            version_side="base",
            key_prefix=f"{key_prefix}_a",
            full_doc_key=full_key_a,
            sync_group=sync_group,
        )
    with col_right:
        st.markdown(f"**{label_b}**")
        _render_document_column(
            path_b,
            type_b,
            changes,
            version_side="new",
            key_prefix=f"{key_prefix}_b",
            full_doc_key=full_key_b,
            sync_group=sync_group,
        )


def _render_document_column(
    file_path: str,
    file_type: str,
    changes: list[ContractualChange] | None,
    *,
    version_side: str,
    key_prefix: str,
    full_doc_key: str,
    sync_group: str,
) -> None:
    if not file_path or not Path(file_path).exists():
        st.warning("Arquivo não encontrado.")
        return

    ft = file_type.lower() if file_type else Path(file_path).suffix.lower().lstrip(".")
    page_key = f"{key_prefix}_page"

    if ft == "pdf":
        try:
            total = page_count_cached(file_path)
        except Exception:
            total = 1
        page_num = st.number_input(
            "Ir para página",
            min_value=1,
            max_value=max(1, total),
            value=1,
            key=page_key,
        )
        if st.session_state.get(full_doc_key):
            _show_pdf_sync_scroll(
                file_path,
                height=_doc_full_height(full_doc_key),
                key=f"{key_prefix}_full",
                sync_group=sync_group,
            )
            return

        rects = []
        color = COLOR_ADDED if version_side == "new" else COLOR_REMOVED
        if changes:
            for ch in changes:
                locs = ch.locations_new if version_side == "new" else ch.locations_base
                for loc in locs:
                    if loc.page == page_num and loc.rects:
                        rects.extend(loc.rects)
                        if ch.risk_level == ChangeRisk.HIGH:
                            color = (1.0, 0.6, 0.2)
        try:
            img = render_page_image_cached(file_path, page_num, rects or None, color)
            st.image(img, caption=f"Página {page_num} de {total}", width="stretch")
        except Exception as exc:
            st.error(str(exc))
    elif ft == "docx":
        highlight: set[int] = set()
        color = "#fff3cd"
        if changes:
            for ch in changes or []:
                loc_list = ch.locations_new if version_side == "new" else ch.locations_base
                for loc in loc_list:
                    if loc.paragraph_index is not None:
                        highlight.add(loc.paragraph_index)
        height = _doc_full_height(full_doc_key)
        html = docx_html_cached(file_path, highlight, color)
        st.markdown(
            f'<div class="bgf-sync-scroll" data-sync-group="{sync_group}" '
            f'style="max-height:{height}px;overflow-y:auto;border:1px solid #D6E2F0;'
            f'border-radius:8px;padding:8px;">{html}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info(f"Formato .{ft} não suportado.")


def render_document_navigator(
    file_path: str,
    file_type: str,
    changes: list[ContractualChange] | None = None,
    excerpt_locations: list[TextLocation] | None = None,
    *,
    version_side: str = "new",
    key_prefix: str = "doc",
) -> None:
    if not file_path or not Path(file_path).exists():
        st.warning("Arquivo não encontrado.")
        return

    ft = file_type.lower() if file_type else Path(file_path).suffix.lower().lstrip(".")
    nav_options: list[str] = []
    nav_map: dict[str, tuple] = {}

    if changes:
        for i, ch in enumerate(changes):
            locs = ch.locations_new if version_side == "new" else ch.locations_base
            loc_label = ""
            if locs:
                loc = locs[0]
                if loc.document_type == "docx" and loc.paragraph_index is not None:
                    loc_label = f"¶{loc.paragraph_index + 1}"
                else:
                    loc_label = f"Pág.{loc.page}"
            risk = ch.risk_level.value if hasattr(ch.risk_level, "value") else str(ch.risk_level)
            label = f"#{i+1} [{risk}] {ch.clause_reference} — {ch.title[:35]}"
            if loc_label:
                label = f"#{i+1} [{risk}] {loc_label} {ch.title[:30]}"
            nav_options.append(label)
            nav_map[label] = (ch, locs)

    if excerpt_locations:
        for i, loc in enumerate(excerpt_locations):
            if loc.document_type == "docx" and loc.paragraph_index is not None:
                loc_label = f"¶{loc.paragraph_index + 1}"
            else:
                loc_label = f"Pág.{loc.page}"
            label = f"Trecho {i+1} — {loc_label}: {loc.text[:45]}..."
            nav_options.append(label)
            nav_map[label] = (None, [loc])

    selected_change: ContractualChange | None = None
    locs: list[TextLocation] = []

    col_nav, col_doc = st.columns([1, 2])

    with col_nav:
        st.markdown("**Navegar no documento**")
        if nav_options:
            selected = st.radio(
                "Ir para",
                nav_options,
                key=f"{key_prefix}_nav_{version_side}",
                label_visibility="collapsed",
            )
            selected_change, locs = nav_map[selected]
            if selected_change:
                with st.expander("Detalhe da alteração", expanded=True):
                    st.write(selected_change.description)
                    st.caption(f"**Impacto:** {selected_change.legal_impact}")
                    st.caption(f"**Parte afetada:** {selected_change.affected_party}")

        if st.checkbox("Ver documento completo", key=f"{key_prefix}_show_full_{version_side}"):
            full_h = 90 if st.checkbox(
                "Expandir (90vh)",
                value=False,
                key=f"{key_prefix}_expand_{version_side}",
            ) else 500
            if ft == "pdf":
                if full_h == 90:
                    st.markdown(_FULL_DOC_CSS, unsafe_allow_html=True)
                    show_pdf(file_path, height=700, key=f"{key_prefix}_full_{version_side}")
                else:
                    show_pdf(file_path, height=full_h, key=f"{key_prefix}_full_{version_side}")
            else:
                html = docx_html_cached(file_path)
                if full_h == 90:
                    st.markdown(
                        f'{_FULL_DOC_CSS}<div class="bgf-doc-full">{html}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(html, unsafe_allow_html=True)

    with col_doc:
        if ft == "pdf":
            _render_pdf_panel(
                file_path, locs, selected_change, version_side, key_prefix=key_prefix
            )
        elif ft == "docx":
            _render_docx_panel(file_path, locs, changes, version_side)
        else:
            st.info(f"Formato .{ft} não suportado para visualização.")


def _render_pdf_panel(
    file_path: str,
    locs: list[TextLocation],
    change: ContractualChange | None,
    version_side: str,
    *,
    key_prefix: str = "doc",
) -> None:
    try:
        total = page_count_cached(file_path)
    except Exception as exc:
        st.error(str(exc))
        return

    default_page = locs[0].page if locs else 1
    page_num = st.number_input(
        "Ir para página",
        min_value=1,
        max_value=total,
        value=min(max(1, default_page), total),
        key=f"{key_prefix}_page_{version_side}",
    )
    rects = locs[0].rects if locs and locs[0].page == page_num else []
    color = COLOR_ADDED if version_side == "new" else COLOR_REMOVED
    if change and change.risk_level == ChangeRisk.HIGH:
        color = (1.0, 0.6, 0.2)

    try:
        img = render_page_image_cached(file_path, int(page_num), rects or None, color)
        st.image(img, caption=f"Página {page_num} de {total}", width="stretch")
    except Exception as exc:
        st.error(str(exc))


def _render_docx_panel(
    file_path: str,
    locs: list[TextLocation],
    changes: list[ContractualChange] | None,
    version_side: str,
) -> None:
    highlight: set[int] = set()
    color = "#fff3cd"
    for loc in locs:
        if loc.paragraph_index is not None:
            highlight.add(loc.paragraph_index)
    if changes:
        for ch in changes:
            loc_list = ch.locations_new if version_side == "new" else ch.locations_base
            for loc in loc_list:
                if loc.paragraph_index is not None:
                    highlight.add(loc.paragraph_index)
                    if ch.risk_level == ChangeRisk.HIGH:
                        color = "#fecaca"
                    elif ch.risk_level == ChangeRisk.MEDIUM:
                        color = "#fef08a"

    st.markdown(docx_html_cached(file_path, highlight, color), unsafe_allow_html=True)
    if locs and locs[0].paragraph_index is not None:
        st.caption(f"Destaque no parágrafo ¶{locs[0].paragraph_index + 1}")
