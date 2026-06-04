"""Análise por matriz temática — Proposta técnica/comercial x Contrato assinado.

Cruza dois documentos distintos item a item (escopo, prazos, entregáveis, valor,
etc.), identifica divergências, obrigações adicionais e gera alertas de risco.
Espelha o padrão tolerante de `contract_comparator.py`.
"""

import json
import re
import uuid
from datetime import datetime, timezone

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.document_locator import find_in_document
from app.core.llm import get_llm
from app.models.schemas import (
    ChangeRisk,
    MatrixItemResult,
    MatrixItemStatus,
    ProposalContractMatrixResult,
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


class MatrixItemLLM(BaseModel):
    """Schema tolerante para a análise de um item da matriz pela IA."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = ""
    categoria: str = ""
    status: MatrixItemStatus = MatrixItemStatus.CONFORME
    contrato_evidencia: str | None = None
    proposta_evidencia: str | None = None
    divergencia: str = ""
    impacto: str = ""
    recomendacao: str = ""
    gera_obrigacao_adicional: bool = False
    risk_level: ChangeRisk = ChangeRisk.MEDIUM

    @field_validator("contrato_evidencia", "proposta_evidencia", mode="before")
    @classmethod
    def truncate_excerpts(cls, v: str | None) -> str | None:
        if v and len(v) > MAX_EXCERPT_CHARS:
            return v[:MAX_EXCERPT_CHARS] + "… [trecho resumido]"
        return v


class _MatrixPayloadLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: str = ""
    items: list[MatrixItemLLM] = Field(default_factory=list)


SYSTEM_PROMPT = """Você é advogado especialista em contratos empresariais brasileiros.
Compare a PROPOSTA técnica/comercial com o CONTRATO assinado, item a item, conforme a MATRIZ fornecida.

Para CADA item da matriz, avalie:
- O que o contrato prevê (contrato_evidencia) e o que a proposta prevê (proposta_evidencia).
- status: conforme | divergente | ausente_contrato (previsto na proposta, não no contrato) |
  ausente_proposta (previsto no contrato, não na proposta) | obrigacao_adicional (a proposta cria obrigação não prevista no contrato).
- divergencia: descreva objetivamente a lacuna ou conflito (vazio se conforme).
- impacto: consequência jurídica/operacional/financeira.
- recomendacao: ação sugerida (ex.: aditivo contratual, alinhamento de prazo).
- gera_obrigacao_adicional: true se cria obrigação/passivo não previsto no contrato.
- risk_level: baixo | medio | alto.

REGRAS DE FORMATO (obrigatório):
- Responda UM item por entrada da matriz, repetindo o item_id recebido.
- contrato_evidencia e proposta_evidencia: no máximo 400 caracteres cada (resuma).
- Não invente cláusulas: se não houver evidência no texto, marque como ausente_*.
- Responda em português. JSON completo e válido."""

USER_PROMPT = """MATRIZ DE VERIFICAÇÃO (item_id | categoria | parâmetro | risco):
{matrix_json}

PROPOSTA TÉCNICA/COMERCIAL — {label_proposal}:
{proposal_text}

CONTRATO ASSINADO — {label_contract}:
{contract_text}

Analise cada item da matriz e devolva o resultado estruturado."""


def _matrix_for_prompt(items: list[dict]) -> str:
    lines = []
    for it in items:
        lines.append(
            f"- id={it['id']} | {it.get('categoria', '')} | "
            f"{it.get('parametro_verificacao', '')} | risco: {it.get('risco_padrao', '')}"
        )
    return "\n".join(lines)


def _coerce_risk(value) -> ChangeRisk:
    if isinstance(value, ChangeRisk):
        return value
    s = str(value or "medio").lower().strip()
    if s in ("alto", "high", "elevado"):
        return ChangeRisk.HIGH
    if s in ("baixo", "low", "baixa"):
        return ChangeRisk.LOW
    return ChangeRisk.MEDIUM


def _coerce_status(value) -> MatrixItemStatus:
    if isinstance(value, MatrixItemStatus):
        return value
    s = str(value or "conforme").lower().strip()
    for st in MatrixItemStatus:
        if st.value == s:
            return st
    return MatrixItemStatus.DIVERGENTE


# --- Recuperação de JSON parcial/truncado ---

def _extract_json_blob(text: str) -> str | None:
    if not text:
        return None
    start = text.find('{"executive_summary"')
    if start < 0:
        start = text.find('{"items"')
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


def _repair_truncated_items_json(blob: str) -> dict | None:
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        pass
    match = list(re.finditer(r'\},\s*\{"item_id"', blob))
    if match:
        cut = match[-1].start() + 1
        candidate = blob[:cut] + "]}"
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    if '"items"' in blob and not blob.rstrip().endswith("}"):
        for suffix in ("]}", "}]}"):
            try:
                return json.loads(blob + suffix)
            except json.JSONDecodeError:
                continue
    return None


def _payload_from_dict(data: dict) -> _MatrixPayloadLLM:
    items: list[MatrixItemLLM] = []
    for raw in data.get("items") or []:
        if not isinstance(raw, dict):
            continue
        try:
            items.append(MatrixItemLLM.model_validate(raw))
        except Exception as exc:
            logger.warning("Item da matriz ignorado (parse): {}", exc)
    return _MatrixPayloadLLM(
        executive_summary=data.get("executive_summary") or "Análise concluída.",
        items=items,
    )


def _parse_fallback(error_or_raw: str) -> _MatrixPayloadLLM | None:
    blob = _extract_json_blob(error_or_raw)
    if not blob:
        return None
    try:
        data = safe_json_parse(blob)
    except ValueError:
        data = _repair_truncated_items_json(blob)
    if data:
        payload = _payload_from_dict(data)
        if payload.items:
            logger.warning("Recuperados {} itens de JSON parcial/truncado", len(payload.items))
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


def _analyze_pass(
    proposal_text: str,
    contract_text: str,
    matrix_items: list[dict],
    label_proposal: str,
    label_contract: str,
) -> _MatrixPayloadLLM:
    llm = get_llm(temperature=0, max_output_tokens=_analysis_max_tokens())
    structured = llm.with_structured_output(_MatrixPayloadLLM, include_raw=True)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
    )
    chain = prompt | structured
    inputs = {
        "matrix_json": _matrix_for_prompt(matrix_items),
        "label_proposal": label_proposal,
        "label_contract": label_contract,
        "proposal_text": proposal_text,
        "contract_text": contract_text,
    }

    try:
        result = chain.invoke(inputs)
    except Exception as exc:
        logger.warning("Structured output falhou, tentando recuperar JSON: {}", exc)
        recovered = _parse_fallback(str(exc))
        if recovered:
            return recovered
        raise ValueError(
            "A resposta da IA foi truncada ou inválida. "
            "Tente novamente ou reduza o tamanho dos documentos. "
            f"Detalhe: {exc}"
        ) from exc

    if isinstance(result, dict):
        parsed = result.get("parsed")
        if parsed is not None:
            return parsed
        err_text = str(result.get("parsing_error") or "")
        raw_text = _content_from_raw_message(result.get("raw"))
        recovered = _parse_fallback(err_text + raw_text)
        if recovered:
            return recovered
        raise ValueError(
            "A resposta da IA foi truncada ou inválida. "
            "Tente novamente ou reduza o tamanho dos documentos."
        )

    return result


def _merge_passes(passes: list[_MatrixPayloadLLM]) -> _MatrixPayloadLLM:
    """Consolida múltiplos chunks: por item_id, mantém o achado mais relevante."""
    severity = {
        MatrixItemStatus.CONFORME: 0,
        MatrixItemStatus.AUSENTE_PROPOSTA: 1,
        MatrixItemStatus.AUSENTE_CONTRATO: 2,
        MatrixItemStatus.OBRIGACAO_ADICIONAL: 3,
        MatrixItemStatus.DIVERGENTE: 4,
    }
    by_id: dict[str, MatrixItemLLM] = {}
    summaries: list[str] = []
    for p in passes:
        if p.executive_summary:
            summaries.append(p.executive_summary)
        for it in p.items:
            existing = by_id.get(it.item_id)
            if existing is None or severity.get(_coerce_status(it.status), 0) > severity.get(
                _coerce_status(existing.status), 0
            ):
                by_id[it.item_id] = it
    return _MatrixPayloadLLM(
        executive_summary=" ".join(summaries[:3]) or "Análise por partes concluída.",
        items=list(by_id.values()),
    )


def _build_results(
    payload: _MatrixPayloadLLM,
    matrix_items: list[dict],
    proposal_path: str | None,
    contract_path: str | None,
) -> list[MatrixItemResult]:
    llm_by_id = {it.item_id: it for it in payload.items if it.item_id}
    results: list[MatrixItemResult] = []
    for src in matrix_items:
        rid = src["id"]
        llm = llm_by_id.get(rid)
        if llm is None:
            results.append(
                MatrixItemResult(
                    item_id=rid,
                    categoria=src.get("categoria", ""),
                    parametro_verificacao=src.get("parametro_verificacao", ""),
                    risco_padrao=src.get("risco_padrao", ""),
                    status=MatrixItemStatus.CONFORME,
                    divergencia="",
                    impacto="Item não retornado pela análise.",
                    risk_level=ChangeRisk.LOW,
                )
            )
            continue
        item = MatrixItemResult(
            item_id=rid,
            categoria=src.get("categoria", "") or llm.categoria,
            parametro_verificacao=src.get("parametro_verificacao", ""),
            risco_padrao=src.get("risco_padrao", ""),
            status=_coerce_status(llm.status),
            contrato_evidencia=llm.contrato_evidencia,
            proposta_evidencia=llm.proposta_evidencia,
            divergencia=llm.divergencia,
            impacto=llm.impacto,
            recomendacao=llm.recomendacao,
            gera_obrigacao_adicional=llm.gera_obrigacao_adicional,
            risk_level=_coerce_risk(llm.risk_level),
        )
        if contract_path and item.contrato_evidencia:
            item.locations_contrato = find_in_document(contract_path, item.contrato_evidencia[:300])
        if proposal_path and item.proposta_evidencia:
            item.locations_proposta = find_in_document(proposal_path, item.proposta_evidencia[:300])
        results.append(item)
    return results


def build_alerts(items: list[MatrixItemResult]) -> tuple[list[str], list[str]]:
    """Deriva (obrigações adicionais, alertas de risco) a partir dos itens analisados."""
    additional_obligations: list[str] = []
    risk_alerts: list[str] = []
    diverging = {
        MatrixItemStatus.DIVERGENTE,
        MatrixItemStatus.AUSENTE_CONTRATO,
        MatrixItemStatus.AUSENTE_PROPOSTA,
        MatrixItemStatus.OBRIGACAO_ADICIONAL,
    }
    for it in items:
        if it.gera_obrigacao_adicional or it.status == MatrixItemStatus.OBRIGACAO_ADICIONAL:
            detail = it.divergencia or it.impacto or it.parametro_verificacao
            additional_obligations.append(f"{it.categoria}: {detail}".strip())
        if it.status in diverging and it.risk_level in (ChangeRisk.MEDIUM, ChangeRisk.HIGH):
            detail = it.divergencia or it.impacto or it.parametro_verificacao
            risk_alerts.append(f"[{it.risk_level.value}] {it.categoria}: {detail}".strip())
    return additional_obligations, risk_alerts


def analyze_matrix(
    proposal_text: str,
    contract_text: str,
    matrix_items: list[dict],
    analysis_id: str,
    *,
    proposal_label: str = "Proposta",
    contract_label: str = "Contrato",
    proposal_path: str | None = None,
    contract_path: str | None = None,
) -> ProposalContractMatrixResult:
    if not matrix_items:
        raise ValueError("A matriz de verificação está vazia. Configure ao menos um item.")

    tokens_p = count_tokens(proposal_text)
    tokens_c = count_tokens(contract_text)
    logger.info(
        "Matriz Proposta x Contrato: {} / {} tokens, {} itens",
        tokens_p,
        tokens_c,
        len(matrix_items),
    )

    if max(tokens_p, tokens_c) <= 12000:
        payload = _analyze_pass(
            proposal_text, contract_text, matrix_items, proposal_label, contract_label
        )
    else:
        chunks_p = chunk_text(
            proposal_text, chunk_size=CHUNK_SIZE_CHARS, overlap=CHUNK_OVERLAP_CHARS
        )
        chunks_c = chunk_text(
            contract_text, chunk_size=CHUNK_SIZE_CHARS, overlap=CHUNK_OVERLAP_CHARS
        )
        passes: list[_MatrixPayloadLLM] = []
        total = max(len(chunks_p), len(chunks_c))
        for i in range(total):
            cp = chunks_p[min(i, len(chunks_p) - 1)]
            cc = chunks_c[min(i, len(chunks_c) - 1)]
            logger.info("Chunk matriz {}/{}", i + 1, total)
            passes.append(
                _analyze_pass(cp, cc, matrix_items, proposal_label, contract_label)
            )
        payload = _merge_passes(passes)

    items = _build_results(payload, matrix_items, proposal_path, contract_path)
    additional_obligations, risk_alerts = build_alerts(items)
    divergences = [i for i in items if i.status != MatrixItemStatus.CONFORME]
    high_risk = [i for i in items if i.risk_level == ChangeRisk.HIGH]

    return ProposalContractMatrixResult(
        analysis_id=analysis_id,
        proposal_label=proposal_label,
        contract_label=contract_label,
        executive_summary=payload.executive_summary or "Análise concluída.",
        items=items,
        divergences_count=len(divergences),
        additional_obligations=additional_obligations,
        risk_alerts=risk_alerts,
        high_risk_count=len(high_risk),
        analysis_timestamp=datetime.now(timezone.utc),
    )
