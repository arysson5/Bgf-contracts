"""Balões de comentário na comparação lado a lado (análise com IA)."""

from __future__ import annotations

import base64
import html
import json
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from app.core import extractor
from app.core.comment_suggester import review_needs_reinforcement, suggest_reinforcement
from app.core.document_locator import find_in_document
from app.models.schemas import CommentReview, CommentStatus
from app.utils.comments_ui import (
    apply_quick_comment_to_version,
    get_quick_applied_ids,
)
from app.utils.pdf_ui import page_count_cached, render_page_image_cached
from app.utils.sync_scroll import (
    render_sync_scroll_controls,
    sync_scroll_classes,
)

_ZOOM = 1.2
_PANEL_HEIGHT = 72  # vh

_STATUS_COLORS = {
    CommentStatus.ATTENDED: ("#16a34a", "Atendido"),
    CommentStatus.PARTIALLY: ("#ca8a04", "Atendido parcialmente"),
    CommentStatus.NOT_ATTENDED: ("#dc2626", "Não atendido"),
}

_BALLOON_CSS = """
<style>
.bgf-sbs-outer { margin: 4px 0 8px; }
.bgf-sbs-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  align-items: start;
}
.bgf-sbs-col {
  border: 1px solid #D6E2F0; border-radius: 8px; background: #fff;
  max-height: 72vh; overflow-y: auto; overflow-x: hidden;
  padding: 10px 12px; overscroll-behavior: contain;
}
.bgf-sbs-col.bgf-comment-target { box-shadow: inset 0 0 0 2px #0A3D7A33; }
.bgf-sbs-col h4 { margin: 0 0 10px; font-size: 0.95rem; color: #0A3D7A; }
.bgf-docx-col.bgf-comment-target .bgf-docx-p,
.bgf-docx-col.bgf-comment-target .bgf-docx-balloon-row { cursor: context-menu; }
.bgf-docx-col.bgf-comment-target .bgf-docx-p:hover { background: #E8F1FB; }
.bgf-page-wrap { position: relative; margin-bottom: 10px; line-height: 0; }
.bgf-page-wrap img { width: 100%; height: auto; display: block; border-radius: 4px; }
.bgf-page-wrap[data-bgf-role="target"] { cursor: crosshair; }
.bgf-sel-rect {
  position: absolute; background: rgba(10,61,122,.18);
  border: 1px dashed #0A3D7A; pointer-events: none; z-index: 4;
}
.bgf-balloon {
  position: absolute; width: 28px; height: 28px; border: 2px solid #fff;
  border-radius: 6px 6px 6px 2px; cursor: pointer; z-index: 5;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 6px rgba(0,0,0,.25); padding: 0;
  transition: transform .12s ease;
}
.bgf-balloon:hover { transform: scale(1.12); z-index: 6; }
.bgf-balloon svg { width: 16px; height: 16px; fill: #fff; pointer-events: none; }
.bgf-balloon path { pointer-events: none; }
.bgf-balloon-attended { background: #16a34a; }
.bgf-balloon-partially { background: #ca8a04; }
.bgf-balloon-not_attended { background: #dc2626; }
.bgf-docx-balloon-row {
  position: relative; padding-left: 36px; margin: 6px 0;
}
.bgf-docx-balloon-row .bgf-balloon {
  position: absolute; left: 0; top: 4px;
}
.bgf-docx-balloon-row .bgf-docx-text {
  font-family: Georgia, serif; line-height: 1.55; font-size: 0.92rem;
  padding: 6px 8px; border-radius: 4px; background: #f8fafc;
}
.bgf-docx-balloon-row.bgf-hl-attended .bgf-docx-text { background: #f0fdf4; border-left: 3px solid #16a34a; }
.bgf-docx-balloon-row.bgf-hl-partially .bgf-docx-text { background: #fefce8; border-left: 3px solid #ca8a04; }
.bgf-docx-balloon-row.bgf-hl-not_attended .bgf-docx-text { background: #fef2f2; border-left: 3px solid #dc2626; }
.bgf-hl-rect {
  position: absolute; border: 2px solid; border-radius: 2px;
  pointer-events: none; z-index: 3; opacity: 0.85;
}
.bgf-hl-rect.bgf-hl-attended { background: rgba(22,163,74,0.14); border-color: #16a34a; }
.bgf-hl-rect.bgf-hl-partially { background: rgba(202,138,4,0.16); border-color: #ca8a04; }
.bgf-hl-rect.bgf-hl-not_attended { background: rgba(220,38,38,0.12); border-color: #dc2626; }
.bgf-cmt-legend {
  display: flex; gap: 14px; flex-wrap: wrap; margin: 0 0 10px; font-size: 0.82rem;
}
.bgf-cmt-legend span { display: inline-flex; align-items: center; gap: 6px; }
.bgf-cmt-dot { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
</style>
"""

_COL_INLINE_STYLE = (
    "max-height:72vh;overflow-y:auto;overflow-x:hidden;"
    "border:1px solid #D6E2F0;border-radius:8px;padding:10px 12px;"
    "background:#fff;overscroll-behavior:contain;"
)

_BALLOON_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M20 2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h4l4 4 4-4h4c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>'
    "</svg>"
)


@dataclass
class _CommentMarker:
    comment_id: str
    status: CommentStatus
    page: int
    top_pct: float
    left_pct: float
    paragraph_index: int | None = None
    excerpt: str = ""
    rect_pct: tuple[float, float, float, float] | None = None


def _match_extracted(extracted: dict[str, dict], rev: CommentReview) -> dict:
    raw = extracted.get(rev.comment_id, {})
    if raw:
        return raw
    needle = rev.original_comment.strip()[:120]
    for item in extracted.values():
        if (item.get("comment_text") or "").strip()[:120] == needle:
            return item
    return {}


def _page_size_pct(path: str, page: int) -> tuple[float, float]:
    try:
        doc = __import__("fitz").open(path)
        pg = doc[page - 1]
        pw, ph = pg.rect.width, pg.rect.height
        doc.close()
        return pw, ph
    except Exception:
        return 595.0, 842.0


def _rect_to_page_pct(
    rect: dict | object,
    path: str,
    page: int,
) -> tuple[float, float, float, float]:
    pw, ph = _page_size_pct(path, page)
    if not pw or not ph:
        return 0.0, 0.0, 0.0, 0.0
    if isinstance(rect, dict):
        x0, y0, x1, y1 = rect["x0"], rect["y0"], rect["x1"], rect["y1"]
    else:
        x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
    return (
        max(0.0, (x0 / pw) * 100),
        max(0.0, (y0 / ph) * 100),
        min(100.0, (x1 / pw) * 100),
        min(100.0, (y1 / ph) * 100),
    )


def _balloon_pct_from_rect(
    rect_pct: tuple[float, float, float, float],
) -> tuple[float, float]:
    x0, y0, x1, y1 = rect_pct
    top = min(92.0, max(2.0, y0))
    left = min(94.0, max(2.0, x1 + 0.8))
    if x1 - x0 < 1.5:
        left = min(94.0, max(2.0, x0 + 1.0))
    return left, top


def _location_to_marker(
    rev: CommentReview,
    loc: object,
    path: str,
    excerpt: str,
) -> _CommentMarker:
    page = int(getattr(loc, "page", 1) or 1)
    para_idx = getattr(loc, "paragraph_index", None)
    rects = getattr(loc, "rects", None) or []
    rect_pct = None
    top_pct, left_pct = 8.0, 92.0
    if rects:
        rect_pct = _rect_to_page_pct(rects[0], path, page)
        left_pct, top_pct = _balloon_pct_from_rect(rect_pct)
    return _CommentMarker(
        comment_id=rev.comment_id,
        status=rev.status,
        page=page,
        top_pct=top_pct,
        left_pct=left_pct,
        paragraph_index=para_idx,
        excerpt=excerpt or getattr(loc, "text", "")[:500],
        rect_pct=rect_pct,
    )


def _marker_from_extracted(
    rev: CommentReview,
    raw: dict,
    path: str,
    file_type: str,
    excerpt: str,
) -> _CommentMarker | None:
    ft = file_type.lower() if file_type else Path(path).suffix.lower().lstrip(".")
    page = int(raw.get("page") or 1)
    para_idx = raw.get("paragraph_index")
    rects = raw.get("rects") or []
    rect_pct = None
    top_pct, left_pct = 8.0, 92.0

    if rects and ft == "pdf":
        rect_pct = _rect_to_page_pct(rects[0], path, page)
        left_pct, top_pct = _balloon_pct_from_rect(rect_pct)
    elif para_idx is None and ft in ("docx", "doc"):
        locs = find_in_document(path, excerpt or rev.referenced_excerpt or rev.original_comment)
        if locs and locs[0].paragraph_index is not None:
            para_idx = locs[0].paragraph_index
    elif ft == "pdf" and not rects:
        locs = find_in_document(path, excerpt or rev.referenced_excerpt or rev.original_comment)
        if locs and locs[0].rects:
            page = locs[0].page
            rect_pct = _rect_to_page_pct(locs[0].rects[0], path, page)
            left_pct, top_pct = _balloon_pct_from_rect(rect_pct)

    return _CommentMarker(
        comment_id=rev.comment_id,
        status=rev.status,
        page=page,
        top_pct=top_pct,
        left_pct=left_pct,
        paragraph_index=para_idx,
        excerpt=excerpt,
        rect_pct=rect_pct,
    )


def _resolve_query_for_side(rev: CommentReview, side: str, raw: dict) -> str:
    if side == "base":
        return (
            rev.referenced_excerpt
            or raw.get("referenced_text")
            or rev.original_comment
            or ""
        )[:400]
    return (rev.change_found or rev.referenced_excerpt or "")[:400]


def _markers_for_side(
    reviews: list[CommentReview],
    path: str,
    file_type: str,
    *,
    side: str,
    extracted: dict[str, dict],
) -> list[_CommentMarker]:
    """Posiciona balões no trecho ancorado (base) ou na alteração correspondente (revisada)."""
    markers: list[_CommentMarker] = []
    for rev in reviews:
        raw = _match_extracted(extracted, rev) if side == "base" else {}
        excerpt = (
            rev.referenced_excerpt
            or raw.get("referenced_text")
            or rev.original_comment
            or ""
        )[:500]
        marker: _CommentMarker | None = None

        if side == "base" and raw:
            marker = _marker_from_extracted(rev, raw, path, file_type, excerpt)

        if marker is None:
            locs = rev.locations_base if side == "base" else rev.locations
            if locs:
                marker = _location_to_marker(rev, locs[0], path, excerpt)

        if marker is None:
            query = _resolve_query_for_side(rev, side, raw)
            if len(query.strip()) >= 4:
                locs = find_in_document(path, query)
                if locs:
                    marker = _location_to_marker(rev, locs[0], path, excerpt)

        if marker:
            markers.append(marker)
    return markers


def _extracted_by_id(base_path: str) -> dict[str, dict]:
    try:
        raw = extractor.extract_comments(base_path)
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for item in raw:
        cid = item.get("stable_id") or item.get("id")
        if cid:
            out[cid] = item
    return out


def _highlight_rect_html(marker: _CommentMarker) -> str:
    if not marker.rect_pct:
        return ""
    x0, y0, x1, y1 = marker.rect_pct
    w = max(0.5, x1 - x0)
    h = max(0.4, y1 - y0)
    status = marker.status.value
    return (
        f'<div class="bgf-hl-rect bgf-hl-{status}" '
        f'style="left:{x0:.2f}%;top:{y0:.2f}%;width:{w:.2f}%;height:{h:.2f}%;"></div>'
    )


def _balloon_btn(marker: _CommentMarker) -> str:
    status_val = marker.status.value
    return (
        f'<button type="button" class="bgf-balloon bgf-balloon-{status_val}" '
        f'data-cmt-id="{html.escape(marker.comment_id)}" '
        f'style="top:{marker.top_pct:.1f}%;left:{marker.left_pct:.1f}%;" '
        f'title="Comentário — clique para ver análise">{_BALLOON_SVG}</button>'
    )


def _pdf_column_html(
    file_path: str,
    label: str,
    markers: list[_CommentMarker] | None,
    *,
    sync_group: str,
    show_markers: bool,
    render_all_pages: bool = False,
    is_target: bool = False,
) -> str:
    total = page_count_cached(file_path)
    markers_by_page: dict[int, list[_CommentMarker]] = {}
    for m in markers or []:
        markers_by_page.setdefault(m.page, []).append(m)

    if render_all_pages:
        page_nums = list(range(1, total + 1))
    elif markers_by_page:
        wanted: set[int] = set()
        for p in markers_by_page:
            for d in (-1, 0, 1):
                n = p + d
                if 1 <= n <= total:
                    wanted.add(n)
        page_nums = sorted(wanted)
    else:
        page_nums = list(range(1, min(total, 3) + 1))

    role = "target" if is_target else "base"
    target_cls = " bgf-comment-target" if is_target else ""
    pages: list[str] = []
    for p in page_nums:
        try:
            png = render_page_image_cached(file_path, p, zoom=_ZOOM)
            b64 = base64.b64encode(png).decode("ascii")
        except Exception:
            continue
        overlays = ""
        if show_markers:
            for mk in markers_by_page.get(p, []):
                overlays += _highlight_rect_html(mk)
                overlays += _balloon_btn(mk)
        pages.append(
            f'<div class="bgf-page-wrap{target_cls}" data-bgf-role="{role}" '
            f'data-bgf-page="{p}" data-bgf-kind="pdf">'
            f'<img src="data:image/png;base64,{b64}" alt="Página {p}"/>{overlays}</div>'
        )

    skipped = total - len(page_nums)
    note = ""
    if skipped > 0:
        note = (
            f'<p style="font-size:0.8rem;color:#64748b;margin:0 0 8px;">'
            f"Mostrando {len(page_nums)} de {total} páginas. Ative "
            f"<em>Documento completo</em> para renderizar todas.</p>"
        )
    if is_target:
        note += (
            '<p style="font-size:0.8rem;color:#0A3D7A;margin:0 0 8px;">'
            "Botão direito neste documento para comentar no ponto. "
            "Arraste para marcar um trecho e depois clique com o direito.</p>"
        )

    body = "".join(pages) or "<em>Sem páginas</em>"
    return (
        f'<div class="bgf-sbs-col {sync_scroll_classes(sync_group)}{target_cls}" '
        f'style="{_COL_INLINE_STYLE}" '
        f'data-sync-group="{html.escape(sync_group)}" data-bgf-role="{role}">'
        f"<h4>{html.escape(label)}</h4>{note}{body}</div>"
    )


def _docx_column_html(
    file_path: str,
    label: str,
    markers: list[_CommentMarker] | None,
    *,
    sync_group: str,
    show_markers: bool,
    is_target: bool = False,
) -> str:
    from app.core.docx_viewer import iter_docx_paragraph_texts

    paragraphs = iter_docx_paragraph_texts(file_path)
    marker_by_para: dict[int, _CommentMarker] = {}
    if show_markers:
        for m in markers or []:
            if m.paragraph_index is not None:
                marker_by_para[m.paragraph_index] = m

    role = "target" if is_target else "base"
    target_cls = " bgf-comment-target" if is_target else ""
    rows: list[str] = []
    if is_target:
        rows.append(
            '<p style="font-size:0.8rem;color:#0A3D7A;margin:0 0 8px;">'
            "Clique com o <strong>botão direito</strong> em um parágrafo "
            "(ou selecione um trecho) para comentar neste ponto.</p>"
        )
    for idx, text in enumerate(paragraphs):
        mk = marker_by_para.get(idx)
        text = (text or "").strip()
        if mk and not text:
            text = mk.excerpt.strip()
        if not text and mk is None:
            continue
        safe = html.escape(text or "(sem trecho visível no documento)")
        para_cls = f"bgf-para-idx-{idx}"
        attrs = (
            f'class="bgf-docx-p {para_cls}{target_cls}" '
            f'data-bgf-role="{role}" data-bgf-para="{idx}" data-bgf-kind="docx" '
            f'data-bgf-page="{idx + 1}"'
        )
        if mk:
            status_val = mk.status.value
            balloon = _balloon_btn(mk).replace(
                f'style="top:{mk.top_pct:.1f}%;left:{mk.left_pct:.1f}%;"',
                'style="position:absolute;left:0;top:4px;"',
            )
            rows.append(
                f'<div class="bgf-docx-balloon-row bgf-hl-{status_val} {para_cls}{target_cls}" '
                f'data-cmt-id="{html.escape(mk.comment_id)}" '
                f'data-bgf-role="{role}" data-bgf-para="{idx}" data-bgf-kind="docx" '
                f'data-bgf-page="{idx + 1}">'
                f"{balloon}<div class=\"bgf-docx-text\">{safe}</div></div>"
            )
        else:
            rows.append(
                f'<div {attrs} style="margin:6px 0;line-height:1.55;">{safe}</div>'
            )

    if len(rows) <= (1 if is_target else 0):
        rows.append("<em>Documento vazio</em>")

    body = "".join(rows)
    return (
        f'<div class="bgf-sbs-col {sync_scroll_classes(sync_group)} bgf-docx-col{target_cls}" '
        f'style="{_COL_INLINE_STYLE}" '
        f'data-sync-group="{html.escape(sync_group)}" data-bgf-role="{role}" data-bgf-kind="docx">'
        f"<h4>{html.escape(label)}</h4>{body}</div>"
    )


def _column_html(
    file_path: str,
    file_type: str,
    label: str,
    markers: list[_CommentMarker] | None,
    *,
    sync_group: str,
    show_markers: bool,
    render_all_pages: bool = False,
    is_target: bool = False,
) -> str:
    ft = file_type.lower() if file_type else Path(file_path).suffix.lower().lstrip(".")
    if ft == "pdf":
        return _pdf_column_html(
            file_path,
            label,
            markers,
            sync_group=sync_group,
            show_markers=show_markers,
            render_all_pages=render_all_pages,
            is_target=is_target,
        )
    if ft in ("docx", "doc"):
        return _docx_column_html(
            file_path,
            label,
            markers,
            sync_group=sync_group,
            show_markers=show_markers,
            is_target=is_target,
        )
    return (
        f'<div class="bgf-sbs-col {sync_scroll_classes(sync_group)}">'
        f"<h4>{html.escape(label)}</h4><em>Formato não suportado</em></div>"
    )


def _reviews_payload(reviews: list[CommentReview]) -> str:
    items = []
    for rev in reviews:
        color, label = _STATUS_COLORS.get(rev.status, ("#64748b", rev.status.value))
        items.append(
            {
                "id": rev.comment_id,
                "status": rev.status.value,
                "status_label": label,
                "color": color,
                "original": rev.original_comment,
                "justification": rev.justification,
                "change_found": rev.change_found or "",
                "suggested_response": rev.suggested_response or "",
                "referenced": rev.referenced_excerpt or "",
                "needs_reinforcement": review_needs_reinforcement(rev),
            }
        )
    return json.dumps(items, ensure_ascii=False)


_UNUSED_LEGACY_BALLOON_JS = """
<script>
(function () {
  const doc = window.parent.document;
  const css = __BGF_CSS__;
  doc.__bgfCommentsData = __BGF_DATA__;

  let style = doc.getElementById("bgf-cmt-modal-styles");
  if (!style) {
    style = doc.createElement("style");
    style.id = "bgf-cmt-modal-styles";
    doc.head.appendChild(style);
  }
  if (css) style.textContent = css;

  function setQuery(params) {
    const url = new URL(window.parent.location.href);
    Object.keys(params).forEach(function (k) {
      const v = params[k];
      if (v === null || v === undefined || v === "") url.searchParams.delete(k);
      else url.searchParams.set(k, String(v));
    });
    window.parent.location.href = url.pathname + url.search + url.hash;
  }

  function ensureModal() {
    let overlay = doc.getElementById("bgf-cmt-modal-overlay");
    if (overlay) return overlay;
    overlay = doc.createElement("div");
    overlay.id = "bgf-cmt-modal-overlay";
    overlay.className = "bgf-cmt-modal-overlay";
    overlay.innerHTML =
      '<div class="bgf-cmt-modal" role="dialog" aria-modal="true">' +
      '<h3>Análise do comentário</h3>' +
      '<span class="bgf-cmt-badge" id="bgf-cmt-badge"></span>' +
      '<p class="bgf-cmt-label">Pedido original</p><p id="bgf-cmt-original"></p>' +
      '<p class="bgf-cmt-label">Trecho referenciado</p><pre id="bgf-cmt-referenced"></pre>' +
      '<p class="bgf-cmt-label">Análise da IA</p><p id="bgf-cmt-justification"></p>' +
      '<p class="bgf-cmt-label" id="bgf-cmt-change-label" style="display:none">Alteração na nova versão</p>' +
      '<pre id="bgf-cmt-change" style="display:none"></pre>' +
      '<p class="bgf-cmt-label" id="bgf-cmt-suggest-label" style="display:none">Sugestão de resposta</p>' +
      '<p id="bgf-cmt-suggest" style="display:none"></p>' +
      '<div class="bgf-cmt-modal-actions">' +
      '<button type="button" class="bgf-cmt-btn bgf-cmt-btn-secondary" id="bgf-cmt-close">Fechar</button>' +
      '<p class="bgf-cmt-hint" style="margin:8px 0 0;font-size:0.82rem;color:#64748b;">' +
      'Para gravar no arquivo, use os botões <strong>Incluir</strong> na seção abaixo.</p>' +
      '</div></div>';
    doc.body.appendChild(overlay);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeModal();
    });
    const closeBtn = overlay.querySelector("#bgf-cmt-close");
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    return overlay;
  }

  function getData() {
    if (Array.isArray(doc.__bgfCommentsData) && doc.__bgfCommentsData.length) {
      return doc.__bgfCommentsData;
    }
    const el = doc.getElementById("bgf-comments-data");
    if (!el) return [];
    try {
      return JSON.parse(el.textContent || el.getAttribute("data-json") || "[]");
    } catch (err) {
      return [];
    }
  }

  function openModal(id) {
    const data = getData().find(function (x) { return String(x.id) === String(id); });
    if (!data) {
      console.warn("[BGF] Comentário não encontrado no payload:", id, getData().length);
      return;
    }
    const overlay = ensureModal();
    const badge = doc.getElementById("bgf-cmt-badge");
    badge.textContent = data.status_label || "";
    badge.style.background = data.color || "#64748b";
    doc.getElementById("bgf-cmt-original").textContent = data.original || "";
    doc.getElementById("bgf-cmt-referenced").textContent = data.referenced || "(sem trecho)";
    doc.getElementById("bgf-cmt-justification").textContent = data.justification || "";
    const chLbl = doc.getElementById("bgf-cmt-change-label");
    const ch = doc.getElementById("bgf-cmt-change");
    if (data.change_found) {
      chLbl.style.display = "block";
      ch.style.display = "block";
      ch.textContent = data.change_found;
    } else {
      chLbl.style.display = "none";
      ch.style.display = "none";
    }
    const sgLbl = doc.getElementById("bgf-cmt-suggest-label");
    const sg = doc.getElementById("bgf-cmt-suggest");
    if (data.suggested_response) {
      sgLbl.style.display = "block";
      sg.style.display = "block";
      sg.textContent = data.suggested_response;
    } else {
      sgLbl.style.display = "none";
      sg.style.display = "none";
    }
    overlay.classList.add("bgf-open");
  }

  function closeModal() {
    const overlay = doc.getElementById("bgf-cmt-modal-overlay");
    if (overlay) overlay.classList.remove("bgf-open");
  }

  if (doc.__bgfCmtClickHandler) {
    try { doc.removeEventListener("click", doc.__bgfCmtClickHandler, true); } catch (err) {}
  }
  if (doc.__bgfCmtCtxHandler) {
    try { doc.removeEventListener("contextmenu", doc.__bgfCmtCtxHandler, true); } catch (err) {}
  }
  if (doc.__bgfCmtDownHandler) {
    try { doc.removeEventListener("mousedown", doc.__bgfCmtDownHandler, true); } catch (err) {}
  }
  if (doc.__bgfCmtMoveHandler) {
    try { doc.removeEventListener("mousemove", doc.__bgfCmtMoveHandler, true); } catch (err) {}
  }
  if (doc.__bgfCmtUpHandler) {
    try { doc.removeEventListener("mouseup", doc.__bgfCmtUpHandler, true); } catch (err) {}
  }

  doc.__bgfCmtClickHandler = function (e) {
    const t = e.target;
    if (!t || !t.closest) return;
    const btn = t.closest(".bgf-balloon");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    setQuery({ bgf_cmt: btn.getAttribute("data-cmt-id") });
  };
  doc.addEventListener("click", doc.__bgfCmtClickHandler, true);

  function pctOnImg(e, img) {
    const r = img.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    const x = ((e.clientX - r.left) / r.width) * 100;
    const y = ((e.clientY - r.top) / r.height) * 100;
    return { x: Math.max(0, Math.min(100, x)), y: Math.max(0, Math.min(100, y)) };
  }
  function clearSel(wrap) {
    if (!wrap) return;
    const old = wrap.querySelector(".bgf-sel-rect");
    if (old) old.remove();
    delete wrap.dataset.selX0;
    delete wrap.dataset.selY0;
    delete wrap.dataset.selX1;
    delete wrap.dataset.selY1;
  }
  let drag = null;
  doc.__bgfCmtDownHandler = function (e) {
    if (e.button !== 0) return;
    const t = e.target;
    if (!t || !t.closest) return;
    if (t.closest(".bgf-balloon")) return;
    const wrap = t.closest('.bgf-page-wrap[data-bgf-role="target"]');
    if (!wrap) return;
    const img = wrap.querySelector("img");
    if (!img) return;
    const p = pctOnImg(e, img);
    if (!p) return;
    drag = { wrap: wrap, start: p };
    clearSel(wrap);
    e.preventDefault();
  };
  doc.__bgfCmtMoveHandler = function (e) {
    if (!drag) return;
    const img = drag.wrap.querySelector("img");
    const p = pctOnImg(e, img);
    if (!p) return;
    let box = drag.wrap.querySelector(".bgf-sel-rect");
    if (!box) {
      box = doc.createElement("div");
      box.className = "bgf-sel-rect";
      drag.wrap.appendChild(box);
    }
    const x0 = Math.min(drag.start.x, p.x);
    const y0 = Math.min(drag.start.y, p.y);
    const x1 = Math.max(drag.start.x, p.x);
    const y1 = Math.max(drag.start.y, p.y);
    box.style.left = x0 + "%";
    box.style.top = y0 + "%";
    box.style.width = (x1 - x0) + "%";
    box.style.height = (y1 - y0) + "%";
  };
  doc.__bgfCmtUpHandler = function (e) {
    if (!drag) return;
    const img = drag.wrap.querySelector("img");
    const p = pctOnImg(e, img) || drag.start;
    const x0 = Math.min(drag.start.x, p.x);
    const y0 = Math.min(drag.start.y, p.y);
    const x1 = Math.max(drag.start.x, p.x);
    const y1 = Math.max(drag.start.y, p.y);
    if ((x1 - x0) > 1.2 && (y1 - y0) > 1.0) {
      drag.wrap.dataset.selX0 = x0.toFixed(2);
      drag.wrap.dataset.selY0 = y0.toFixed(2);
      drag.wrap.dataset.selX1 = x1.toFixed(2);
      drag.wrap.dataset.selY1 = y1.toFixed(2);
    } else {
      clearSel(drag.wrap);
    }
    drag = null;
  };
  doc.addEventListener("mousedown", doc.__bgfCmtDownHandler, true);
  doc.addEventListener("mousemove", doc.__bgfCmtMoveHandler, true);
  doc.addEventListener("mouseup", doc.__bgfCmtUpHandler, true);

  doc.__bgfCmtCtxHandler = function (e) {
    let t = e.target;
    if (t && t.nodeType === 3) t = t.parentElement;
    if (!t || !t.closest) return;

    function paraIdx(el) {
      if (!el) return "";
      const m = String(el.className || "").match(/bgf-para-idx-(\\d+)/);
      if (m) return m[1];
      return el.getAttribute("data-bgf-para") || "";
    }

    const docxEl = t.closest(".bgf-docx-p, .bgf-docx-balloon-row, .bgf-docx-text");
    const pageWrap = t.closest(".bgf-page-wrap.bgf-comment-target");
    const docxCol = t.closest(".bgf-docx-col.bgf-comment-target");
    let kind = "";
    let page = "1";
    let para = "";
    let host = null;

    if (docxEl || docxCol) {
      kind = "docx";
      let anchor = docxEl
        ? (docxEl.classList.contains("bgf-docx-text") ? docxEl.closest(".bgf-docx-balloon-row") || docxEl : docxEl)
        : null;
      if (!anchor && docxCol) {
        const nodes = docxCol.querySelectorAll("[class*='bgf-para-idx-']");
        let best = null;
        let bestDist = 1e9;
        for (let i = 0; i < nodes.length; i++) {
          const rr = nodes[i].getBoundingClientRect();
          if (e.clientY >= rr.top && e.clientY <= rr.bottom) {
            best = nodes[i];
            break;
          }
          const mid = (rr.top + rr.bottom) / 2;
          const d = Math.abs(e.clientY - mid);
          if (d < bestDist) {
            bestDist = d;
            best = nodes[i];
          }
        }
        anchor = best;
      }
      if (!anchor) return;
      para = paraIdx(anchor);
      page = String((parseInt(para, 10) || 0) + 1);
    } else if (pageWrap) {
      kind = "pdf";
      host = pageWrap;
      page = pageWrap.getAttribute("data-bgf-page") || "1";
    } else {
      return;
    }

    e.preventDefault();
    e.stopPropagation();
    const selText = (window.parent.getSelection && window.parent.getSelection().toString() || "").trim().slice(0, 400);
    const params = {
      bgf_rc: "1",
      bgf_rc_kind: kind,
      bgf_rc_page: page,
      bgf_rc_para: para,
      bgf_rc_sel: selText
    };
    if (kind === "pdf" && host) {
      const imgEl = host.querySelector("img");
      const p = imgEl ? pctOnImg(e, imgEl) : null;
      if (p) {
        params.bgf_rc_x = p.x.toFixed(2);
        params.bgf_rc_y = p.y.toFixed(2);
      }
      if (host.dataset && host.dataset.selX0) {
        params.bgf_rc_x0 = host.dataset.selX0;
        params.bgf_rc_y0 = host.dataset.selY0;
        params.bgf_rc_x1 = host.dataset.selX1;
        params.bgf_rc_y1 = host.dataset.selY1;
      }
    }
    setQuery(params);
  };
  doc.addEventListener("contextmenu", doc.__bgfCmtCtxHandler, true);
})();
</script>
"""

_MODAL_ONLY_CSS = """
.bgf-sbs-col {
  max-height: 72vh !important;
  overflow-y: auto !important;
  overflow-x: hidden !important;
  overscroll-behavior: contain;
}
.bgf-sbs-grid { align-items: start; }
.bgf-docx-col.bgf-comment-target .bgf-docx-p,
.bgf-docx-col.bgf-comment-target .bgf-docx-balloon-row { cursor: context-menu; }
.bgf-cmt-modal-overlay {
  display: none; position: fixed; inset: 0; background: rgba(13,33,55,.45);
  z-index: 99999; align-items: center; justify-content: center; padding: 16px;
}
.bgf-cmt-modal-overlay.bgf-open { display: flex !important; }
.bgf-cmt-modal {
  background: #fff; border-radius: 12px; max-width: 560px; width: 100%;
  max-height: 85vh; overflow-y: auto; padding: 20px 22px;
  box-shadow: 0 12px 40px rgba(0,0,0,.2);
}
.bgf-cmt-modal h3 { margin: 0 0 12px; font-size: 1.05rem; color: #0A3D7A; }
.bgf-cmt-badge {
  display: inline-block; padding: 3px 10px; border-radius: 999px;
  font-size: 0.8rem; font-weight: 600; color: #fff; margin-bottom: 12px;
}
.bgf-cmt-modal p { margin: 8px 0; line-height: 1.5; color: #0D2137; }
.bgf-cmt-modal .bgf-cmt-label { font-weight: 600; font-size: 0.85rem; color: #475569; }
.bgf-cmt-modal pre {
  background: #f1f5f9; padding: 10px; border-radius: 6px;
  white-space: pre-wrap; font-size: 0.82rem; max-height: 160px; overflow-y: auto;
}
.bgf-cmt-modal-actions { display: flex; gap: 10px; margin-top: 16px; flex-wrap: wrap; }
.bgf-cmt-btn {
  padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer;
  font-size: 0.9rem; font-weight: 600;
}
.bgf-cmt-btn-primary { background: #0A3D7A; color: #fff; }
.bgf-cmt-btn-primary:hover { background: #083060; }
.bgf-cmt-btn-secondary { background: #e2e8f0; color: #334155; }
.bgf-balloon svg, .bgf-balloon path { pointer-events: none; }
"""

_INJECTED_BALLOON_KEY = "_bgf_comment_balloon_js_v8"


def close_comment_modal_overlay() -> None:
    """No-op: o diálogo agora é st.dialog, sem overlay em iframe."""
    return


def ensure_comment_balloon_handler(
    reviews: list[CommentReview] | None = None,
    *,
    sync_enabled: bool = True,
) -> None:
    """Clique direito e balões voltam ao Python pelo componente v2 (sem navegar a URL)."""
    from app.utils.comment_actions_ui import ingest_bridge_event
    from app.utils.page_bridge import mount_page_bridge

    event = mount_page_bridge(comments=True, sync_enabled=sync_enabled)
    st.session_state[_INJECTED_BALLOON_KEY] = True
    ingest_bridge_event(event)


def _balloon_cache_key(
    path_a: str,
    path_b: str,
    reviews: list[CommentReview],
    *,
    render_all_pages: bool,
) -> str:
    ids = ",".join(sorted(r.comment_id for r in reviews))
    try:
        mtime = f"{Path(path_a).stat().st_mtime_ns}:{Path(path_b).stat().st_mtime_ns}"
    except OSError:
        mtime = "0"
    return f"{path_a}|{path_b}|{mtime}|{ids}|all={int(render_all_pages)}|layout=scroll-v3"


def build_side_by_side_balloons_html(
    path_a: str,
    type_a: str,
    path_b: str,
    type_b: str,
    reviews: list[CommentReview],
    *,
    label_a: str = "Versão base",
    label_b: str = "Versão revisada",
    sync_group: str = "cmp_sbs",
    render_all_pages: bool = False,
) -> str:
    """HTML lado a lado: balões na âncora do comentário (base) e no trecho revisado (nova)."""
    cache_key = _balloon_cache_key(
        path_a, path_b, reviews, render_all_pages=render_all_pages
    )
    cached = st.session_state.get("_bgf_balloon_html_cache")
    if isinstance(cached, dict) and cached.get("key") == cache_key:
        return cached["html"]

    extracted = _extracted_by_id(path_a)
    base_markers = _markers_for_side(
        reviews, path_a, type_a, side="base", extracted=extracted
    )
    new_markers = _markers_for_side(
        reviews, path_b, type_b, side="new", extracted={}
    )
    legend = (
        '<div class="bgf-cmt-legend">'
        '<span><i class="bgf-cmt-dot" style="background:#16a34a"></i> Atendido</span>'
        '<span><i class="bgf-cmt-dot" style="background:#ca8a04"></i> Atendido parcialmente</span>'
        '<span><i class="bgf-cmt-dot" style="background:#dc2626"></i> Não atendido</span>'
        '<span style="color:#64748b">· Clique no balão para aceitar/editar · '
        "Botão direito no documento da <strong>direita</strong> para novo comentário</span>"
        "</div>"
    )
    left = _column_html(
        path_a,
        type_a,
        label_a,
        base_markers,
        sync_group=sync_group,
        show_markers=True,
        render_all_pages=render_all_pages,
        is_target=False,
    )
    right = _column_html(
        path_b,
        type_b,
        label_b,
        new_markers,
        sync_group=sync_group,
        show_markers=True,
        render_all_pages=render_all_pages,
        is_target=True,
    )
    # Streamlit remove <script> do markdown — dados ficam em div oculta.
    payload = html.escape(_reviews_payload(reviews), quote=False)
    html_block = (
        f"{_BALLOON_CSS}{legend}"
        f'<div class="bgf-sbs-outer"><div class="bgf-sbs-grid">{left}{right}</div></div>'
        f'<div id="bgf-comments-data" hidden>{payload}</div>'
    )
    st.session_state["_bgf_balloon_html_cache"] = {"key": cache_key, "html": html_block}
    return html_block


def _apply_reinforcement(rev: CommentReview, new_version) -> None:
    suggestion = suggest_reinforcement(rev)
    anchor = rev.referenced_excerpt or rev.change_found
    apply_quick_comment_to_version(
        new_version,
        comment_text=suggestion,
        anchor_text=anchor,
        locations=rev.locations,
        source_ref=rev.comment_id,
    )


def render_balloon_include_panel(
    reviews: list[CommentReview],
    new_version,
    *,
    key_prefix: str = "balloon_act",
) -> None:
    """Painel Streamlit para incluir reforço (sem recarregar a página)."""
    if not new_version:
        return

    applied = get_quick_applied_ids(new_version.id)
    pending = [
        r
        for r in reviews
        if review_needs_reinforcement(r) and r.comment_id not in applied
    ]
    if not pending:
        return

    st.markdown("#### Aceitar reforço na versão nova")
    st.caption(
        "Clique no balão colorido (ou em **Aceitar**) para ver a análise, "
        "editar o texto e gravar no arquivo mais recente."
    )

    for rev in pending:
        color, label = _STATUS_COLORS.get(rev.status, ("#64748b", rev.status.value))
        col_text, col_btn = st.columns([5, 1])
        with col_text:
            st.markdown(
                f'<span style="background:{color};color:#fff;padding:2px 8px;'
                f'border-radius:4px;font-size:0.75rem;margin-right:6px;">{label}</span>'
                f"{html.escape(rev.original_comment[:110])}…",
                unsafe_allow_html=True,
            )
        with col_btn:
            if st.button(
                "Aceitar",
                key=f"{key_prefix}_inc_{rev.comment_id}",
                type="primary",
                use_container_width=True,
            ):
                st.session_state["bgf_open_cmt_id"] = rev.comment_id
                st.rerun()


def render_side_by_side_with_comment_balloons(
    path_a: str,
    type_a: str,
    path_b: str,
    type_b: str,
    reviews: list[CommentReview],
    *,
    label_a: str = "Versão base",
    label_b: str = "Versão revisada",
    sync_group: str = "cmp_sbs",
    new_version=None,
) -> None:
    """Renderiza comparação lado a lado com balões de comentário."""
    c_sync, c_full = st.columns([3, 2])
    with c_sync:
        sync_enabled = render_sync_scroll_controls(key=f"{sync_group}_sync_scroll")
    with c_full:
        render_all = st.checkbox(
            "Documento completo (todas as páginas PDF)",
            value=False,
            key=f"{sync_group}_balloon_full_pdf",
            help="Mais lento em PDFs longos. Por padrão só páginas com comentários.",
        )
    html_block = build_side_by_side_balloons_html(
        path_a,
        type_a,
        path_b,
        type_b,
        reviews,
        label_a=label_a,
        label_b=label_b,
        sync_group=sync_group,
        render_all_pages=render_all,
    )
    st.markdown(html_block, unsafe_allow_html=True)
    ensure_comment_balloon_handler(reviews, sync_enabled=sync_enabled)
    render_balloon_include_panel(reviews, new_version, key_prefix=f"{sync_group}_inc")


def _review_by_id(reviews: list[CommentReview], cid: str) -> CommentReview | None:
    for rev in reviews:
        if rev.comment_id == cid:
            return rev
    return None


@st.dialog("Análise do comentário", width="large")
def _comment_include_dialog(rev: CommentReview, new_version) -> None:
    color, status_label = _STATUS_COLORS.get(rev.status, ("#64748b", rev.status.value))
    st.markdown(
        f'<span style="background:{color};color:#fff;padding:4px 12px;'
        f'border-radius:999px;font-size:0.85rem;font-weight:600;">{status_label}</span>',
        unsafe_allow_html=True,
    )
    st.markdown("**Pedido original**")
    st.write(rev.original_comment)
    if rev.referenced_excerpt:
        st.markdown("**Trecho referenciado**")
        st.code(rev.referenced_excerpt[:800])
    st.markdown("**Análise da IA**")
    st.write(rev.justification)
    if rev.change_found:
        st.markdown("**Alteração na nova versão**")
        st.code(rev.change_found[:1200])
    if rev.suggested_response:
        st.markdown("**Sugestão de resposta**")
        st.write(rev.suggested_response)

    if not new_version:
        st.info("Versão revisada não disponível para incluir comentário.")
        return

    applied = get_quick_applied_ids(new_version.id)
    if rev.comment_id in applied:
        st.success("Sugestão já incluída na versão nova.")
        return

    if review_needs_reinforcement(rev):
        if st.button("Incluir na nova versão", type="primary", key=f"dlg_inc_{rev.comment_id}"):
            try:
                suggestion = suggest_reinforcement(rev)
                anchor = rev.referenced_excerpt or rev.change_found
                apply_quick_comment_to_version(
                    new_version,
                    comment_text=suggestion,
                    anchor_text=anchor,
                    locations=rev.locations,
                    source_ref=rev.comment_id,
                )
                st.session_state["bgf_show_save_cta"] = new_version.id
                close_comment_modal_overlay()
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    else:
        st.caption("Este comentário foi atendido — não é necessário reforço.")


def dismiss_comment_modal_overlay() -> None:
    """Fecha overlay do modal HTML (chamar em toda renderização de resultados)."""
    close_comment_modal_overlay()
