"""Análise inicial do contrato contra parâmetros de verificação (documento único)."""

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.llm import get_llm
from app.models.schemas import (
    ChangeRisk,
    ContractMatrixInitialResult,
    MatrixParameterCheck,
)
from app.core.context_limits import (
    CHUNK_TOKEN_LIMIT,
    CONTRACT_CTX_CHARS,
    MAX_EXCERPT_CHARS,
    PROPOSAL_CTX_CHARS,
)
from app.utils.helpers import chunk_text, count_tokens, safe_json_parse
from app.utils.settings import get_settings

ProgressCallback = Callable[[int, int, str], None]
ItemCompleteCallback = Callable[[MatrixParameterCheck, int, int], None]


def _analysis_max_tokens() -> int:
    return max(4096, get_settings().max_tokens)


class _MatrixParameterCheckLLM(BaseModel):
    """Schema tolerante — só os campos que a IA deve preencher por item."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = ""
    categoria: str = ""
    parametro_verificacao: str = ""
    risco_padrao: str = ""
    present: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    found_excerpt: str | None = None
    proposal_excerpt: str | None = None
    aligns_with_proposal: bool | None = None
    page_hint: str | None = None
    observation: str = ""
    validation_steps: str = ""
    risk_level: ChangeRisk = ChangeRisk.LOW

    @field_validator("found_excerpt", "proposal_excerpt", mode="before")
    @classmethod
    def truncate_excerpt(cls, v: str | None) -> str | None:
        if v and len(v) > MAX_EXCERPT_CHARS:
            return v[:MAX_EXCERPT_CHARS] + "… [trecho resumido]"
        return v


class _MatrixChecksPayloadLLM(BaseModel):
    """Resposta mínima da IA — totais e timestamp são calculados no código."""

    model_config = ConfigDict(extra="ignore")

    checks: list[_MatrixParameterCheckLLM] = Field(default_factory=list)
    executive_summary: str = ""


class _MatrixSingleItemPayloadLLM(BaseModel):
    """Uma verificação por chamada (modo item a item com proposta)."""

    model_config = ConfigDict(extra="ignore")

    check: _MatrixParameterCheckLLM


SYSTEM_PROMPT = """Você é advogado especialista em contratos empresariais brasileiros.

A matriz lista PARÂMETROS DE VERIFICAÇÃO. Em cada linha, o campo «AÇÃO DE VALIDAÇÃO»
descreve o procedimento que você DEVE executar (não é título decorativo).

Para CADA item da matriz (obrigatório — um objeto em checks por item_id):
1) Leia a categoria e a AÇÃO DE VALIDAÇÃO.
2) Se houver PROPOSTA COMERCIAL: localize trechos que definam a expectativa do cliente.
3) No CONTRATO: busque evidência textual que atenda ou viole essa ação.
4) Conclua com base em evidência citável.

Campos por item:
- item_id: repita exatamente o id recebido.
- present: true só se o contrato cobre o parâmetro com evidência clara.
- confidence: 0 a 1.
- found_excerpt: trecho do contrato (máx. 600 caracteres) ou null.
- proposal_excerpt: trecho da proposta que fundamenta a expectativa (ou null).
- aligns_with_proposal: true/false/null — contrato alinhado à proposta neste ponto.
- page_hint: referência (ex.: Cláusula 3).
- validation_steps: em português, liste em 2–4 frases curtas o que você consultou
  na proposta e o que verificou no contrato (prova de que executou a ação).
- observation: conclusão objetiva; cite proposta e contrato quando relevante.
- risk_level: baixo | medio | alto.

REGRAS:
- Devolva checks com TODOS os itens da matriz (mesma quantidade).
- Não invente cláusulas; use null se não houver evidência.
- Responda em português. JSON válido."""

SINGLE_ITEM_SYSTEM_PROMPT = """Você é advogado especialista em contratos empresariais brasileiros.

Você analisa UM ÚNICO parâmetro da matriz por vez, com máxima rigorosidade.

O campo «AÇÃO DE VALIDAÇÃO» descreve o procedimento obrigatório — execute-o passo a passo:
1) Entenda categoria e ação de validação.
2) Na PROPOSTA COMERCIAL: encontre o que o cliente espera neste ponto.
3) No CONTRATO: verifique se atende à proposta e à ação (busque cláusulas, anexos, tabelas).
4) Registre evidências literais nos trechos (não parafraseie sem base).

Preencha o objeto check com todos os campos, em especial validation_steps (2–4 frases
descrevendo consulta à proposta e verificação no contrato)."""

USER_PROMPT = """MATRIZ DE VERIFICAÇÃO (item_id | categoria | AÇÃO DE VALIDAÇÃO | risco esperado):
{matrix_json}

Total de itens na matriz: {item_count}

{proposal_block}

CONTRATO:
{contract_text}

Analise cada item_id e preencha checks[]."""

SINGLE_ITEM_USER_PROMPT = """PARÂMETRO (item_id={item_id}):
- Categoria: {categoria}
- AÇÃO DE VALIDAÇÃO (execute integralmente): {parametro_verificacao}
- Risco se falhar: {risco_padrao}

{proposal_block}

CONTRATO (trecho para análise):
{contract_text}

Execute a ação de validação e devolva o objeto check."""

PROPOSAL_BLOCK = """PROPOSTA COMERCIAL — {proposal_label}:
{proposal_text}
"""


def _truncate_context(text: str, max_chars: int, label: str = "documento") -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    half = max_chars // 2
    logger.warning(
        "{} truncado de {} para {} caracteres no contexto da IA",
        label,
        len(t),
        max_chars,
    )
    return (
        t[:half]
        + f"\n\n[... {label} truncado — leia início e fim ...]\n\n"
        + t[-half:]
    )


def _matrix_for_prompt(items: list[dict]) -> str:
    lines = []
    for it in items:
        lines.append(
            f"- id={it['id']} | {it.get('categoria', '')} | "
            f"AÇÃO: {it.get('parametro_verificacao', '')} | risco: {it.get('risco_padrao', '')}"
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


def _llm_check_to_model(raw: _MatrixParameterCheckLLM, src: dict) -> MatrixParameterCheck:
    return MatrixParameterCheck(
        item_id=raw.item_id or src.get("id", ""),
        categoria=raw.categoria or src.get("categoria", ""),
        parametro_verificacao=raw.parametro_verificacao or src.get("parametro_verificacao", ""),
        risco_padrao=raw.risco_padrao or src.get("risco_padrao", ""),
        present=raw.present,
        confidence=raw.confidence,
        found_excerpt=raw.found_excerpt,
        proposal_excerpt=raw.proposal_excerpt,
        aligns_with_proposal=raw.aligns_with_proposal,
        page_hint=raw.page_hint,
        observation=raw.observation or "Sem observação.",
        validation_steps=raw.validation_steps or "",
        risk_level=_coerce_risk(raw.risk_level),
    )


def _merge_checks(
    all_checks: list[MatrixParameterCheck],
    matrix_items: list[dict],
    contract_id: str,
    *,
    executive_summary_hint: str = "",
    proposal_used: bool = False,
    proposal_label: str = "",
    analysis_mode: str = "",
) -> ContractMatrixInitialResult:
    item_map = {r["id"]: r for r in matrix_items}
    by_id: dict[str, MatrixParameterCheck] = {}

    for check in all_checks:
        existing = by_id.get(check.item_id)
        if existing is None or (check.present and not existing.present):
            by_id[check.item_id] = check
        elif check.present and existing.present and check.confidence > existing.confidence:
            by_id[check.item_id] = check

    checks: list[MatrixParameterCheck] = []
    for src in matrix_items:
        rid = src["id"]
        if rid in by_id:
            checks.append(by_id[rid])
        else:
            checks.append(
                MatrixParameterCheck(
                    item_id=rid,
                    categoria=src.get("categoria", ""),
                    parametro_verificacao=src.get("parametro_verificacao", ""),
                    risco_padrao=src.get("risco_padrao", ""),
                    present=False,
                    confidence=0.0,
                    observation="Não analisado em nenhum trecho.",
                )
            )

    met = sum(1 for c in checks if c.present)
    total = len(checks)
    critical_gaps: list[str] = []
    risk_alerts: list[str] = []

    for c in checks:
        if not c.present:
            label = f"{c.categoria}: {c.parametro_verificacao[:80]}"
            if c.risk_level == ChangeRisk.HIGH:
                critical_gaps.append(label)
                risk_alerts.append(f"[alto] {label}")
            elif c.risk_level == ChangeRisk.MEDIUM:
                risk_alerts.append(f"[medio] {label}")
        if c.aligns_with_proposal is False:
            label = f"Proposta × contrato — {c.categoria}: {c.parametro_verificacao[:60]}"
            risk_alerts.append(f"[proposta] {label}")

    summaries = [c.observation for c in checks if c.observation and not c.present][:3]
    executive = (executive_summary_hint or "").strip()
    if not executive:
        mode_note = ""
        if analysis_mode == "item_a_item_proposta":
            mode_note = " (verificação item a item com proposta)"
        executive = (
            f"Análise inicial{mode_note}: {met}/{total} parâmetros contemplados no contrato."
            + (" Lacunas: " + "; ".join(summaries) if summaries else "")
        )

    return ContractMatrixInitialResult(
        contract_id=contract_id,
        executive_summary=executive,
        overall_score=met / total if total else 0.0,
        total_items=total,
        items_met=met,
        items_missing=total - met,
        checks=checks,
        critical_gaps=critical_gaps,
        risk_alerts=risk_alerts,
        proposal_used=proposal_used,
        proposal_label=proposal_label,
        analysis_mode=analysis_mode,
        analysis_timestamp=datetime.now(timezone.utc),
    )


def _extract_json_blob(text: str) -> str | None:
    if not text:
        return None
    for needle in ('{"check"', '{"checks"', '{"executive_summary"', "{"):
        start = text.find(needle)
        if start >= 0:
            break
    else:
        return None
    blob = text[start:]
    for marker in ("}. Got:", "}. Got ", "\nFor troubleshooting"):
        idx = blob.find(marker)
        if idx > 0:
            blob = blob[: idx + 1]
            break
    return blob


def _repair_truncated_checks_json(blob: str) -> dict | None:
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        pass
    match = list(re.finditer(r'\},\s*\{"item_id"', blob))
    if match:
        cut = match[-1].start() + 1
        candidate = blob[:cut] + "]}"
        if '"checks"' in blob[:20]:
            candidate = blob[: blob.find("[") + 1] + blob[blob.find("[") + 1 : cut] + "]}"
            try:
                return json.loads(candidate + "}")
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(candidate + "}")
        except json.JSONDecodeError:
            pass
    if '"checks"' in blob and not blob.rstrip().endswith("}"):
        for suffix in ("]}", "}]}"):
            try:
                return json.loads(blob + suffix)
            except json.JSONDecodeError:
                continue
    return None


def _payload_from_dict(data: dict) -> _MatrixChecksPayloadLLM:
    checks: list[_MatrixParameterCheckLLM] = []
    for raw in data.get("checks") or []:
        if not isinstance(raw, dict):
            continue
        try:
            checks.append(_MatrixParameterCheckLLM.model_validate(raw))
        except Exception as exc:
            logger.warning("Check da matriz ignorado (parse): {}", exc)
    return _MatrixChecksPayloadLLM(
        executive_summary=data.get("executive_summary") or "",
        checks=checks,
    )


def _parse_fallback(error_or_raw: str) -> _MatrixChecksPayloadLLM | None:
    blob = _extract_json_blob(error_or_raw)
    if not blob:
        return None
    try:
        data = safe_json_parse(blob)
    except ValueError:
        data = _repair_truncated_checks_json(blob)
    if data:
        if "check" in data and isinstance(data["check"], dict):
            return _MatrixChecksPayloadLLM(checks=[_MatrixParameterCheckLLM.model_validate(data["check"])])
        payload = _payload_from_dict(data)
        if payload.checks:
            logger.warning(
                "Recuperados {} checks de JSON parcial/truncado",
                len(payload.checks),
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


def _proposal_block(proposal_text: str | None, proposal_label: str) -> str:
    if not (proposal_text or "").strip():
        return "PROPOSTA: não informada nesta análise.\n"
    body = _truncate_context(proposal_text, PROPOSAL_CTX_CHARS, "proposta")
    return PROPOSAL_BLOCK.format(
        proposal_label=proposal_label or "Proposta comercial",
        proposal_text=body,
    )


def _invoke_checks_payload(
    contract_text: str,
    matrix_items: list[dict],
    *,
    proposal_text: str | None = None,
    proposal_label: str = "Proposta comercial",
) -> _MatrixChecksPayloadLLM:
    llm = get_llm(temperature=0, max_output_tokens=_analysis_max_tokens())
    structured = llm.with_structured_output(_MatrixChecksPayloadLLM, include_raw=True)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
    )
    chain = prompt | structured
    ctx_contract = _truncate_context(contract_text, CONTRACT_CTX_CHARS, "contrato")
    inputs = {
        "contract_text": ctx_contract,
        "matrix_json": _matrix_for_prompt(matrix_items),
        "item_count": len(matrix_items),
        "proposal_block": _proposal_block(proposal_text, proposal_label),
    }

    try:
        result = chain.invoke(inputs)
    except Exception as exc:
        logger.warning("Structured output falhou, tentando recuperar JSON: {}", exc)
        recovered = _parse_fallback(str(exc))
        if recovered and recovered.checks:
            return recovered
        raise ValueError(
            "A resposta da IA não trouxe a lista de verificações (checks). "
            "Tente novamente ou reduza o tamanho do contrato. "
            f"Detalhe: {exc}"
        ) from exc

    if isinstance(result, dict):
        parsed = result.get("parsed")
        if parsed is not None:
            if isinstance(parsed, _MatrixChecksPayloadLLM):
                return parsed
            return _MatrixChecksPayloadLLM.model_validate(parsed)
        err_text = str(result.get("parsing_error") or "")
        raw_text = _content_from_raw_message(result.get("raw"))
        recovered = _parse_fallback(err_text + raw_text)
        if recovered and recovered.checks:
            return recovered
        raise ValueError(
            "A resposta da IA foi truncada ou inválida. Tente novamente."
        )

    return result


def _invoke_single_item(
    contract_text: str,
    matrix_item: dict,
    *,
    proposal_text: str | None = None,
    proposal_label: str = "Proposta comercial",
) -> _MatrixParameterCheckLLM:
    llm = get_llm(temperature=0, max_output_tokens=_analysis_max_tokens())
    structured = llm.with_structured_output(_MatrixSingleItemPayloadLLM, include_raw=True)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SINGLE_ITEM_SYSTEM_PROMPT), ("user", SINGLE_ITEM_USER_PROMPT)]
    )
    chain = prompt | structured
    ctx_contract = _truncate_context(contract_text, CONTRACT_CTX_CHARS, "contrato")
    inputs = {
        "item_id": matrix_item["id"],
        "categoria": matrix_item.get("categoria", ""),
        "parametro_verificacao": matrix_item.get("parametro_verificacao", ""),
        "risco_padrao": matrix_item.get("risco_padrao", ""),
        "contract_text": ctx_contract,
        "proposal_block": _proposal_block(proposal_text, proposal_label),
    }

    try:
        result = chain.invoke(inputs)
    except Exception as exc:
        logger.warning("Item {} — structured output falhou: {}", matrix_item.get("id"), exc)
        recovered = _parse_fallback(str(exc))
        if recovered and recovered.checks:
            return recovered.checks[0]
        raise ValueError(
            f"Falha ao verificar o item «{matrix_item.get('categoria', '')}». "
            f"Detalhe: {exc}"
        ) from exc

    if isinstance(result, dict):
        parsed = result.get("parsed")
        if parsed is not None:
            if isinstance(parsed, _MatrixSingleItemPayloadLLM):
                return parsed.check
            payload = _MatrixSingleItemPayloadLLM.model_validate(parsed)
            return payload.check
        err_text = str(result.get("parsing_error") or "")
        raw_text = _content_from_raw_message(result.get("raw"))
        recovered = _parse_fallback(err_text + raw_text)
        if recovered and recovered.checks:
            return recovered.checks[0]
        raise ValueError(
            f"Resposta inválida no item «{matrix_item.get('categoria', '')}»."
        )

    return result.check


def _contract_chunks(contract_text: str) -> list[str]:
    if count_tokens(contract_text) <= CHUNK_TOKEN_LIMIT:
        return [contract_text]
    return chunk_text(contract_text)


def _analyze_one_matrix_item(
    contract_text: str,
    matrix_item: dict,
    *,
    proposal_text: str | None,
    proposal_label: str,
) -> MatrixParameterCheck:
    chunks = _contract_chunks(contract_text)
    best: MatrixParameterCheck | None = None

    for chunk in chunks:
        raw = _invoke_single_item(
            chunk,
            matrix_item,
            proposal_text=proposal_text,
            proposal_label=proposal_label,
        )
        check = _llm_check_to_model(raw, matrix_item)
        if best is None:
            best = check
        elif check.present and not best.present:
            best = check
        elif check.present and best.present and check.confidence > best.confidence:
            best = check
        elif not check.present and not best.present and len(check.validation_steps) > len(
            best.validation_steps
        ):
            best = check

    return best or _llm_check_to_model(
        _MatrixParameterCheckLLM(item_id=matrix_item["id"]),
        matrix_item,
    )


def _analyze_per_item(
    contract_text: str,
    matrix_items: list[dict],
    contract_id: str,
    *,
    proposal_text: str | None = None,
    proposal_label: str = "Proposta comercial",
    progress_callback: ProgressCallback | None = None,
    item_complete_callback: ItemCompleteCallback | None = None,
) -> ContractMatrixInitialResult:
    total = len(matrix_items)
    has_proposal = bool((proposal_text or "").strip())
    logger.info(
        "Matriz item a item (proposta={}): {} parâmetros, max_tokens={}",
        has_proposal,
        total,
        _analysis_max_tokens(),
    )
    checks: list[MatrixParameterCheck] = []

    for idx, item in enumerate(matrix_items):
        label = item.get("categoria") or item.get("id", "")
        if progress_callback:
            progress_callback(idx + 1, total, label)
        logger.info("Matriz item {}/{} — {}", idx + 1, total, label)
        check = _analyze_one_matrix_item(
            contract_text,
            item,
            proposal_text=proposal_text,
            proposal_label=proposal_label,
        )
        checks.append(check)
        if item_complete_callback:
            item_complete_callback(check, idx + 1, total)

    summary_hint = f"Verificação item a item ({total} parâmetros)."
    if has_proposal:
        summary_hint += f" Consulta à proposta «{proposal_label}»."

    return _merge_checks(
        checks,
        matrix_items,
        contract_id,
        executive_summary_hint=summary_hint,
        proposal_used=has_proposal,
        proposal_label=proposal_label,
        analysis_mode="item_a_item_proposta" if has_proposal else "item_a_item",
    )


def _analyze_chunk(
    contract_text: str,
    matrix_items: list[dict],
    contract_id: str,
    *,
    proposal_text: str | None = None,
    proposal_label: str = "Proposta comercial",
    analysis_mode: str = "lote",
) -> ContractMatrixInitialResult:
    logger.info(
        "Matriz em lote — chunk ({} tokens), max_tokens={}",
        count_tokens(contract_text),
        _analysis_max_tokens(),
    )
    payload = _invoke_checks_payload(
        contract_text,
        matrix_items,
        proposal_text=proposal_text,
        proposal_label=proposal_label,
    )

    checks: list[MatrixParameterCheck] = []
    for ch in payload.checks:
        src = next((m for m in matrix_items if m["id"] == ch.item_id), {})
        checks.append(_llm_check_to_model(ch, src))

    return _merge_checks(
        checks,
        matrix_items,
        contract_id,
        executive_summary_hint=payload.executive_summary,
        proposal_used=bool((proposal_text or "").strip()),
        proposal_label=proposal_label,
        analysis_mode=analysis_mode,
    )


def check_matrix_against_contract(
    contract_text: str,
    matrix_items: list[dict],
    contract_id: str,
    *,
    proposal_text: str | None = None,
    proposal_label: str = "Proposta comercial",
    progress_callback: ProgressCallback | None = None,
    item_complete_callback: ItemCompleteCallback | None = None,
) -> ContractMatrixInitialResult:
    """
    Verifica parâmetros da matriz no contrato (análise inicial).

    Com item_complete_callback ou proposta: uma chamada à IA por parâmetro.
    Sem proposta e sem callback: análise em lote; contratos grandes usam chunking.
    """
    if not matrix_items:
        raise ValueError("A matriz de verificação está vazia. Configure ao menos um parâmetro.")

    token_count = count_tokens(contract_text)
    has_proposal = bool((proposal_text or "").strip())

    logger.info(
        "check_matrix: {} tokens, {} parâmetros, proposta={}, streaming={}, max_tokens={}",
        token_count,
        len(matrix_items),
        has_proposal,
        item_complete_callback is not None,
        _analysis_max_tokens(),
    )

    if item_complete_callback is not None or has_proposal:
        return _analyze_per_item(
            contract_text,
            matrix_items,
            contract_id,
            proposal_text=proposal_text.strip() if has_proposal else None,
            proposal_label=proposal_label,
            progress_callback=progress_callback,
            item_complete_callback=item_complete_callback,
        )

    if token_count <= CHUNK_TOKEN_LIMIT:
        return _analyze_chunk(
            contract_text,
            matrix_items,
            contract_id,
            proposal_text=None,
            proposal_label=proposal_label,
            analysis_mode="lote",
        )

    logger.warning("Contrato grande ({} tokens); chunking em lote.", token_count)
    chunks = chunk_text(contract_text)
    all_checks: list[MatrixParameterCheck] = []

    for i, chunk in enumerate(chunks):
        logger.info("Chunk matriz lote {}/{}", i + 1, len(chunks))
        partial = _analyze_chunk(
            chunk,
            matrix_items,
            contract_id,
            proposal_text=None,
            proposal_label=proposal_label,
            analysis_mode="lote_chunked",
        )
        all_checks.extend(partial.checks)

    return _merge_checks(
        all_checks,
        matrix_items,
        contract_id,
        proposal_used=False,
        proposal_label=proposal_label,
        analysis_mode="lote_chunked",
    )
