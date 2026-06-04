"""Comparação contratual entre versões via IA — análise jurídica, não diff de texto."""

import json
import re
import uuid

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.llm import get_llm
from app.models.schemas import (
    ChangeCategory,
    ChangeRisk,
    ContractDiffResult,
    ContractualChange,
)
from app.core.context_limits import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    MAX_EXCERPT_CHARS,
)
from app.utils.helpers import chunk_text, count_tokens, safe_json_parse
from app.utils.settings import get_settings


def _analysis_max_tokens() -> int:
    return max(4096, get_settings().max_tokens)


class ContractualChangeLLM(BaseModel):
    """Schema tolerante para respostas da IA (campos omitidos ou JSON truncado)."""

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


SYSTEM_PROMPT = """Você é advogado especialista em contratos empresariais brasileiros.
Compare duas versões de um mesmo contrato de forma CRITERIOSA e JURÍDICA.

FOQUE EM alterações MATERIAIS: cláusulas, prazos, valores, multas, responsabilidade, foro, rescisão.
IGNORE diferenças de formatação ou pontuação irrelevantes. NÃO faça diff caractere a caractere.

REGRAS DE FORMATO (obrigatório):
- Liste no máximo 12 alterações mais relevantes por análise.
- original_text e new_text: no máximo 400 caracteres cada (resuma se necessário).
- Sempre preencha: legal_impact, risk_level (baixo|medio|alto), requires_attention.
- category: clausula_adicionada | clausula_removida | clausula_alterada | condicoes_comerciais | responsabilidade | rescissao | confidencialidade | outro"""

USER_PROMPT = """VERSÃO ORIGINAL — {label_a}:
{text_a}

VERSÃO NOVA — {label_b}:
{text_b}

Analise as diferenças contratuais materiais. Resposta JSON completa e válida."""


def _coerce_risk(value) -> ChangeRisk:
    if isinstance(value, ChangeRisk):
        return value
    s = str(value or "medio").lower().strip()
    if s in ("alto", "high", "elevado"):
        return ChangeRisk.HIGH
    if s in ("baixo", "low", "baixa"):
        return ChangeRisk.LOW
    return ChangeRisk.MEDIUM


def _coerce_category(value) -> ChangeCategory:
    if isinstance(value, ChangeCategory):
        return value
    s = str(value or "outro").lower().strip()
    for cat in ChangeCategory:
        if cat.value == s:
            return cat
    return ChangeCategory.OTHER


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


def _extract_json_blob(text: str) -> str | None:
    """Extrai objeto JSON de mensagem de erro ou resposta bruta."""
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
    # Remover sufixo de erro LangChain após o JSON
    for marker in ("}. Got:", "}. Got ", "\nFor troubleshooting"):
        idx = blob.find(marker)
        if idx > 0:
            blob = blob[: idx + 1]
            break
    return blob


def _repair_truncated_changes_json(blob: str) -> dict | None:
    """Tenta recuperar JSON truncado removendo último item incompleto de changes."""
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        pass
    # Cortar no último objeto completo em "changes"
    match = list(re.finditer(r'\},\s*\{"change_id"', blob))
    if match:
        cut = match[-1].start() + 1
        candidate = blob[:cut] + "]}"
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # Fechar array e objeto
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
) -> ContractDiffResult:
    tokens_a = count_tokens(text_a)
    tokens_b = count_tokens(text_b)
    max_tokens = max(tokens_a, tokens_b)
    logger.info(
        "Análise contratual: {} / {} tokens — {} vs {}",
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
