"""Diff textual determinístico — estilo PDF24 (vermelho removido, verde adicionado, amarelo movido)."""

from __future__ import annotations

import difflib
import html
import re
import unicodedata
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from app.core.extractor import normalize_text
from app.models.schemas import TextDiffHunk, TextDiffResult

# Apenas chave normalizada idêntica conta como move (sem fuzzy de edição real).
_BULLET_CHARS = r"[•●▪◦‣⁃∙·\*]"
_MATCH_WS_RE = re.compile(r"\s+")
_MATCH_BULLET_RE = re.compile(rf"{_BULLET_CHARS}\s*")
_MATCH_PAGEBREAK_RE = re.compile(r"[\f\u000c]+")

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


def _match_key(text: str) -> str:
    """
    Chave conservadora para parear trechos movidos.
    Colapsa whitespace/quebra de página e normaliza bullets, sem casefold
    (mudança de maiúsculas continua sendo alteração real).
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _MATCH_PAGEBREAK_RE.sub(" ", t)
    t = _MATCH_BULLET_RE.sub("• ", t)
    t = _MATCH_WS_RE.sub(" ", t)
    return t.strip()


def _texts_essentially_same(a: str, b: str) -> bool:
    """True se o conteúdo é o mesmo após normalização conservadora de whitespace/bullet."""
    if not a or not b:
        return False
    if a == b:
        return True
    ka, kb = _match_key(a), _match_key(b)
    return bool(ka) and ka == kb


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


def _pair_near_moves(
    rem_parts: list[str],
    add_parts: list[str],
    move_rem: set[int],
    move_add: set[int],
) -> None:
    """Pareia rem↔add com a mesma chave normalizada (in-place)."""
    add_by_key: dict[str, deque[int]] = defaultdict(deque)
    for j, text in enumerate(add_parts):
        if j in move_add:
            continue
        add_by_key[_match_key(text) or text].append(j)

    for i, text in enumerate(rem_parts):
        if i in move_rem:
            continue
        key = _match_key(text) or text
        queue = add_by_key.get(key)
        if not queue:
            continue
        while queue and queue[0] in move_add:
            queue.popleft()
        if queue:
            j = queue.popleft()
            move_rem.add(i)
            move_add.add(j)


def _emit_rem_add_block(rem_parts: list[str], add_parts: list[str]) -> list[TextDiffHunk]:
    """
    Converte um bloco rem+add em hunks.
    Parágrafos com conteúdo essencialmente igual viram 'moved';
    o restante é pareado como modified/rem/add.
    """
    move_rem: set[int] = set()
    move_add: set[int] = set()
    _pair_near_moves(rem_parts, add_parts, move_rem, move_add)

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
            if _texts_essentially_same(ra, rb):
                out.append(_new_hunk("moved", text_a=ra))
                out.append(_new_hunk("moved", text_b=rb))
            else:
                out.append(_new_hunk("modified", text_a=ra, text_b=rb))
        elif ra:
            out.append(_new_hunk("removed", text_a=ra))
        elif rb:
            out.append(_new_hunk("added", text_b=rb))
    return out


def _reclassify_as_moved(
    hunks: list[TextDiffHunk],
    used_removed: set[int],
    used_added: set[int],
) -> list[TextDiffHunk]:
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


def _detect_moved_paragraphs(hunks: list[TextDiffHunk]) -> list[TextDiffHunk]:
    """Pareia removed↔added com conteúdo essencialmente igual → moved (sem IA)."""
    rem_idx = [i for i, h in enumerate(hunks) if h.change_type == "removed" and h.text_a]
    add_idx = [i for i, h in enumerate(hunks) if h.change_type == "added" and h.text_b]
    if not rem_idx or not add_idx:
        return hunks

    rem_parts = [hunks[i].text_a or "" for i in rem_idx]
    add_parts = [hunks[i].text_b or "" for i in add_idx]
    move_rem_local: set[int] = set()
    move_add_local: set[int] = set()
    _pair_near_moves(rem_parts, add_parts, move_rem_local, move_add_local)

    used_removed = {rem_idx[i] for i in move_rem_local}
    used_added = {add_idx[j] for j in move_add_local}
    return _reclassify_as_moved(hunks, used_removed, used_added)


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
                moved_from += 1
                moved_to += 1
    moved = min(moved_from, moved_to) if (moved_from or moved_to) else 0
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
    """Diff em nível de parágrafo com SequenceMatcher + detecção intensificada de moves.

    Alinha parágrafos por chave normalizada (whitespace/bullet/quebra de página) para
    evitar falsos Removido+Novo quando o DMP fragmentava no nível de caractere.
    """
    pa = _paragraphs(text_a)
    pb = _paragraphs(text_b)
    pa_keys = [_match_key(p) for p in pa]
    pb_keys = [_match_key(p) for p in pb]
    matcher = difflib.SequenceMatcher(None, pa_keys, pb_keys, autojunk=False)

    hunks: list[TextDiffHunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                hunks.append(
                    _new_hunk(
                        "unchanged",
                        text_a=pa[i1 + k],
                        text_b=pb[j1 + k],
                    )
                )
        elif tag == "replace":
            hunks.extend(_emit_rem_add_block(pa[i1:i2], pb[j1:j2]))
        elif tag == "delete":
            for para in pa[i1:i2]:
                hunks.append(_new_hunk("removed", text_a=para))
        else:  # insert
            for para in pb[j1:j2]:
                hunks.append(_new_hunk("added", text_b=para))

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
            left_parts.append(f'<span class="bgf-diff-same">{_escape_para(h.text_a or "")}</span>')
            right_parts.append(
                f'<span class="bgf-diff-same">{_escape_para(h.text_b or h.text_a or "")}</span>'
            )
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
        f'<div class="bgf-diff-wrap bgf-diff-side bgf-sg-{html.escape(sync_group)}">'
        f'<div class="bgf-diff-col bgf-sync-scroll bgf-sg-{html.escape(sync_group)}">'
        f"<h4>{html.escape(label_a)}</h4>{left_body}</div>"
        f'<div class="bgf-diff-col bgf-sync-scroll bgf-sg-{html.escape(sync_group)}">'
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
