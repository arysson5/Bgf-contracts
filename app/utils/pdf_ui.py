"""Componentes Streamlit para visualização de PDF."""

import base64
import os
from pathlib import Path

import streamlit as st

from app.core.pdf_viewer import (
    COLOR_ADDED,
    COLOR_REMOVED,
    COLOR_HIGHLIGHT,
    find_text_locations,
    get_pdf_page_count,
    render_page_image,
)
from app.models.schemas import DiffLocation, DiffType, PdfRect, TextLocation


def _file_signature(path: str) -> float:
    """Assinatura para invalidar cache quando o arquivo muda."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False, max_entries=128)
def _cached_page_count(pdf_path: str, _sig: float) -> int:
    return get_pdf_page_count(pdf_path)


@st.cache_data(show_spinner=False, max_entries=128)
def _cached_page_image(
    pdf_path: str,
    _sig: float,
    page_num: int,
    rects_key: tuple,
    color: tuple,
    zoom: float,
) -> bytes:
    rects = [PdfRect(x0=a, y0=b, x1=c, y1=d) for (a, b, c, d) in rects_key] or None
    return render_page_image(pdf_path, page_num, rects, color, zoom)


def page_count_cached(pdf_path: str) -> int:
    """Contagem de páginas com cache (evita reabrir o PDF a cada rerun)."""
    return _cached_page_count(pdf_path, _file_signature(pdf_path))


def render_page_image_cached(
    pdf_path: str,
    page_num: int,
    rects: list[PdfRect] | None = None,
    color: tuple[float, float, float] = COLOR_HIGHLIGHT,
    zoom: float = 1.5,
) -> bytes:
    """Renderiza página do PDF com cache por (arquivo, página, destaques, cor, zoom)."""
    rects_key = tuple((r.x0, r.y0, r.x1, r.y1) for r in (rects or []))
    return _cached_page_image(
        pdf_path, _file_signature(pdf_path), page_num, rects_key, tuple(color), zoom
    )

def _show_pdf_fallback(path: Path, height: int, widget_key: str) -> None:
    """Visualização alternativa quando st.pdf não está disponível."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{b64}" '
        f'width="100%" height="{height}" style="border:none;"></iframe>',
        unsafe_allow_html=True,
    )
    with open(path, "rb") as f:
        st.download_button(
            "⬇️ Baixar PDF",
            f.read(),
            file_name=path.name,
            mime="application/pdf",
            key=f"{widget_key}_download",
        )


def show_pdf(pdf_path: str, height: int = 500, key: str | None = None) -> None:
    """Exibe PDF com st.pdf ou fallback (iframe + download)."""
    path = Path(pdf_path)
    if not path.exists():
        st.warning("PDF não encontrado.")
        return

    widget_key = key or f"pdf_view_{abs(hash(str(path.resolve())))}_{height}"

    try:
        st.pdf(str(path), height=height, key=f"{widget_key}_viewer")
    except TypeError:
        # Versões antigas do Streamlit sem parâmetro key em st.pdf
        try:
            st.pdf(str(path), height=height)
        except st.errors.StreamlitAPIException:
            _show_pdf_fallback(path, height, widget_key)
    except st.errors.StreamlitAPIException:
        _show_pdf_fallback(path, height, widget_key)


def render_pdf_navigator(
    pdf_path: str,
    change_items: list[DiffLocation] | None = None,
    excerpt_locations: list[TextLocation] | None = None,
    key_prefix: str = "pdf",
) -> None:
    """
    Exibe PDF com navegação por alterações ou trechos.
    change_items: lista de DiffLocation
    excerpt_locations: trechos avulsos (checklist)
    """
    if not pdf_path or not Path(pdf_path).exists():
        st.warning("Arquivo PDF não encontrado.")
        return
    if Path(pdf_path).suffix.lower() != ".pdf":
        st.info("Visualização no documento disponível apenas para PDF. Use o texto extraído para DOCX.")
        return

    nav_options: list[str] = []
    nav_map: dict[str, tuple[int, list, tuple]] = {}

    if change_items:
        for i, ch in enumerate(change_items):
            if not ch.locations:
                label = f"#{i+1} [{ch.block_type.value}] (não localizado no PDF) — {ch.text[:50]}..."
                nav_options.append(label)
                nav_map[label] = (1, [], COLOR_HIGHLIGHT)
            else:
                loc = ch.locations[0]
                icon = "+" if ch.block_type == DiffType.ADDED else "-"
                label = f"#{i+1} [{icon}] Pág. {loc.page} — {ch.text[:55]}..."
                color = COLOR_ADDED if ch.block_type == DiffType.ADDED else COLOR_REMOVED
                nav_options.append(label)
                nav_map[label] = (loc.page, loc.rects, color)

    if excerpt_locations:
        for i, loc in enumerate(excerpt_locations):
            label = f"Trecho {i+1} — Pág. {loc.page}: {loc.text[:50]}..."
            nav_options.append(label)
            nav_map[label] = (loc.page, loc.rects, COLOR_HIGHLIGHT)

    col_nav, col_pdf = st.columns([1, 2])

    with col_nav:
        st.markdown("**Navegar no documento**")
        if nav_options:
            selected = st.radio(
                "Ir para",
                nav_options,
                key=f"{key_prefix}_nav",
                label_visibility="collapsed",
            )
            page_num, rects, color = nav_map[selected]
        else:
            page_num = st.number_input(
                "Página",
                min_value=1,
                value=1,
                key=f"{key_prefix}_page_manual",
            )
            rects = []
            color = COLOR_HIGHLIGHT

        total_pages = st.session_state.get(f"{key_prefix}_total_pages")
        if total_pages:
            st.caption(f"Página {page_num} de {total_pages}")

        if st.checkbox("Ver PDF completo", key=f"{key_prefix}_show_full"):
            show_pdf(pdf_path, height=500, key=f"{key_prefix}_full")

    with col_pdf:
        try:
            total = page_count_cached(pdf_path)
            st.session_state[f"{key_prefix}_total_pages"] = total
            page_num = min(max(1, page_num), total)
            img = render_page_image_cached(pdf_path, page_num, rects or None, color)
            st.image(img, caption=f"Página {page_num}", width="stretch")
        except Exception as exc:
            st.error(f"Erro ao renderizar página: {exc}")


def locate_excerpt_in_pdf(pdf_path: str, excerpt: str | None) -> list[TextLocation]:
    if not excerpt or not pdf_path:
        return []
    return find_text_locations(pdf_path, excerpt)
