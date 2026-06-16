"""Comentários inline: trecho marcado no documento + confirmar/descartar + gravação imediata."""

from __future__ import annotations

import uuid
from pathlib import Path

import streamlit as st

from app.core.comment_suggester import (
    review_needs_reinforcement,
    suggest_for_checklist_gap,
    suggest_for_matrix_divergence,
    suggest_for_matrix_gap,
    suggest_reinforcement,
)
from app.core.document_locator import find_in_document
from app.core.comment_suggester import matrix_item_needs_comment  # noqa: F401
from app.models.schemas import (
    CommentReview,
    CommentStatus,
    CommentsReviewResult,
    DocumentCommentSource,
    MatrixParameterCheck,
    RequirementCheck,
    VersionRegressionAlert,
    VersionRegressionResult,
)
from app.utils.comments_ui import get_comments_bundle
from app.utils.document_ui import render_focused_excerpt
from app.utils.theme import section_title

_QUEUE_KEY = "inline_comment_queue"
_STATUS_BADGE = {
    CommentStatus.ATTENDED: "✅ Atendido",
    CommentStatus.PARTIALLY: "⚠️ Parcial",
    CommentStatus.NOT_ATTENDED: "❌ Não atendido",
}


def _nav_task_key(version_id: str, key_prefix: str) -> str:
    return f"{key_prefix}_inline_nav_task_{version_id}"


def _nav_idx_key(version_id: str, key_prefix: str) -> str:
    return f"{key_prefix}_inline_nav_idx_{version_id}"


def _rebuild_flag_key(version_id: str, key_prefix: str) -> str:
    return f"{key_prefix}_rebuild_{version_id}"


def mark_comment_queue_for_rebuild(version_id: str, key_prefix: str = "inl") -> None:
    """Marca a fila para ser recriada na próxima renderização (ex.: após nova análise)."""
    st.session_state[_rebuild_flag_key(version_id, key_prefix)] = True


def mark_queue_item_applied(version_id: str, source_ref: str) -> None:
    """Marca item da fila inline como gravado (ex.: após comentário rápido na aba de verificação)."""
    for task in _queue_store().get(version_id, []):
        if task.get("source_ref") == source_ref:
            task["status"] = "applied"


def _queue_store() -> dict[str, list[dict]]:
    if _QUEUE_KEY not in st.session_state:
        st.session_state[_QUEUE_KEY] = {}
    return st.session_state[_QUEUE_KEY]


def _pending_tasks(queue: list[dict]) -> list[dict]:
    return [t for t in queue if t.get("status") == "pending"]


def _clamp_idx(idx: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(int(idx), total - 1))


def _task_page_label(task: dict) -> str:
    locs = task.get("locations") or []
    if locs and isinstance(locs[0], dict):
        page = locs[0].get("page")
        if page:
            return f"Pág.{page} · "
    return ""


def _task_short_label(task: dict, index: int, total: int) -> str:
    preview = (task.get("comment_text") or "").replace("\n", " ").strip()[:72]
    kind = task.get("kind", "suggestion")
    prefix = "↩ " if kind == "unattended" else ""
    src = (task.get("source") or "").replace("_", " ")[:18]
    return f"{index + 1}/{total} {prefix}{_task_page_label(task)}{preview}… [{src}]"


def _sync_nav_state(
    pending: list[dict],
    version_id: str,
    key_prefix: str,
    *,
    preferred_idx: int | None = None,
) -> tuple[dict, int]:
    """Fonte única de verdade: índice na lista pending + task_id."""
    if not pending:
        raise ValueError("Nenhuma sugestão pendente")

    idx_key = _nav_idx_key(version_id, key_prefix)
    task_key = _nav_task_key(version_id, key_prefix)
    by_id = {t["task_id"]: t for t in pending}

    if preferred_idx is not None:
        idx = _clamp_idx(preferred_idx, len(pending))
    else:
        stored_idx = st.session_state.get(idx_key, 0)
        idx = _clamp_idx(stored_idx, len(pending))
        task_id = st.session_state.get(task_key)
        if task_id in by_id:
            idx = pending.index(by_id[task_id])

    task = pending[idx]
    st.session_state[idx_key] = idx
    st.session_state[task_key] = task["task_id"]
    return task, idx


def _goto_idx(
    pending: list[dict],
    version_id: str,
    key_prefix: str,
    new_idx: int,
) -> None:
    if not pending:
        _clear_nav_state(version_id, key_prefix)
        return
    idx = _clamp_idx(new_idx, len(pending))
    st.session_state[_nav_idx_key(version_id, key_prefix)] = idx
    st.session_state[_nav_task_key(version_id, key_prefix)] = pending[idx]["task_id"]


def _clear_nav_state(version_id: str, key_prefix: str) -> None:
    st.session_state.pop(_nav_idx_key(version_id, key_prefix), None)
    st.session_state.pop(_nav_task_key(version_id, key_prefix), None)


def _after_action_navigate(
    pending_before: list[dict],
    current_task_id: str,
    version_id: str,
    key_prefix: str,
) -> None:
    """Após confirmar/descartar: mantém posição ou avança para o próximo pendente."""
    queue = _queue_store().get(version_id, [])
    pending_after = _pending_tasks(queue)
    if not pending_after:
        _clear_nav_state(version_id, key_prefix)
        return

    try:
        old_idx = next(i for i, t in enumerate(pending_before) if t["task_id"] == current_task_id)
    except StopIteration:
        old_idx = 0

    if old_idx < len(pending_after):
        new_idx = old_idx
    elif old_idx > 0:
        new_idx = old_idx - 1
    else:
        new_idx = 0

    _goto_idx(pending_after, version_id, key_prefix, new_idx)


def _build_task(
    *,
    comment_text: str,
    anchor_text: str | None,
    source: DocumentCommentSource,
    source_ref: str | None = None,
    kind: str = "suggestion",
    original_comment: str | None = None,
    review_status: str | None = None,
    file_path: str | None = None,
    categoria: str | None = None,
) -> dict:
    locs = []
    if file_path and anchor_text:
        locs = [loc.model_dump() for loc in find_in_document(file_path, anchor_text)]
    return {
        "task_id": str(uuid.uuid4())[:8],
        "comment_text": comment_text,
        "anchor_text": anchor_text,
        "locations": locs,
        "source": source.value,
        "source_ref": source_ref,
        "kind": kind,
        "original_comment": original_comment,
        "review_status": review_status,
        "status": "pending",
        "categoria": categoria,
    }


def _enqueue_tasks(version_id: str, tasks: list[dict], *, replace: bool = False) -> None:
    store = _queue_store()
    if replace or version_id not in store:
        store[version_id] = []
    existing_ids = {t["task_id"] for t in store[version_id]}
    for t in tasks:
        if t["task_id"] not in existing_ids:
            store[version_id].append(t)
            existing_ids.add(t["task_id"])


def _tasks_from_analysis(
    file_path: str,
    *,
    matrix_checks: list[MatrixParameterCheck] | None = None,
    checklist_checks: list[RequirementCheck] | None = None,
    matrix_items: list | None = None,
    regressions: list[VersionRegressionAlert] | None = None,
) -> list[dict]:
    tasks: list[dict] = []
    if matrix_checks:
        for ch in matrix_checks:
            if ch.present and ch.aligns_with_proposal is not False:
                continue
            text = suggest_for_matrix_gap(ch)
            anchor = ch.found_excerpt or ch.proposal_excerpt or ch.page_hint
            tasks.append(
                _build_task(
                    comment_text=text,
                    anchor_text=anchor,
                    source=DocumentCommentSource.MATRIX_GAP,
                    source_ref=ch.item_id,
                    file_path=file_path,
                    categoria=ch.categoria,
                )
            )
    if checklist_checks:
        for ch in checklist_checks:
            if ch.present:
                continue
            tasks.append(
                _build_task(
                    comment_text=suggest_for_checklist_gap(ch),
                    anchor_text=ch.found_excerpt or ch.page_hint,
                    source=DocumentCommentSource.CHECKLIST_GAP,
                    source_ref=ch.requirement_id,
                    file_path=file_path,
                )
            )
    if matrix_items:
        for it in matrix_items:
            if not matrix_item_needs_comment(it):  # type: ignore[arg-type]
                continue
            tasks.append(
                _build_task(
                    comment_text=suggest_for_matrix_divergence(it),
                    anchor_text=it.contrato_evidencia or it.proposta_evidencia,
                    source=DocumentCommentSource.MATRIX_DIVERGENCE,
                    source_ref=it.item_id,
                    file_path=file_path,
                    categoria=getattr(it, "categoria", None),
                )
            )
    if regressions:
        for alert in regressions:
            anchor = alert.contract_excerpt or alert.proposal_excerpt
            text = (
                f"[Regressão na {alert.title}] {alert.description} "
                f"Impacto: {alert.negotiation_impact}"
            )
            tasks.append(
                _build_task(
                    comment_text=text[:1200],
                    anchor_text=anchor,
                    source=DocumentCommentSource.REINFORCEMENT,
                    source_ref=alert.alert_id,
                    kind="regression",
                    file_path=file_path,
                )
            )
    return tasks


def _tasks_from_verification(
    verification: CommentsReviewResult,
    file_path: str,
) -> list[dict]:
    tasks: list[dict] = []
    for rev in verification.reviews:
        if not review_needs_reinforcement(rev):
            continue
        anchor = rev.referenced_excerpt or rev.change_found
        locs = find_in_document(file_path, anchor or rev.original_comment[:120])
        tasks.append(
            {
                "task_id": f"ver_{rev.comment_id}",
                "comment_text": suggest_reinforcement(rev),
                "anchor_text": anchor,
                "locations": [loc.model_dump() for loc in locs],
                "source": DocumentCommentSource.REINFORCEMENT.value,
                "source_ref": rev.comment_id,
                "kind": "unattended",
                "original_comment": rev.original_comment,
                "review_status": rev.status.value,
                "status": "pending",
            }
        )
    return tasks


def _apply_task_to_file(
    version,
    task: dict,
    bundle,
) -> str:
    from app.models.schemas import TextLocation
    from app.utils.comments_ui import apply_quick_comment_to_version

    locs = [TextLocation.model_validate(x) for x in task.get("locations") or []]
    work = apply_quick_comment_to_version(
        version,
        comment_text=task["comment_text"],
        anchor_text=task.get("anchor_text"),
        locations=locs,
        source_ref=task.get("source_ref"),
    )
    bundle.annotated_file_path = work
    return work


def _render_comment_navigator(
    pending: list[dict],
    idx: int,
    *,
    version_id: str,
    key_prefix: str,
) -> None:
    """Barra de navegação entre sugestões pendentes."""
    total = len(pending)
    st.markdown("**Navegar entre sugestões**")

    c_prev, c_jump, c_next, c_pos = st.columns([1, 3, 1, 1])
    with c_prev:
        if st.button(
            "◀ Anterior",
            key=f"{key_prefix}_nav_prev_{version_id}",
            disabled=idx <= 0,
            use_container_width=True,
        ):
            _goto_idx(pending, version_id, key_prefix, idx - 1)
            st.rerun()
    with c_next:
        if st.button(
            "Próximo ▶",
            key=f"{key_prefix}_nav_next_{version_id}",
            disabled=idx >= total - 1,
            use_container_width=True,
        ):
            _goto_idx(pending, version_id, key_prefix, idx + 1)
            st.rerun()
    with c_pos:
        st.caption(f"**{idx + 1}** / {total}")

    with c_jump:
        labels = [_task_short_label(t, i, total) for i, t in enumerate(pending)]
        # Sem key no selectbox: índice vem só do session_state (evita conflito com botões)
        picked = st.selectbox(
            "Ir diretamente para",
            options=list(range(total)),
            index=idx,
            format_func=lambda i: labels[i],
            label_visibility="collapsed",
            key=f"{key_prefix}_nav_sel_{version_id}_{idx}",
        )
        if picked != idx:
            _goto_idx(pending, version_id, key_prefix, picked)
            st.rerun()

    with st.expander(f"Lista rápida ({total} pendentes)", expanded=total <= 6):
        cols = st.columns(min(total, 4))
        for i, t in enumerate(pending):
            col = cols[i % len(cols)]
            active = i == idx
            label = f"{'● ' if active else ''}{i + 1}"
            if col.button(
                label,
                key=f"{key_prefix}_nav_chip_{version_id}_{t['task_id']}",
                type="primary" if active else "secondary",
                use_container_width=True,
            ):
                _goto_idx(pending, version_id, key_prefix, i)
                st.rerun()


def render_inline_comments_workspace(
    version,
    *,
    matrix_checks: list[MatrixParameterCheck] | None = None,
    checklist_checks: list[RequirementCheck] | None = None,
    matrix_items: list | None = None,
    verification: CommentsReviewResult | None = None,
    regression: VersionRegressionResult | None = None,
    key_prefix: str = "inl",
    rebuild_queue: bool = False,
) -> None:
    section_title("Comentar no PDF")
    st.caption(
        "Sugestões geradas a partir da análise. Revise trecho a trecho e grave com **Comentar no PDF**."
    )

    bundle = get_comments_bundle(version.id, version.contract_id)
    file_path = bundle.annotated_file_path or version.file_path
    file_type = version.file_type
    vid = version.id

    rebuild_flag = st.session_state.pop(_rebuild_flag_key(vid, key_prefix), False)
    do_rebuild = rebuild_queue or rebuild_flag
    has_sources = bool(
        matrix_checks
        or checklist_checks
        or matrix_items
        or (verification and verification.reviews)
        or (regression and regression.alerts)
    )
    queue_missing = vid not in _queue_store()

    if do_rebuild or (queue_missing and has_sources):
        new_tasks = _tasks_from_analysis(
            version.file_path,
            matrix_checks=matrix_checks,
            checklist_checks=checklist_checks,
            matrix_items=matrix_items,
            regressions=regression.alerts if regression else None,
        )
        if verification:
            new_tasks.extend(_tasks_from_verification(verification, version.file_path))
        _enqueue_tasks(vid, new_tasks, replace=do_rebuild)
        if do_rebuild or queue_missing:
            fresh_pending = _pending_tasks(_queue_store().get(vid, []))
            if fresh_pending:
                _goto_idx(fresh_pending, vid, key_prefix, 0)

    queue = _queue_store().get(vid, [])
    pending = _pending_tasks(queue)
    applied = sum(1 for t in queue if t.get("status") == "applied")
    discarded = sum(1 for t in queue if t.get("status") == "discarded")

    if queue:
        st.caption(
            f"Fila: **{len(pending)}** pendente(s) · **{applied}** gravado(s) · **{discarded}** descartado(s)"
        )

    if pending:
        if st.button(
            f"✅ Comentar todos no PDF ({len(pending)})",
            type="primary",
            key=f"{key_prefix}_apply_all",
        ):
            try:
                with st.spinner(f"Gravando {len(pending)} comentário(s)..."):
                    for task in list(pending):
                        _apply_task_to_file(version, task, bundle)
                        task["status"] = "applied"
                _clear_nav_state(vid, key_prefix)
                st.success(f"{len(pending)} comentário(s) gravado(s).")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if not pending:
        st.success("Nenhuma sugestão pendente na fila.")
        from app.utils.export_ui import render_annotated_export_panel

        render_annotated_export_panel(
            version,
            key_prefix=f"{key_prefix}_export",
            title="Salvar documento comentado",
        )
        return

    try:
        task, idx = _sync_nav_state(pending, vid, key_prefix)
    except ValueError:
        st.success("Nenhuma sugestão pendente na fila.")
        return

    _render_comment_navigator(pending, idx, version_id=vid, key_prefix=key_prefix)

    st.progress((idx + 1) / len(pending), text=f"Sugestão {idx + 1} de {len(pending)}")

    kind = task.get("kind", "suggestion")
    if kind == "unattended":
        try:
            rev_status = CommentStatus(task["review_status"])
        except (ValueError, KeyError):
            rev_status = CommentStatus.NOT_ATTENDED
        badge = _STATUS_BADGE.get(rev_status, "❌ Pendente")
        st.error(f"{badge} — Comentário anterior não atendido")
        if task.get("original_comment"):
            st.markdown(f"**Comentário original:** {task['original_comment']}")

    from app.models.schemas import TextLocation

    locs = [TextLocation.model_validate(x) for x in (task.get("locations") or [])]
    if not locs and task.get("anchor_text"):
        locs = find_in_document(file_path, task["anchor_text"])
        task["locations"] = [loc.model_dump() for loc in locs]

    col_doc, col_act = st.columns([3, 2])
    with col_doc:
        render_focused_excerpt(
            file_path,
            file_type,
            locs,
            caption="Trecho marcado",
        )
        if task.get("anchor_text"):
            st.caption("Âncora")
            st.code(task["anchor_text"][:600])

    with col_act:
        if task.get("categoria"):
            st.caption(f"Categoria: **{task['categoria']}**")

        txt_key = f"{key_prefix}_txt_{task['task_id']}"
        if txt_key not in st.session_state:
            st.session_state[txt_key] = task["comment_text"]

        anc_key = f"{key_prefix}_anc_{task['task_id']}"
        if anc_key not in st.session_state:
            st.session_state[anc_key] = task.get("anchor_text") or ""

        edited = st.text_area(
            "Texto do comentário",
            height=160,
            key=txt_key,
        )
        manual_anchor = st.text_input(
            "Ajustar trecho âncora (opcional)",
            key=anc_key,
        )

        if st.button(
            "✅ Comentar no PDF",
            type="primary",
            key=f"{key_prefix}_ok_{task['task_id']}",
            use_container_width=True,
        ):
            task["comment_text"] = edited
            if manual_anchor.strip():
                task["anchor_text"] = manual_anchor.strip()
                task["locations"] = [
                    loc.model_dump()
                    for loc in find_in_document(file_path, task["anchor_text"])
                ]
            try:
                _apply_task_to_file(version, task, bundle)
                task["status"] = "applied"
                _after_action_navigate(pending, task["task_id"], vid, key_prefix)
                st.session_state.pop(txt_key, None)
                st.session_state.pop(anc_key, None)
                st.success("Comentário gravado no documento.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        if st.button("Descartar sugestão", key=f"{key_prefix}_no_{task['task_id']}"):
            task["status"] = "discarded"
            _after_action_navigate(pending, task["task_id"], vid, key_prefix)
            st.session_state.pop(txt_key, None)
            st.session_state.pop(anc_key, None)
            st.rerun()

    from app.utils.export_ui import get_annotated_work_path, render_annotated_export_panel

    if get_annotated_work_path(version):
        st.divider()
        render_annotated_export_panel(
            version,
            key_prefix=f"{key_prefix}_export",
            title="Salvar documento comentado",
        )
