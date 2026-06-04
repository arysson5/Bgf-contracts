"""UI unificada para PDF e DOCX."""

import os
from pathlib import Path

import streamlit as st

from app.core.docx_viewer import render_docx_paragraphs_html
from app.core.pdf_viewer import COLOR_ADDED, COLOR_REMOVED
from app.models.schemas import ChangeRisk, ContractualChange, TextLocation
from app.utils.pdf_ui import page_count_cached, render_page_image_cached, show_pdf


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
            if ft == "pdf":
                show_pdf(file_path, height=500, key=f"{key_prefix}_full_{version_side}")
            else:
                st.markdown(docx_html_cached(file_path), unsafe_allow_html=True)

    with col_doc:
        if ft == "pdf":
            _render_pdf_panel(file_path, locs, selected_change, version_side)
        elif ft == "docx":
            _render_docx_panel(file_path, locs, changes, version_side)
        else:
            st.info(f"Formato .{ft} não suportado para visualização.")


def _render_pdf_panel(
    file_path: str,
    locs: list[TextLocation],
    change: ContractualChange | None,
    version_side: str,
) -> None:
    page_num = locs[0].page if locs else 1
    rects = locs[0].rects if locs else []
    color = COLOR_ADDED if version_side == "new" else COLOR_REMOVED
    if change and change.risk_level == ChangeRisk.HIGH:
        color = (1.0, 0.6, 0.2)

    try:
        total = page_count_cached(file_path)
        page_num = min(max(1, page_num), total)
        img = render_page_image_cached(file_path, page_num, rects or None, color)
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
