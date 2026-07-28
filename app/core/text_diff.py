"""Diff textual determinístico — estilo PDF24 (vermelho removido, verde adicionado, amarelo movido)."""

from __future__ import annotations

import difflib
import html
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from diff_match_patch import diff_match_patch

from app.core.extractor import normalize_text
from app.models.schemas import TextDiffHunk, TextDiffResult

DMP = diff_match_patch()
_PARA_SEP = "\x1e"

_DIFF_CSS = """
<style>
.bgf-diff-wrap { font-family: Georgia, 'Times New Roman', serif; line-height: 1.55; }
.bgf-diff-col { border: 1px solid #D6E2F0; border-radius: 8px; padding: 12px 14px;
  background: #fff; max-height: 70vh; overflow-y: auto; }
.bgf-diff-col.bgf-sync-scroll { overflow-y: auto; }
.bgf-diff-col h4 { margin: 0 0 10px; font-size: 0.95rem; color: #0A3D7A; }
.bgf-diff-side { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.bgf-diff-removed { color: #b91c1c; text-decoration: line-through; background: #fef2f2; }
.bgf-diff-added { color: #15803d; text-decoration: underline; background: #f0fdf4; }
.bgf-diff-moved { color: #a16207; background: #fef9c3; }
.bgf-diff-same { color: #0D2137; }
.bgf-diff-legend { display: flex; flex-wrap: wrap; gap: 16px; margin: 8px 0 12px; font-size: 0.85rem; }
.bgf-diff-legend span { display: inline-flex; align-items: center; gap: 6px; }
.bgf-diff-dot-same { width: 10px; height: 10px; border-radius: 50%; background: #0D2137; }
.bgf-diff-dot-add { width: 10px; height: 10px; border-radius: 50%; background: #15803d; }
.bgf-diff-dot-rem { width: 10px; height: 10px; border-radius: 50%; background: #b91c1c; }
.bgf-diff-dot-mov { width: 10px; height: 10px; border-radius: 50%; background: #ca8a04; }
.bgf-diff-inline { border: 1px solid #D6E2F0; border-radius: 8px; padding: 12px 14px;
  background: #fff; max-height: 70vh; overflow-y: auto; }
</style>
"""


def _paragraphs(text: str) -> list[str]:
    norm = normalize_text(text)
    if not norm:
        return []
    parts = [p.strip() for p in norm.split("\n\n") if p.strip()]
    return parts if parts else [norm]


def _join_paragraphs(parts: list[str]) -> str:
    return _PARA_SEP.join(parts)


def _split_joined(joined: str) -> list[str]:
    if not joined:
        return []
    return [p for p in joined.split(_PARA_SEP) if p]


def _escape_para(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def _new_hunk(
    change_type: str,
    *,
    text_a: str | None = None,
    text_b: str | None = None,
) -> TextDiffHunk:
    return TextDiffHunk(
        hunk_id=str(uuid.uuid4())[:8],
        change_type=change_type,
        text_a=text_a,
        text_b=text_b,
    )


def _emit_rem_add_block(rem_parts: list[str], add_parts: list[str]) -> list[TextDiffHunk]:
    """
    Converte um bloco rem+add do DMP em hunks.
    Parágrafos com texto idêntico viram 'moved'; o restante é pareado como modified/rem/add.
    """
    add_by_text: dict[str, deque[int]] = defaultdict(deque)
    for j, text in enumerate(add_parts):
        add_by_text[text].append(j)

    move_rem: set[int] = set()
    move_add: set[int] = set()
    for i, text in enumerate(rem_parts):
        queue = add_by_text.get(text)
        if queue:
            j = queue.popleft()
            move_rem.add(i)
            move_add.add(j)

    out: list[TextDiffHunk] = []
    rem_queue: list[str] = []
    add_queue: list[str] = []

    for i, text in enumerate(rem_parts):
        if i in move_rem:
            out.append(_new_hunk("moved", text_a=text))
        else:
            rem_queue.append(text)

    for j, text in enumerate(add_parts):
        if j in move_add:
            out.append(_new_hunk("moved", text_b=text))
        else:
            add_queue.append(text)

    pairs = max(len(rem_queue), len(add_queue))
    for k in range(pairs):
        ra = rem_queue[k] if k < len(rem_queue) else None
        rb = add_queue[k] if k < len(add_queue) else None
        if ra and rb:
            if ra == rb:
                out.append(_new_hunk("moved", text_a=ra))
                out.append(_new_hunk("moved", text_b=rb))
            else:
                out.append(_new_hunk("modified", text_a=ra, text_b=rb))
        elif ra:
            out.append(_new_hunk("removed", text_a=ra))
        elif rb:
            out.append(_new_hunk("added", text_b=rb))
    return out


def _detect_moved_paragraphs(hunks: list[TextDiffHunk]) -> list[TextDiffHunk]:
    """Pareia removed↔added com texto idêntico e reclassifica como moved (sem IA)."""
    added_by_text: dict[str, deque[int]] = defaultdict(deque)
    for i, h in enumerate(hunks):
        if h.change_type == "added" and h.text_b:
            added_by_text[h.text_b].append(i)

    used_added: set[int] = set()
    used_removed: set[int] = set()
    for i, h in enumerate(hunks):
        if h.change_type != "removed" or not h.text_a:
            continue
        queue = added_by_text.get(h.text_a)
        if not queue:
            continue
        while queue and queue[0] in used_added:
            queue.popleft()
        if not queue:
            continue
        j = queue.popleft()
        used_added.add(j)
        used_removed.add(i)

    if not used_removed:
        return hunks

    out: list[TextDiffHunk] = []
    for i, h in enumerate(hunks):
        if i in used_removed:
            out.append(
                TextDiffHunk(
                    hunk_id=h.hunk_id,
                    change_type="moved",
                    text_a=h.text_a,
                    text_b=None,
                )
            )
        elif i in used_added:
            out.append(
                TextDiffHunk(
                    hunk_id=h.hunk_id,
                    change_type="moved",
                    text_a=None,
                    text_b=h.text_b,
                )
            )
        else:
            out.append(h)
    return out


def _count_change_types(hunks: list[TextDiffHunk]) -> tuple[int, int, int, int]:
    added = removed = modified = 0
    moved_from = moved_to = 0
    for h in hunks:
        if h.change_type == "added":
            added += 1
        elif h.change_type == "removed":
            removed += 1
        elif h.change_type == "modified":
            modified += 1
        elif h.change_type == "moved":
            if h.text_a and not h.text_b:
                moved_from += 1
            elif h.text_b and not h.text_a:
                moved_to += 1
            else:
                # hunk único com ambos os lados — conta como 1 par
                moved_from += 1
                moved_to += 1
    moved = min(moved_from, moved_to) if (moved_from or moved_to) else 0
    # se só um lado sobrar (inconsistência), ainda reporta o máximo coerente
    if moved == 0 and (moved_from or moved_to):
        moved = max(moved_from, moved_to)
    return added, removed, modified, moved


def compute_text_diff(
    text_a: str,
    text_b: str,
    *,
    contract_id: str = "",
    label_a: str = "Base",
    label_b: str = "Revisada",
) -> TextDiffResult:
    """Diff em nível de parágrafo com diff-match-patch + detecção de moves."""
    pa = _paragraphs(text_a)
    pb = _paragraphs(text_b)
    joined_a = _join_paragraphs(pa)
    joined_b = _join_paragraphs(pb)

    diffs = DMP.diff_main(joined_a, joined_b)
    DMP.diff_cleanupSemantic(diffs)

    hunks: list[TextDiffHunk] = []
    i = 0
    while i < len(diffs):
        op, chunk = diffs[i]
        if op == 0:
            for para in _split_joined(chunk):
                hunks.append(_new_hunk("unchanged", text_a=para, text_b=para))
            i += 1
        elif op == -1 and i + 1 < len(diffs) and diffs[i + 1][0] == 1:
            rem_parts = _split_joined(diffs[i][1])
            add_parts = _split_joined(diffs[i + 1][1])
            hunks.extend(_emit_rem_add_block(rem_parts, add_parts))
            i += 2
        elif op == -1:
            for para in _split_joined(chunk):
                hunks.append(_new_hunk("removed", text_a=para))
            i += 1
        else:
            for para in _split_joined(chunk):
                hunks.append(_new_hunk("added", text_b=para))
            i += 1

    hunks = _detect_moved_paragraphs(hunks)
    added, removed, modified, moved = _count_change_types(hunks)

    total = max(len(pa), len(pb), 1)
    # Moves não alteram o conteúdo — não penalizam a similaridade como rem/add
    changed_count = added + removed + modified
    similarity = max(0.0, min(1.0, 1.0 - changed_count / total))

    side_html = render_side_by_side_html(text_a, text_b, label_a=label_a, label_b=label_b, hunks=hunks)
    inline_html = render_inline_diff_html(text_a, text_b, hunks=hunks)

    return TextDiffResult(
        contract_id=contract_id,
        version_a_label=label_a,
        version_b_label=label_b,
        hunks=hunks,
        paragraphs_added=added,
        paragraphs_removed=removed,
        paragraphs_modified=modified,
        paragraphs_moved=moved,
        similarity_score=round(similarity, 4),
        side_by_side_html=side_html,
        inline_diff_html=inline_html,
        analysis_timestamp=datetime.now(timezone.utc),
    )


def changed_hunks(hunks: list[TextDiffHunk]) -> list[TextDiffHunk]:
    """Retorna apenas parágrafos com diferença (added, removed, modified, moved)."""
    return [h for h in hunks if h.change_type != "unchanged"]


def paragraph_diff_hunks(
    text_a: str,
    text_b: str,
    *,
    context_paragraphs: int = 2,
) -> list[TextDiffHunk]:
    """
    Diff em nível de parágrafo para revisão de comentários.
    Cada bloco alterado inclui N parágrafos vizinhos (contexto) para a IA.
    """
    pa = _paragraphs(text_a)
    pb = _paragraphs(text_b)
    matcher = difflib.SequenceMatcher(None, pa, pb)
    hunks: list[TextDiffHunk] = []
    ctx = max(0, int(context_paragraphs))

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        a_lo = max(0, i1 - ctx)
        a_hi = min(len(pa), i2 + ctx)
        b_lo = max(0, j1 - ctx)
        b_hi = min(len(pb), j2 + ctx)
        ctx_before_a = "\n\n".join(pa[a_lo:i1]).strip() if i1 > a_lo else ""
        ctx_after_a = "\n\n".join(pa[i2:a_hi]).strip() if a_hi > i2 else ""
        ctx_before_b = "\n\n".join(pb[b_lo:j1]).strip() if j1 > b_lo else ""
        ctx_after_b = "\n\n".join(pb[j2:b_hi]).strip() if b_hi > j2 else ""

        def _wrap(core: str | None, before: str, after: str) -> str | None:
            if core is None and not before and not after:
                return None
            parts = [p for p in (before, core or "", after) if p]
            return "\n\n".join(parts) if parts else core

        if tag == "replace":
            span = max(i2 - i1, j2 - j1)
            for k in range(span):
                ra = pa[i1 + k] if i1 + k < i2 else None
                rb = pb[j1 + k] if j1 + k < j2 else None
                # Contexto só no primeiro/último item do span para não repetir
                before_a = ctx_before_a if k == 0 else ""
                after_a = ctx_after_a if k == span - 1 else ""
                before_b = ctx_before_b if k == 0 else ""
                after_b = ctx_after_b if k == span - 1 else ""
                if ra and rb:
                    hunks.append(
                        TextDiffHunk(
                            hunk_id=str(uuid.uuid4())[:8],
                            change_type="modified",
                            text_a=_wrap(ra, before_a, after_a),
                            text_b=_wrap(rb, before_b, after_b),
                        )
                    )
                elif ra:
                    hunks.append(
                        TextDiffHunk(
                            hunk_id=str(uuid.uuid4())[:8],
                            change_type="removed",
                            text_a=_wrap(ra, before_a, after_a),
                            text_b=None,
                        )
                    )
                elif rb:
                    hunks.append(
                        TextDiffHunk(
                            hunk_id=str(uuid.uuid4())[:8],
                            change_type="added",
                            text_a=None,
                            text_b=_wrap(rb, before_b, after_b),
                        )
                    )
        elif tag == "delete":
            core = "\n\n".join(pa[i1:i2])
            hunks.append(
                TextDiffHunk(
                    hunk_id=str(uuid.uuid4())[:8],
                    change_type="removed",
                    text_a=_wrap(core, ctx_before_a, ctx_after_a),
                    text_b=_wrap(None, ctx_before_b, ctx_after_b) if (ctx_before_b or ctx_after_b) else None,
                )
            )
        elif tag == "insert":
            core = "\n\n".join(pb[j1:j2])
            hunks.append(
                TextDiffHunk(
                    hunk_id=str(uuid.uuid4())[:8],
                    change_type="added",
                    text_a=_wrap(None, ctx_before_a, ctx_after_a) if (ctx_before_a or ctx_after_a) else None,
                    text_b=_wrap(core, ctx_before_b, ctx_after_b),
                )
            )
    return hunks


def format_hunk_block(hunk: TextDiffHunk, *, index: int | None = None) -> str:
    """Formata um bloco de diff (com contexto vizinho) para envio à IA."""
    label = f"Bloco {index} — " if index is not None else ""
    if hunk.change_type == "added":
        return (
            f"{label}[ADICIONADO]\n"
            f"(trecho novo + contexto vizinho)\n"
            f"{hunk.text_b or ''}"
        )
    if hunk.change_type == "removed":
        return (
            f"{label}[REMOVIDO]\n"
            f"(trecho removido + contexto vizinho)\n"
            f"{hunk.text_a or ''}"
        )
    if hunk.change_type == "moved":
        text = hunk.text_b or hunk.text_a or ""
        side = "destino" if hunk.text_b else "origem"
        return (
            f"{label}[MOVIDO — {side}]\n"
            f"(mesmo texto em outra posição)\n"
            f"{text}"
        )
    if hunk.change_type == "modified":
        return (
            f"{label}[ALTERADO]\n"
            f"Antes (com contexto): {hunk.text_a or '(vazio)'}\n"
            f"Depois (com contexto): {hunk.text_b or '(vazio)'}"
        )
    return ""


def compile_changed_blocks_digest(
    hunks: list[TextDiffHunk],
    *,
    max_chars: int = 14000,
    max_blocks: int = 40,
) -> str:
    """Compilado de todas as diferenças textuais entre as versões."""
    changed = changed_hunks(hunks) if any(h.change_type == "unchanged" for h in hunks) else hunks
    if not changed:
        return "(nenhuma diferença textual entre as versões)"
    parts: list[str] = []
    total = 0
    for i, hunk in enumerate(changed[:max_blocks], 1):
        block = format_hunk_block(hunk, index=i)
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    omitted = len(changed) - len(parts)
    digest = "\n\n".join(parts)
    if omitted > 0:
        digest += f"\n\n(... {omitted} bloco(s) omitido(s) por limite de tamanho)"
    return digest


def _diff_legend_html() -> str:
    return (
        '<div class="bgf-diff-legend">'
        '<span><i class="bgf-diff-dot-same"></i> Mesmo</span>'
        '<span><i class="bgf-diff-dot-add"></i> Novo</span>'
        '<span><i class="bgf-diff-dot-rem"></i> Removido</span>'
        '<span><i class="bgf-diff-dot-mov"></i> Movido</span>'
        "</div>"
    )


def render_side_by_side_html(
    text_a: str,
    text_b: str,
    *,
    label_a: str = "Versão base",
    label_b: str = "Versão revisada",
    hunks: list[TextDiffHunk] | None = None,
    sync_group: str = "bgf-text-diff",
) -> str:
    """Duas colunas: esquerda com remoções/origem, direita com adições/destino."""
    if hunks is None:
        hunks = compute_text_diff(text_a, text_b).hunks

    left_parts: list[str] = []
    right_parts: list[str] = []
    for h in hunks:
        if h.change_type == "unchanged":
            esc = _escape_para(h.text_a or "")
            left_parts.append(f'<span class="bgf-diff-same">{esc}</span>')
            right_parts.append(f'<span class="bgf-diff-same">{esc}</span>')
        elif h.change_type == "removed":
            left_parts.append(f'<span class="bgf-diff-removed">{_escape_para(h.text_a or "")}</span>')
        elif h.change_type == "added":
            right_parts.append(f'<span class="bgf-diff-added">{_escape_para(h.text_b or "")}</span>')
        elif h.change_type == "moved":
            if h.text_a:
                left_parts.append(f'<span class="bgf-diff-moved">{_escape_para(h.text_a)}</span>')
            if h.text_b:
                right_parts.append(f'<span class="bgf-diff-moved">{_escape_para(h.text_b)}</span>')
        elif h.change_type == "modified":
            if h.text_a:
                left_parts.append(f'<span class="bgf-diff-removed">{_escape_para(h.text_a)}</span>')
            if h.text_b:
                right_parts.append(f'<span class="bgf-diff-added">{_escape_para(h.text_b)}</span>')

    left_body = "<br><br>".join(left_parts) or "<em>(vazio)</em>"
    right_body = "<br><br>".join(right_parts) or "<em>(vazio)</em>"
    return (
        f"{_DIFF_CSS}{_diff_legend_html()}"
        f'<div class="bgf-diff-wrap bgf-diff-side" data-sync-group="{html.escape(sync_group)}">'
        f'<div class="bgf-diff-col bgf-sync-scroll" data-sync-group="{html.escape(sync_group)}">'
        f"<h4>{html.escape(label_a)}</h4>{left_body}</div>"
        f'<div class="bgf-diff-col bgf-sync-scroll" data-sync-group="{html.escape(sync_group)}">'
        f"<h4>{html.escape(label_b)}</h4>{right_body}</div>"
        f"</div>"
    )


def render_inline_diff_html(
    text_a: str,
    text_b: str,
    *,
    hunks: list[TextDiffHunk] | None = None,
) -> str:
    """Visão única mesclada com marcações inline."""
    if hunks is None:
        hunks = compute_text_diff(text_a, text_b).hunks

    parts: list[str] = []
    for h in hunks:
        if h.change_type == "unchanged":
            parts.append(f'<span class="bgf-diff-same">{_escape_para(h.text_a or "")}</span>')
        elif h.change_type == "removed":
            parts.append(f'<span class="bgf-diff-removed">{_escape_para(h.text_a or "")}</span>')
        elif h.change_type == "added":
            parts.append(f'<span class="bgf-diff-added">{_escape_para(h.text_b or "")}</span>')
        elif h.change_type == "moved":
            text = h.text_b or h.text_a or ""
            parts.append(f'<span class="bgf-diff-moved">{_escape_para(text)}</span>')
        elif h.change_type == "modified":
            if h.text_a:
                parts.append(f'<span class="bgf-diff-removed">{_escape_para(h.text_a)}</span>')
            if h.text_b:
                parts.append(f'<span class="bgf-diff-added">{_escape_para(h.text_b)}</span>')

    body = "<br><br>".join(parts) or "<em>(sem diferenças)</em>"
    return f'{_DIFF_CSS}<div class="bgf-diff-wrap bgf-diff-inline">{body}</div>'


def get_html_diff(text_a: str, text_b: str) -> str:
    """Alias compatível com test_differ.py — diff inline mesclado."""
    return render_inline_diff_html(text_a, text_b)
