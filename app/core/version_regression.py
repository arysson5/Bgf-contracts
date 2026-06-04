"""Detecta retiradas na nova versão que prejudicam a negociação (proposta + matriz)."""

import json
import re
import uuid
from datetime import datetime, timezone

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.core.llm import get_llm
from app.models.schemas import (
    ChangeRisk,
    ContractDiffResult,
    VersionRegressionAlert,
    VersionRegressionResult,
)
from app.utils.helpers import safe_json_parse
from app.utils.settings import get_settings


def _analysis_max_tokens() -> int:
    return max(4096, get_settings().max_tokens)


class _RegressionAlertLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    description: str = ""
    matrix_item_id: str = ""
    contract_excerpt: str | None = None
    proposal_excerpt: str | None = None
    removed_in_new_version: bool = True
    risk_level: ChangeRisk = ChangeRisk.HIGH
    negotiation_impact: str = ""


class _RegressionPayloadLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: str = ""
    alerts: list[_RegressionAlertLLM] = Field(default_factory=list)


SYSTEM_PROMPT = """Você é advogado analisando a 2ª (ou posterior) revisão de um contrato.
Compare a VERSÃO BASE com a VERSÃO NOVA do cliente, usando a PROPOSTA COMERCIAL e a MATRIZ
como referência do que foi negociado.

Identifique alertas quando na VERSÃO NOVA:
- Foi retirado ou enfraquecido algo que existia na base e está na proposta/matriz;
- Surge lacuna que prejudica a BGF na negociação com o cliente;
- O cliente removeu obrigação, escopo, prazo ou condição que a proposta já havia consolidado.

Para cada alerta: title, description, matrix_item_id (se aplicável), contract_excerpt,
proposal_excerpt, removed_in_new_version, risk_level, negotiation_impact.
Máx. 400 caracteres por excerpt. JSON válido."""

USER_PROMPT = """MATRIZ:
{matrix_json}

PROPOSTA — {proposal_label}:
{proposal_text}

VERSÃO BASE — {label_base}:
{base_text}

VERSÃO NOVA — {label_new}:
{new_text}

RESUMO DO DIFF JURÍDICO:
{diff_summary}

Liste alertas de regressão que prejudicam a negociação."""


def _matrix_for_prompt(items: list[dict]) -> str:
    lines = []
    for it in items:
        lines.append(
            f"- id={it['id']} | {it.get('categoria', '')} | {it.get('parametro_verificacao', '')}"
        )
    return "\n".join(lines)


def _extract_json_blob(text: str) -> str | None:
    if not text:
        return None
    for needle in ('{"alerts"', '{"executive_summary"', "{"):
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


def _parse_fallback(error_or_raw: str) -> _RegressionPayloadLLM | None:
    blob = _extract_json_blob(error_or_raw)
    if not blob:
        return None
    try:
        data = safe_json_parse(blob)
    except ValueError:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            return None
    alerts = []
    for raw in data.get("alerts") or []:
        if isinstance(raw, dict):
            try:
                alerts.append(_RegressionAlertLLM.model_validate(raw))
            except Exception:
                pass
    if alerts:
        return _RegressionPayloadLLM(
            executive_summary=data.get("executive_summary") or "",
            alerts=alerts,
        )
    return None


def _content_from_raw_message(raw) -> str:
    if raw is None:
        return ""
    content = getattr(raw, "content", raw)
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
            if isinstance(b, (dict, str))
        )
    return str(content)


def analyze_version_regression(
    base_text: str,
    new_text: str,
    proposal_text: str,
    matrix_items: list[dict],
    diff_result: ContractDiffResult,
    contract_id: str,
    *,
    label_base: str = "Base",
    label_new: str = "Nova",
    proposal_label: str = "Proposta",
) -> VersionRegressionResult:
    if not (proposal_text or "").strip():
        return VersionRegressionResult(
            contract_id=contract_id,
            base_version_label=label_base,
            new_version_label=label_new,
            proposal_label=proposal_label,
            executive_summary="Proposta não cadastrada — análise de regressão não executada.",
            alerts=[],
            analysis_timestamp=datetime.now(timezone.utc),
        )

    diff_summary = diff_result.executive_summary or diff_result.summary or ""
    changes_snip = [
        f"- {ch.title}: {ch.description[:200]}"
        for ch in (diff_result.contractual_changes or [])[:15]
    ]
    if changes_snip:
        diff_summary += "\n" + "\n".join(changes_snip)

    llm = get_llm(temperature=0, max_output_tokens=_analysis_max_tokens())
    structured = llm.with_structured_output(_RegressionPayloadLLM, include_raw=True)
    chain = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
    ) | structured

    inputs = {
        "matrix_json": _matrix_for_prompt(matrix_items),
        "proposal_label": proposal_label,
        "proposal_text": proposal_text[:120000],
        "label_base": label_base,
        "label_new": label_new,
        "base_text": base_text[:80000],
        "new_text": new_text[:80000],
        "diff_summary": diff_summary[:8000],
    }

    payload: _RegressionPayloadLLM | None = None
    try:
        result = chain.invoke(inputs)
        if isinstance(result, dict):
            parsed = result.get("parsed")
            if parsed:
                payload = (
                    parsed
                    if isinstance(parsed, _RegressionPayloadLLM)
                    else _RegressionPayloadLLM.model_validate(parsed)
                )
            else:
                recovered = _parse_fallback(
                    str(result.get("parsing_error") or "")
                    + _content_from_raw_message(result.get("raw"))
                )
                payload = recovered
        else:
            payload = result
    except Exception as exc:
        logger.warning("Regressão structured output falhou: {}", exc)
        payload = _parse_fallback(str(exc))

    if not payload:
        payload = _RegressionPayloadLLM(
            executive_summary="Não foi possível analisar regressões automaticamente.",
            alerts=[],
        )

    alerts: list[VersionRegressionAlert] = []
    for a in payload.alerts:
        alerts.append(
            VersionRegressionAlert(
                alert_id=str(uuid.uuid4())[:8],
                title=a.title or "Regressão detectada",
                description=a.description or "",
                matrix_item_id=a.matrix_item_id or None,
                contract_excerpt=(a.contract_excerpt or "")[:400] or None,
                proposal_excerpt=(a.proposal_excerpt or "")[:400] or None,
                removed_in_new_version=a.removed_in_new_version,
                risk_level=a.risk_level,
                negotiation_impact=a.negotiation_impact or a.description,
            )
        )

    return VersionRegressionResult(
        contract_id=contract_id,
        base_version_label=label_base,
        new_version_label=label_new,
        proposal_label=proposal_label,
        executive_summary=payload.executive_summary,
        alerts=alerts,
        analysis_timestamp=datetime.now(timezone.utc),
    )
