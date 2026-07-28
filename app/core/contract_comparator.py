"""Comparação contratual híbrida — diff determinístico primeiro, IA opcional nos hunks."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from rapidfuzz import fuzz

from app.core.context_limits import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS, MAX_EXCERPT_CHARS
from app.core.llm import get_llm, get_llm_pro
from app.core.text_diff import compute_text_diff
from app.models.schemas import (
    AnalysisMode,
    ChangeCategory,
    ChangeRisk,
    ContractDiffResult,
    ContractualChange,
    TextDiffHunk,
    TextDiffResult,
)
from app.utils.helpers import chunk_text, count_tokens, safe_json_parse
from app.utils.settings import get_settings

ProgressCallback = Callable[[int, int, str], None]

EXCERPT_MATCH_THRESHOLD = 85
VALIDATION_HUNK_THRESHOLD = 3

_LEGAL_KEYWORDS = (
    "multa", "rescis", "foro", "confidenc", "indeniz", "garantia",
    "prazo", "vigência", "vigencia", "valor", "pagamento", "responsabil",
)


def excerpt_matches(haystack: str, needle: str, threshold: int = EXCERPT_MATCH_THRESHOLD) -> bool:
    """Valida se um trecho existe no texto com correspondência fuzzy ≥ threshold."""
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    return fuzz.partial_ratio(needle, haystack) >= threshold


def _hunk_category(change_type: str) -> ChangeCategory:
    if change_type == "added":
        return ChangeCategory.CLAUSE_ADDED
    if change_type == "removed":
        return ChangeCategory.CLAUSE_REMOVED
    if change_type == "moved":
        return ChangeCategory.CLAUSE_MOVED
    return ChangeCategory.CLAUSE_MODIFIED


def _hunk_title(hunk: TextDiffHunk) -> str:
    if hunk.change_type == "added":
        return "Parágrafo adicionado"
    if hunk.change_type == "removed":
        return "Parágrafo removido"
    if hunk.change_type == "moved":
        return "Parágrafo movido"
    return "Parágrafo alterado"


def hunks_to_contractual_changes(hunks: list[TextDiffHunk]) -> list[ContractualChange]:
    """Converte hunks do diff textual em alterações contratuais (sem IA)."""
    changes: list[ContractualChange] = []
    for h in hunks:
        if h.change_type == "unchanged":
            continue
        desc = (h.text_b or h.text_a or "")[:800]
        changes.append(
            ContractualChange(
                change_id=h.hunk_id,
                category=_hunk_category(h.change_type),
                clause_reference="Diff textual",
                title=_hunk_title(h),
                description=desc,
                original_text=h.text_a,
                new_text=h.text_b,
                legal_impact="Alteração identificada por diff textual.",
                risk_level=ChangeRisk.MEDIUM,
                requires_attention=True,
            )
        )
    return changes


def validate_hunks_as_changes(
    hunks: list[TextDiffHunk],
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    contract_id: str,
    *,
    similarity_score: float = 0.0,
) -> ContractDiffResult:
    """Fallback sem IA: keywords + fuzzy — usado se a validação com OpenAI falhar."""
    changes: list[ContractualChange] = []
    warnings: list[str] = []
    invalid = 0

    for h in hunks:
        if h.change_type == "unchanged":
            continue
        valid_a = excerpt_matches(text_a, h.text_a) if h.text_a else True
        valid_b = excerpt_matches(text_b, h.text_b) if h.text_b else True
        if not valid_a or not valid_b:
            invalid += 1
            warnings.append(f"Hunk {h.hunk_id}: trecho não validado no documento.")

        legal = _hunk_has_legal_keyword(h)
        impact = (
            "Possível alteração material (termo jurídico detectado)."
            if legal
            else (
                "Trecho validado nos documentos."
                if valid_a and valid_b
                else "Trecho com baixa correspondência — revisar manualmente."
            )
        )
        changes.append(
            ContractualChange(
                change_id=h.hunk_id,
                category=_hunk_category(h.change_type),
                clause_reference="Validação pré-assinatura",
                title=_hunk_title(h),
                description=(h.text_b or h.text_a or "")[:800],
                original_text=h.text_a,
                new_text=h.text_b,
                legal_impact=impact,
                risk_level=(
                    ChangeRisk.HIGH
                    if legal or not (valid_a and valid_b)
                    else ChangeRisk.LOW
                ),
                requires_attention=legal or not (valid_a and valid_b),
            )
        )

    summary, recommendation = _validation_alert(hunks)
    if invalid:
        summary += f" {invalid} trecho(s) com correspondência fuzzy abaixo de {EXCERPT_MATCH_THRESHOLD}."
    if warnings:
        summary += " " + " ".join(warnings[:3])

    high = [c for c in changes if c.risk_level == ChangeRisk.HIGH]
    material = [c for c in changes if c.requires_attention]
    return ContractDiffResult(
        contract_id=contract_id,
        version_a_label=label_a,
        version_b_label=label_b,
        executive_summary=summary,
        recommendation=recommendation,
        material_changes_count=len(material),
        high_risk_count=len(high),
        has_significant_changes=bool(material),
        contractual_changes=changes,
        summary=summary,
        similarity_score=similarity_score,
    )


class _SigningFlagLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hunk_id: str = ""
    is_material: bool = False
    risk_level: ChangeRisk = ChangeRisk.LOW
    reason: str = ""
    title: str = ""


class _SigningValidationLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    safe_to_sign: bool = True
    executive_summary: str = ""
    recommendation: str = ""
    material_flags: list[_SigningFlagLLM] = Field(default_factory=list)


SIGNING_VALIDATION_SYSTEM = """Você é advogado de contratos corporativos no Brasil.
Cenário: as partes já acordaram o texto; uma versão chegou para ASSINATURA.
Sua missão é só detectar se houve ALTERAÇÃO MATERIAL inserida em relação à versão anterior.
Ignore formatação, espaços, tipografia, numeração cosméticas e correções ortográficas sem impacto.
É material: obrigação, valor, prazo, multa, rescisão, foro, confidencialidade, responsabilidade,
garantia, partes/qualificação, objeto, pagamento, indicação.
Responda de forma objetiva para decisão de assinar ou não."""

SIGNING_VALIDATION_USER = """Versão anterior (acordo): {label_a}
Versão enviada para assinatura: {label_b}
Similaridade textual: {similarity:.0%}

ALTERAÇÕES DETECTADAS PELO DUMP TEXTUAL (hunks):
{hunks_digest}

Para cada alteração material, preencha material_flags com hunk_id, is_material=true, risk_level, reason e title curto.
Se nada for material: safe_to_sign=true, material_flags vazio.
executive_summary: 1-3 frases para o usuário jurídico.
recommendation: "Pode assinar" ou o que revisar antes de assinar."""


def _digest_hunks_for_signing(hunks: list[TextDiffHunk], *, max_hunks: int = 40) -> str:
    parts: list[str] = []
    changed = [h for h in hunks if h.change_type != "unchanged"][:max_hunks]
    for i, h in enumerate(changed, 1):
        a = (h.text_a or "(vazio)")[:900]
        b = (h.text_b or "(vazio)")[:900]
        parts.append(
            f"[{h.hunk_id}] #{i} tipo={h.change_type}\n"
            f"ANTES: {a}\nDEPOIS: {b}"
        )
    if not parts:
        return "(nenhuma alteração de parágrafo)"
    return "\n\n---\n\n".join(parts)


def validate_signing_version(
    hunks: list[TextDiffHunk],
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    contract_id: str,
    *,
    similarity_score: float = 0.0,
    progress_callback: ProgressCallback | None = None,
) -> ContractDiffResult:
    """Validação pré-assinatura: diff + IA (flash) só para relevância material.

    Não analisa comentários. Objetivo: ver se a versão para assinar diverge
    de forma relevante do texto acordado.
    """
    changed = [h for h in hunks if h.change_type != "unchanged"]
    if not changed:
        return ContractDiffResult(
            contract_id=contract_id,
            version_a_label=label_a,
            version_b_label=label_b,
            executive_summary=(
                "Nenhuma alteração textual entre a versão acordada e a enviada para assinatura."
            ),
            recommendation="Pode assinar — documentos equivalentes no texto.",
            material_changes_count=0,
            high_risk_count=0,
            has_significant_changes=False,
            contractual_changes=[],
            summary="Sem diferenças.",
            similarity_score=similarity_score,
        )

    if progress_callback:
        progress_callback(2, 3, f"Validando {len(changed)} alteração(ões) com IA…")

    hunk_by_id = {h.hunk_id: h for h in changed}
    try:
        llm = get_llm(temperature=0, max_output_tokens=min(8192, _analysis_max_tokens()))
        structured = llm.with_structured_output(_SigningValidationLLM)
        prompt = ChatPromptTemplate.from_messages(
            [("system", SIGNING_VALIDATION_SYSTEM), ("user", SIGNING_VALIDATION_USER)]
        )
        raw: _SigningValidationLLM = (prompt | structured).invoke(
            {
                "label_a": label_a,
                "label_b": label_b,
                "similarity": similarity_score,
                "hunks_digest": _digest_hunks_for_signing(changed),
            }
        )
    except Exception as exc:
        logger.warning("Validação com IA falhou — fallback regras: {}", exc)
        return validate_hunks_as_changes(
            hunks,
            text_a,
            text_b,
            label_a,
            label_b,
            contract_id,
            similarity_score=similarity_score,
        )

    changes: list[ContractualChange] = []
    for flag in raw.material_flags:
        if not flag.is_material:
            continue
        h = hunk_by_id.get(flag.hunk_id)
        if h is None and flag.hunk_id:
            # tenta match por prefixo/parcial
            for hid, cand in hunk_by_id.items():
                if hid.startswith(flag.hunk_id) or flag.hunk_id in hid:
                    h = cand
                    break
        if h is None:
            continue
        changes.append(
            ContractualChange(
                change_id=h.hunk_id,
                category=_hunk_category(h.change_type),
                clause_reference="Validação pré-assinatura",
                title=flag.title or _hunk_title(h),
                description=(flag.reason or (h.text_b or h.text_a or ""))[:800],
                original_text=h.text_a,
                new_text=h.text_b,
                legal_impact=flag.reason or "Alteração material detectada na versão para assinar.",
                risk_level=flag.risk_level or ChangeRisk.HIGH,
                requires_attention=True,
            )
        )

    # Se a IA disse inseguro mas não marcou flags, inclui hunks com keyword jurídica.
    if not raw.safe_to_sign and not changes:
        for h in changed:
            if _hunk_has_legal_keyword(h):
                changes.append(
                    ContractualChange(
                        change_id=h.hunk_id,
                        category=_hunk_category(h.change_type),
                        clause_reference="Validação pré-assinatura",
                        title=_hunk_title(h),
                        description=(h.text_b or h.text_a or "")[:800],
                        original_text=h.text_a,
                        new_text=h.text_b,
                        legal_impact="Possível alteração material (revisar antes de assinar).",
                        risk_level=ChangeRisk.HIGH,
                        requires_attention=True,
                    )
                )

    high = [c for c in changes if c.risk_level == ChangeRisk.HIGH]
    if changes:
        summary = raw.executive_summary or (
            f"Atenção: {len(changes)} alteração(ões) material(is) entre a versão acordada "
            f"e a enviada para assinatura."
        )
        recommendation = raw.recommendation or (
            "Não assine ainda — revise as alterações materiais listadas."
        )
    else:
        summary = raw.executive_summary or (
            f"{len(changed)} diferença(s) textual(is), nenhuma classificada como material "
            f"para fins de assinatura (similaridade {similarity_score:.0%})."
        )
        recommendation = raw.recommendation or "Pode assinar — sem alteração material relevante."

    if progress_callback:
        progress_callback(3, 3, "Validação pré-assinatura concluída")

    return ContractDiffResult(
        contract_id=contract_id,
        version_a_label=label_a,
        version_b_label=label_b,
        executive_summary=summary,
        recommendation=recommendation,
        material_changes_count=len(changes),
        high_risk_count=len(high),
        has_significant_changes=bool(changes),
        contractual_changes=changes,
        summary=summary,
        similarity_score=similarity_score,
    )


def _hunk_has_legal_keyword(h: TextDiffHunk) -> bool:
    blob = f"{h.text_a or ''} {h.text_b or ''}".lower()
    return any(kw in blob for kw in _LEGAL_KEYWORDS)


def _validation_alert(hunks: list[TextDiffHunk]) -> tuple[str, str]:
    changed = [h for h in hunks if h.change_type != "unchanged"]
    significant = [h for h in changed if _hunk_has_legal_keyword(h)]
    n = len(changed)
    if n == 0:
        return (
            "Nenhuma alteração de parágrafo detectada entre as versões.",
            "Documento validado — sem mudanças textuais.",
        )
    if n <= VALIDATION_HUNK_THRESHOLD and not significant:
        return (
            f"{n} parágrafo(s) alterado(s) — abaixo do limiar de alerta ({VALIDATION_HUNK_THRESHOLD}).",
            "Alterações menores; revisão humana opcional.",
        )
    alert = f"{n} parágrafo(s) alterado(s)"
    if significant:
        alert += f", incluindo {len(significant)} com termos jurídicos relevantes"
    return alert + ".", "Recomenda-se revisão das alterações destacadas no diff lateral."


def _hunk_to_change(h: TextDiffHunk, index: int) -> ContractualChange:
    return ContractualChange(
        change_id=h.hunk_id or f"h{index}",
        category=_hunk_category(h.change_type),
        clause_reference=f"§{index + 1}",
        title=_hunk_title(h),
        description=(h.text_b or h.text_a or "")[:800],
        original_text=h.text_a,
        new_text=h.text_b,
        legal_impact="Alteração textual confirmada por diff determinístico.",
        risk_level=ChangeRisk.LOW,
        requires_attention=h.change_type != "unchanged",
    )


def _filter_ai_changes(
    changes: list[ContractualChange],
    text_a: str,
    text_b: str,
) -> list[ContractualChange]:
    kept: list[ContractualChange] = []
    for ch in changes:
        orig_ok = excerpt_matches(text_a, ch.original_text or "") if ch.original_text else True
        new_ok = excerpt_matches(text_b, ch.new_text or "") if ch.new_text else True
        if orig_ok and new_ok:
            kept.append(ch)
        else:
            logger.warning(
                "Alteração descartada (âncora inválida, fuzz < {}): {}",
                EXCERPT_MATCH_THRESHOLD,
                ch.title,
            )
    return kept


def _result_from_hunks(
    hunks: list[TextDiffHunk],
    *,
    contract_id: str,
    label_a: str,
    label_b: str,
    executive_summary: str,
    recommendation: str,
    changes: list[ContractualChange] | None = None,
    similarity: float = 0.0,
) -> ContractDiffResult:
    contractual = changes or [
        _hunk_to_change(h, i) for i, h in enumerate(hunks) if h.change_type != "unchanged"
    ]
    material = [c for c in contractual if c.requires_attention or c.risk_level != ChangeRisk.LOW]
    high_risk = [c for c in contractual if c.risk_level == ChangeRisk.HIGH]
    return ContractDiffResult(
        contract_id=contract_id,
        version_a_label=label_a,
        version_b_label=label_b,
        executive_summary=executive_summary,
        recommendation=recommendation,
        material_changes_count=len(material) or len(contractual),
        high_risk_count=len(high_risk),
        has_significant_changes=bool(material or contractual),
        contractual_changes=contractual,
        summary=executive_summary,
        similarity_score=similarity,
    )


HUNK_LLM_SYSTEM = """Você é advogado especialista em contratos empresariais brasileiros.
Analise APENAS os trechos alterados fornecidos (hunks confirmados por diff textual).
NÃO invente alterações que não estejam nos trechos."""

HUNK_LLM_USER = """Hunk {index}/{total}:
TEXTO ANTERIOR:
{original}

TEXTO NOVO:
{new}

Classifique risco jurídico e impacto. JSON com changes (lista de 0 ou 1 item)."""


class ContractualChangeLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    change_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    category: ChangeCategory = ChangeCategory.OTHER
    clause_reference: str = "Não especificada"
    title: str = "Alteração contratual"
    description: str = ""
    original_text: str | None = None
    new_text: str | None = None
    legal_impact: str = ""
    affected_party: str = "ambas"
    risk_level: ChangeRisk = ChangeRisk.MEDIUM
    requires_attention: bool = True

    @field_validator("original_text", "new_text", mode="before")
    @classmethod
    def truncate_excerpts(cls, v: str | None) -> str | None:
        if v and len(v) > MAX_EXCERPT_CHARS:
            return v[:MAX_EXCERPT_CHARS] + "… [trecho resumido]"
        return v


class _ChangesPayloadLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: str = ""
    recommendation: str = ""
    changes: list[ContractualChangeLLM] = Field(default_factory=list)


class _ChangesPayload(BaseModel):
    executive_summary: str
    recommendation: str
    changes: list[ContractualChange]


def _llm_change_to_contractual(ch: ContractualChangeLLM) -> ContractualChange | None:
    if not ch.description and not ch.title:
        return None
    return ContractualChange(
        change_id=ch.change_id or str(uuid.uuid4())[:8],
        category=ch.category,
        clause_reference=ch.clause_reference or "Não especificada",
        title=ch.title or "Alteração",
        description=ch.description or ch.title,
        original_text=ch.original_text,
        new_text=ch.new_text,
        legal_impact=ch.legal_impact or ch.description[:300],
        affected_party=ch.affected_party or "ambas",
        risk_level=ch.risk_level,
        requires_attention=ch.requires_attention,
    )


def _payload_from_llm(raw: _ChangesPayloadLLM) -> _ChangesPayload:
    changes: list[ContractualChange] = []
    for ch in raw.changes:
        converted = _llm_change_to_contractual(ch)
        if converted:
            changes.append(converted)
    return _ChangesPayload(
        executive_summary=raw.executive_summary or "Análise concluída.",
        recommendation=raw.recommendation or "",
        changes=changes,
    )


def _analyze_hunk_llm(h: TextDiffHunk, index: int, total: int) -> list[ContractualChange]:
    if h.change_type == "unchanged":
        return []
    llm = get_llm_pro(temperature=0, max_output_tokens=_analysis_max_tokens())
    structured = llm.with_structured_output(_ChangesPayloadLLM)
    prompt = ChatPromptTemplate.from_messages(
        [("system", HUNK_LLM_SYSTEM), ("user", HUNK_LLM_USER)]
    )
    chain = prompt | structured
    try:
        raw: _ChangesPayloadLLM = chain.invoke(
            {
                "index": index + 1,
                "total": total,
                "original": h.text_a or "(removido)",
                "new": h.text_b or "(adicionado)",
            }
        )
        payload = _payload_from_llm(raw)
        if payload.changes:
            return payload.changes
    except Exception as exc:
        logger.warning("IA falhou no hunk {}: {}", index, exc)
    return [_hunk_to_change(h, index)]


def compare_from_hunks(
    hunks: list[TextDiffHunk],
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    contract_id: str,
    *,
    progress_callback: ProgressCallback | None = None,
    max_hunks: int = 20,
) -> ContractDiffResult:
    """Análise criteriosa via LLM Pro nos hunks alterados, com validação fuzzy ≥ 85."""
    changed = [h for h in hunks if h.change_type != "unchanged"][:max_hunks]
    all_changes: list[ContractualChange] = []
    total = len(changed) or 1

    for i, hunk in enumerate(changed):
        if progress_callback:
            progress_callback(i, total, f"Analisando alteração {i + 1}/{total}…")
        if hunk.text_a and not excerpt_matches(text_a, hunk.text_a):
            logger.debug("Hunk {} — texto base não validado", hunk.hunk_id)
        if hunk.text_b and not excerpt_matches(text_b, hunk.text_b):
            logger.debug("Hunk {} — texto novo não validado", hunk.hunk_id)
        all_changes.extend(_analyze_hunk_llm(hunk, i, total))

    all_changes = _filter_ai_changes(all_changes, text_a, text_b)

    if progress_callback:
        progress_callback(total, total, "Consolidando análise…")

    similarity = 0.0
    summary = (
        f"Análise criteriosa: {len(all_changes)} alteração(ões) confirmada(s) "
        f"em {len(changed)} hunk(s) do diff ({label_a} × {label_b})."
    )
    return _result_from_hunks(
        hunks,
        contract_id=contract_id,
        label_a=label_a,
        label_b=label_b,
        executive_summary=summary,
        recommendation="Revise alterações de alto risco antes de assinar.",
        changes=all_changes,
        similarity=similarity,
    )


def _analysis_max_tokens() -> int:
    return max(4096, get_settings().max_tokens)


SYSTEM_PROMPT = """Você é advogado especialista em contratos empresariais brasileiros.
Compare duas versões de um mesmo contrato de forma CRITERIOSA e JURÍDICA.

FOQUE EM alterações MATERIAIS: cláusulas, prazos, valores, multas, responsabilidade, foro, rescisão.
IGNORE diferenças de formatação ou pontuação irrelevantes. NÃO faça diff caractere a caractere.

REGRAS DE FORMATO (obrigatório):
- Liste no máximo 12 alterações mais relevantes por análise.
- original_text e new_text: no máximo 400 caracteres cada (resuma se necessário).
- Sempre preencha: legal_impact, risk_level (baixo|medio|alto), requires_attention.
- category: clausula_adicionada | clausula_removida | clausula_alterada | clausula_movida | condicoes_comerciais | responsabilidade | rescissao | confidencialidade | outro"""

USER_PROMPT = """VERSÃO ORIGINAL — {label_a}:
{text_a}

VERSÃO NOVA — {label_b}:
{text_b}

Analise as diferenças contratuais materiais. Resposta JSON completa e válida."""


def _extract_json_blob(text: str) -> str | None:
    if not text:
        return None
    start = text.find('{"executive_summary"')
    if start < 0:
        start = text.find('{"changes"')
    if start < 0:
        start = text.find("{")
    if start < 0:
        return None
    blob = text[start:]
    for marker in ("}. Got:", "}. Got ", "\nFor troubleshooting"):
        idx = blob.find(marker)
        if idx > 0:
            blob = blob[: idx + 1]
            break
    return blob


def _repair_truncated_changes_json(blob: str) -> dict | None:
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        pass
    match = list(re.finditer(r'\},\s*\{"change_id"', blob))
    if match:
        cut = match[-1].start() + 1
        candidate = blob[:cut] + "]}"
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    if '"changes"' in blob and not blob.rstrip().endswith("}"):
        for suffix in ("]}", "}]}"):
            try:
                return json.loads(blob + suffix)
            except json.JSONDecodeError:
                continue
    return None


def _payload_from_dict(data: dict) -> _ChangesPayload:
    changes: list[ContractualChange] = []
    for item in data.get("changes") or []:
        if not isinstance(item, dict):
            continue
        try:
            llm_ch = ContractualChangeLLM.model_validate(item)
            converted = _llm_change_to_contractual(llm_ch)
            if converted:
                changes.append(converted)
        except Exception as exc:
            logger.warning("Alteração ignorada (parse): {}", exc)
    return _ChangesPayload(
        executive_summary=data.get("executive_summary") or "Análise concluída.",
        recommendation=data.get("recommendation") or "",
        changes=changes,
    )


def _parse_fallback(error_or_raw: str) -> _ChangesPayload | None:
    blob = _extract_json_blob(error_or_raw)
    if not blob:
        return None
    try:
        data = safe_json_parse(blob)
    except ValueError:
        data = _repair_truncated_changes_json(blob)
    if data:
        payload = _payload_from_dict(data)
        if payload.changes:
            logger.warning(
                "Recuperadas {} alterações de JSON parcial/truncado",
                len(payload.changes),
            )
            return payload
    return None


def _content_from_raw_message(raw) -> str:
    if raw is None:
        return ""
    content = getattr(raw, "content", raw)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _analyze_pair(text_a: str, text_b: str, label_a: str, label_b: str) -> _ChangesPayload:
    llm = get_llm(temperature=0, max_output_tokens=_analysis_max_tokens())
    structured = llm.with_structured_output(_ChangesPayloadLLM, include_raw=True)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
    )
    chain = prompt | structured
    inputs = {"label_a": label_a, "label_b": label_b, "text_a": text_a, "text_b": text_b}

    try:
        result = chain.invoke(inputs)
    except Exception as exc:
        logger.warning("Structured output falhou, tentando recuperar JSON: {}", exc)
        recovered = _parse_fallback(str(exc))
        if recovered:
            return recovered
        raise ValueError(
            "A resposta da IA foi truncada ou inválida. "
            "Tente novamente ou use contratos menores. "
            f"Detalhe: {exc}"
        ) from exc

    if isinstance(result, dict):
        parsed = result.get("parsed")
        if parsed is not None:
            return _payload_from_llm(parsed)
        err_text = str(result.get("parsing_error") or "")
        raw_text = _content_from_raw_message(result.get("raw"))
        recovered = _parse_fallback(err_text + raw_text)
        if recovered:
            return recovered
        raise ValueError(
            "A resposta da IA foi truncada ou inválida. "
            "Tente novamente ou reduza o tamanho do contrato."
        )

    return _payload_from_llm(result)


def _merge_changes(chunks: list[_ChangesPayload]) -> _ChangesPayload:
    all_changes: list[ContractualChange] = []
    summaries: list[str] = []
    recommendations: list[str] = []
    for c in chunks:
        all_changes.extend(c.changes)
        if c.executive_summary:
            summaries.append(c.executive_summary)
        if c.recommendation:
            recommendations.append(c.recommendation)
    seen: set[str] = set()
    unique: list[ContractualChange] = []
    for ch in all_changes:
        key = f"{ch.clause_reference}|{ch.title}"
        if key not in seen:
            seen.add(key)
            unique.append(ch)
    return _ChangesPayload(
        executive_summary=" ".join(summaries[:3]) or "Análise por partes concluída.",
        recommendation=recommendations[-1] if recommendations else "",
        changes=unique,
    )


def compare_contracts(
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    contract_id: str,
    *,
    mode: AnalysisMode = AnalysisMode.CRITERIOSA,
    progress_callback: ProgressCallback | None = None,
    text_diff: TextDiffResult | None = None,
) -> ContractDiffResult:
    """Comparação completa — delega ao diff textual e ao modo escolhido.

    Passe ``text_diff`` pré-calculado para evitar recomputar o diff no caller.
    """
    if progress_callback:
        progress_callback(1, 3, "Calculando diff textual…")

    if text_diff is None:
        text_diff = compute_text_diff(
            text_a, text_b, contract_id=contract_id, label_a=label_a, label_b=label_b
        )
    hunks = text_diff.hunks
    changed_hunks = [h for h in hunks if h.change_type != "unchanged"]

    if mode in (AnalysisMode.TEXT_DIFF, AnalysisMode.DIFERENCAS):
        if progress_callback:
            progress_callback(3, 3, "Diff concluído (sem IA)")
        summary = (
            f"Diff textual: {text_diff.paragraphs_added} adicionados, "
            f"{text_diff.paragraphs_removed} removidos, "
            f"{text_diff.paragraphs_modified} alterados, "
            f"{text_diff.paragraphs_moved} movidos. "
            f"Similaridade: {text_diff.similarity_score:.0%}."
        )
        return _result_from_hunks(
            hunks,
            contract_id=contract_id,
            label_a=label_a,
            label_b=label_b,
            executive_summary=summary,
            recommendation="",
            changes=hunks_to_contractual_changes(hunks),
            similarity=text_diff.similarity_score,
        )

    if mode == AnalysisMode.VALIDACAO:
        if progress_callback:
            progress_callback(2, 3, "Validação pré-assinatura (relevância material)…")
        return validate_signing_version(
            hunks,
            text_a,
            text_b,
            label_a,
            label_b,
            contract_id,
            similarity_score=text_diff.similarity_score,
            progress_callback=progress_callback,
        )

    if progress_callback:
        progress_callback(2, 3, f"Analisando {len(changed_hunks)} hunk(s) com IA…")

    result = compare_from_hunks(
        hunks,
        text_a,
        text_b,
        label_a,
        label_b,
        contract_id,
        progress_callback=progress_callback,
    )
    result.similarity_score = text_diff.similarity_score
    if progress_callback:
        progress_callback(3, 3, "Análise concluída")
    return result



def compare_contracts_full_document(
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    contract_id: str,
) -> ContractDiffResult:
    """Análise documento inteiro via IA (fallback para contratos muito grandes)."""
    tokens_a = count_tokens(text_a)
    tokens_b = count_tokens(text_b)
    max_tokens = max(tokens_a, tokens_b)
    logger.info(
        "Análise contratual completa: {} / {} tokens — {} vs {}",
        tokens_a,
        tokens_b,
        label_a,
        label_b,
    )

    if max_tokens <= 12000:
        payload = _analyze_pair(text_a, text_b, label_a, label_b)
    else:
        chunks_a = chunk_text(text_a, chunk_size=CHUNK_SIZE_CHARS, overlap=CHUNK_OVERLAP_CHARS)
        chunks_b = chunk_text(text_b, chunk_size=CHUNK_SIZE_CHARS, overlap=CHUNK_OVERLAP_CHARS)
        partials: list[_ChangesPayload] = []
        pairs = max(len(chunks_a), len(chunks_b))
        for i in range(pairs):
            ca = chunks_a[min(i, len(chunks_a) - 1)]
            cb = chunks_b[min(i, len(chunks_b) - 1)]
            logger.info("Chunk contratual {}/{}", i + 1, pairs)
            partials.append(_analyze_pair(ca, cb, label_a, label_b))
        payload = _merge_changes(partials)

    material = [
        c for c in payload.changes
        if c.requires_attention or c.risk_level != ChangeRisk.LOW
    ]
    high_risk = [c for c in payload.changes if c.risk_level == ChangeRisk.HIGH]

    return ContractDiffResult(
        contract_id=contract_id,
        version_a_label=label_a,
        version_b_label=label_b,
        executive_summary=payload.executive_summary,
        recommendation=payload.recommendation,
        material_changes_count=len(material),
        high_risk_count=len(high_risk),
        has_significant_changes=len(material) > 0,
        contractual_changes=payload.changes,
        summary=payload.executive_summary,
    )
