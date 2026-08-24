"""Ações de aceitar / comentar no arquivo mais recente (versão B)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

import streamlit as st

from app.core.annotation_io import AnnotationError
from app.core.comment_suggester import review_needs_reinforcement, suggest_reinforcement
from app.core.pdf_viewer import text_near_pdf_point
from app.models.schemas import CommentReview, CommentStatus
from app.utils.comments_ui import apply_quick_comment_to_version, get_quick_applied_ids
from app.utils.export_ui import get_annotated_work_path, render_prominent_save_cta

_OPEN_CMT_KEY = "bgf_open_cmt_id"
_MANUAL_DRAFT_KEY = "bgf_manual_draft"
_CONFIRM_ALL_KEY = "bgf_confirm_accept_all"
_STATUS_COLORS = {
    CommentStatus.ATTENDED: ("#16a34a", "Atendido"),
    CommentStatus.PARTIALLY: ("#ca8a04", "Atendido parcialmente"),
    CommentStatus.NOT_ATTENDED: ("#dc2626", "Não atendido"),
}

_OPEN_CMT_KEY = "bgf_open_cmt_id"
_MANUAL_DRAFT_KEY = "bgf_manual_draft"
_CONFIRM_ALL_KEY = "bgf_confirm_accept_all"


def pending_reviews(reviews: list[CommentReview] | None, version) -> list[CommentReview]:
    if not reviews or not version:
        return []
    applied = get_quick_applied_ids(version.id)
    return [
        r
        for r in reviews
        if review_needs_reinforcement(r) and r.comment_id not in applied
    ]


def consume_comment_query_actions() -> None:
    """Lê clique no balão / botão direito e abre o diálogo correspondente."""
    qp = st.query_params
    cid = qp.get("bgf_cmt")
    rc = qp.get("bgf_rc")
    if cid or rc:
        _ingest_comment_event(
            {
                "type": "cmt" if cid else "rc",
                "id": cid,
                "kind": qp.get("bgf_rc_kind"),
                "page": qp.get("bgf_rc_page"),
                "para": qp.get("bgf_rc_para"),
                "sel": unquote(str(qp.get("bgf_rc_sel") or "")),
                "x": qp.get("bgf_rc_x"),
                "y": qp.get("bgf_rc_y"),
                "x0": qp.get("bgf_rc_x0"),
                "y0": qp.get("bgf_rc_y0"),
                "x1": qp.get("bgf_rc_x1"),
                "y1": qp.get("bgf_rc_y1"),
            }
        )
        for key in list(qp.keys()):
            if str(key).startswith("bgf_"):
                del st.query_params[key]
        st.rerun()


def ingest_bridge_event(event) -> None:
    """Recebe o evento do componente Streamlit (clique direito / balão)."""
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except json.JSONDecodeError:
            return
    if not isinstance(event, dict) or not event.get("type"):
        return
    token = event.get("ts") or repr(event)
    if token == st.session_state.get("_bgf_bridge_seen"):
        return
    st.session_state["_bgf_bridge_seen"] = token
    _ingest_comment_event(event)
    st.rerun()


def _ingest_comment_event(event: dict) -> None:
    etype = str(event.get("type") or "")
    if etype == "cmt" and event.get("id"):
        st.session_state[_OPEN_CMT_KEY] = str(event["id"])
        return
    if etype != "rc":
        return

    def _f(name: str) -> float | None:
        raw = event.get(name)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    para_raw = event.get("para")
    para = None
    if para_raw not in (None, ""):
        try:
            para = int(para_raw)
        except (TypeError, ValueError):
            para = None

    x0, y0, x1, y1 = _f("x0"), _f("y0"), _f("x1"), _f("y1")
    percent_rect = None
    if None not in (x0, y0, x1, y1) and abs((x1 or 0) - (x0 or 0)) > 0.8:
        percent_rect = (x0, y0, x1, y1)

    st.session_state[_MANUAL_DRAFT_KEY] = {
        "page": int(_f("page") or 1),
        "x": _f("x") or 0.0,
        "y": _f("y") or 0.0,
        "para": para,
        "sel": str(event.get("sel") or "")[:800],
        "kind": str(event.get("kind") or "pdf"),
        "percent_rect": percent_rect,
    }


def _review_by_id(reviews: list[CommentReview], cid: str) -> CommentReview | None:
    for rev in reviews:
        if rev.comment_id == cid:
            return rev
    return None


def _mark_saved(version) -> None:
    st.session_state["bgf_show_save_cta"] = version.id
    st.session_state.pop("_bgf_balloon_html_cache", None)


def _safe_apply(version, **kwargs) -> bool:
    try:
        apply_quick_comment_to_version(version, **kwargs)
        _mark_saved(version)
        return True
    except AnnotationError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Não foi possível gravar o comentário: {exc}")
    return False


@st.dialog("Aceitar comentário", width="large")
def _accept_comment_dialog(rev: CommentReview, new_version) -> None:
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

    if not new_version:
        st.info("Versão revisada não disponível para gravar o comentário.")
        return

    applied = get_quick_applied_ids(new_version.id)
    if rev.comment_id in applied:
        st.success("Este comentário já foi gravado no arquivo mais recente.")
        if st.button("Fechar", key=f"dlg_close_{rev.comment_id}"):
            st.session_state.pop(_OPEN_CMT_KEY, None)
            st.rerun()
        return

    if not review_needs_reinforcement(rev):
        st.caption("Este comentário foi atendido — não é necessário gravar reforço.")
        if st.button("Fechar", key=f"dlg_ok_{rev.comment_id}"):
            st.session_state.pop(_OPEN_CMT_KEY, None)
            st.rerun()
        return

    txt_key = f"bgf_edit_{rev.comment_id}"
    if txt_key not in st.session_state:
        with st.spinner("Preparando texto sugerido…"):
            st.session_state[txt_key] = suggest_reinforcement(rev)

    st.markdown("**Texto que será gravado no arquivo mais recente**")
    st.caption("Edite à vontade antes de aceitar.")
    edited = st.text_area("Comentário", key=txt_key, height=160, label_visibility="collapsed")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Aceitar e gravar", type="primary", key=f"dlg_save_{rev.comment_id}"):
            if not (edited or "").strip():
                st.error("Escreva o comentário antes de gravar.")
            else:
                ok = _safe_apply(
                    new_version,
                    comment_text=edited,
                    anchor_text=rev.referenced_excerpt or rev.change_found,
                    locations=rev.locations,
                    source_ref=rev.comment_id,
                )
                if ok:
                    st.session_state.pop(_OPEN_CMT_KEY, None)
                    st.session_state.pop(txt_key, None)
                    st.rerun()
    with c2:
        if st.button("Cancelar", key=f"dlg_cancel_{rev.comment_id}"):
            st.session_state.pop(_OPEN_CMT_KEY, None)
            st.rerun()


@st.dialog("Novo comentário", width="large")
def _manual_comment_dialog(new_version, draft: dict) -> None:
    kind = draft.get("kind") or "pdf"
    page = int(draft.get("page") or 1)
    para = draft.get("para")
    sel = (draft.get("sel") or "").strip()
    path = getattr(new_version, "file_path", "") if new_version else ""

    if kind == "docx" and para is not None:
        st.caption(f"Parágrafo **{int(para) + 1}** no arquivo mais recente.")
    else:
        st.caption(f"Página **{page}** no arquivo mais recente (posição do clique).")

    if not sel and kind == "pdf" and path:
        sel = text_near_pdf_point(path, page, draft.get("x") or 0, draft.get("y") or 0)
    if sel:
        st.markdown("**Trecho no ponto / seleção**")
        st.code(sel[:600])

    text = st.text_area(
        "Escreva o comentário",
        key="bgf_manual_comment_text",
        height=140,
        placeholder="O comentário ficará neste ponto do arquivo.",
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Gravar no arquivo", type="primary", key="bgf_manual_save"):
            if not new_version:
                st.error("Arquivo mais recente não disponível.")
            elif _safe_apply(
                new_version,
                comment_text=text,
                anchor_text=sel if (draft.get("percent_rect") or kind == "docx") else None,
                percent_point=(draft.get("x"), draft.get("y")) if kind == "pdf" else None,
                percent_rect=draft.get("percent_rect") if kind == "pdf" else None,
                paragraph_index=int(para) if para is not None else None,
                page_num=page if kind == "pdf" else None,
            ):
                st.session_state.pop(_MANUAL_DRAFT_KEY, None)
                st.session_state.pop("bgf_manual_comment_text", None)
                st.rerun()
    with c2:
        if st.button("Cancelar", key="bgf_manual_cancel"):
            st.session_state.pop(_MANUAL_DRAFT_KEY, None)
            st.session_state.pop("bgf_manual_comment_text", None)
            st.rerun()


def render_open_comment_dialogs(
    reviews: list[CommentReview] | None,
    new_version,
) -> None:
    cid = st.session_state.get(_OPEN_CMT_KEY)
    if cid and reviews:
        rev = _review_by_id(reviews, str(cid))
        if rev:
            _accept_comment_dialog(rev, new_version)
            return
        st.session_state.pop(_OPEN_CMT_KEY, None)
    draft = st.session_state.get(_MANUAL_DRAFT_KEY)
    if draft and new_version:
        _manual_comment_dialog(new_version, draft)


def _accept_all(reviews: list[CommentReview], new_version) -> tuple[int, int]:
    ok = 0
    failed = 0
    for rev in reviews:
        try:
            suggestion = suggest_reinforcement(rev)
            apply_quick_comment_to_version(
                new_version,
                comment_text=suggestion,
                anchor_text=rev.referenced_excerpt or rev.change_found,
                locations=rev.locations,
                source_ref=rev.comment_id,
            )
            ok += 1
        except Exception:
            failed += 1
    if ok:
        _mark_saved(new_version)
    return ok, failed


def render_accept_and_save_bar(
    reviews: list[CommentReview] | None,
    new_version,
    *,
    key_prefix: str = "cmt_act",
) -> None:
    """Aceitar todos os não atendidos + salvar o arquivo no computador."""
    if not new_version:
        return

    pending = pending_reviews(reviews, new_version)
    fname = Path(getattr(new_version, "file_path", "") or "").name
    st.info(
        "Os comentários são gravados **no arquivo mais recente** "
        f"(`{fname}`). Clique com o **botão direito** no documento da direita "
        "para comentar no ponto (ou em um trecho selecionado). "
        "Depois use **Salvar** para baixar uma cópia na pasta que escolher."
    )

    cols = st.columns([2, 2, 3])
    with cols[0]:
        if pending:
            if st.button(
                f"Aceitar todos os não atendidos ({len(pending)})",
                type="primary",
                key=f"{key_prefix}_accept_all",
                use_container_width=True,
            ):
                st.session_state[_CONFIRM_ALL_KEY] = True
        else:
            st.caption("Nenhum reforço pendente para aceitar.")

    with cols[1]:
        work = get_annotated_work_path(new_version) or getattr(new_version, "file_path", None)
        if work and Path(work).exists():
            from app.utils.export_ui import render_browser_save_button

            render_browser_save_button(
                new_version,
                key_prefix=f"{key_prefix}_bar",
                label=None,
            )

    if st.session_state.get(_CONFIRM_ALL_KEY) and pending:
        st.warning(
            f"Isso grava **{len(pending)}** comentário(s) sugeridos pela IA em `{fname}`. "
            "Para editar o texto, aceite um a um no balão."
        )
        c_ok, c_no = st.columns(2)
        with c_ok:
            if st.button("Confirmar gravação", type="primary", key=f"{key_prefix}_confirm_all"):
                with st.spinner(f"Gravando {len(pending)} comentário(s) no arquivo…"):
                    ok, failed = _accept_all(pending, new_version)
                st.session_state.pop(_CONFIRM_ALL_KEY, None)
                if failed:
                    st.error(f"Gravados {ok}. Falharam {failed}. Feche o arquivo se estiver aberto e tente de novo.")
                else:
                    st.success(f"{ok} comentário(s) gravado(s) no arquivo mais recente.")
                st.rerun()
        with c_no:
            if st.button("Cancelar", key=f"{key_prefix}_cancel_all"):
                st.session_state.pop(_CONFIRM_ALL_KEY, None)
                st.rerun()

    if get_annotated_work_path(new_version) or st.session_state.get("bgf_show_save_cta") == getattr(
        new_version, "id", None
    ):
        render_prominent_save_cta(
            new_version,
            key_prefix=f"{key_prefix}_cta",
            message="Comentários gravados no arquivo. **Salve uma cópia** no seu computador:",
        )
