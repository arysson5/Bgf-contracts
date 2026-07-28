"""Pipeline LangChain — checklist de requisitos via OpenAI."""

from datetime import datetime, timezone

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from app.core.llm import get_llm
from app.models.schemas import ContractChecklistResult, RequirementCheck
from app.utils.helpers import chunk_text, count_tokens, format_requirements_for_prompt


SYSTEM_PROMPT = """Você é um especialista em análise de contratos jurídicos brasileiros.
Analise o contrato fornecido e verifique cada requisito da lista.
Seja preciso: só marque como presente se encontrar evidência clara no texto.
Responda em português nas observações."""

USER_PROMPT = """Contrato:
{contract_text}

Requisitos para verificar:
{requirements_json}

Para cada requisito informe: present (true/false), confidence (0-1),
found_excerpt (trecho exato ou null), page_hint (ex: Cláusula 3), observation (justificativa)."""


def _build_requirements_list(requirements: list[dict]) -> list[dict]:
    return [
        {
            "id": r["id"],
            "text": r["text"],
            "is_critical": r.get("is_critical", False),
        }
        for r in requirements
    ]


def _merge_chunk_results(
    all_checks: list[RequirementCheck],
    requirements: list[dict],
    contract_id: str,
) -> ContractChecklistResult:
    """Consolida resultados de múltiplos chunks — presente se qualquer chunk encontrou."""
    req_map = {r["id"]: r for r in requirements}
    by_id: dict[str, RequirementCheck] = {}

    for check in all_checks:
        existing = by_id.get(check.requirement_id)
        if existing is None or (check.present and not existing.present):
            by_id[check.requirement_id] = check
        elif check.present and existing.present and check.confidence > existing.confidence:
            by_id[check.requirement_id] = check

    checks: list[RequirementCheck] = []
    for req in requirements:
        rid = req["id"]
        if rid in by_id:
            checks.append(by_id[rid])
        else:
            checks.append(
                RequirementCheck(
                    requirement_id=rid,
                    requirement_text=req["text"],
                    present=False,
                    confidence=0.0,
                    observation="Não analisado em nenhum trecho.",
                )
            )

    met = sum(1 for c in checks if c.present)
    total = len(checks)
    critical_missing = [
        c.requirement_text
        for c in checks
        if not c.present and req_map.get(c.requirement_id, {}).get("is_critical")
    ]

    return ContractChecklistResult(
        contract_id=contract_id,
        overall_score=met / total if total else 0.0,
        total_requirements=total,
        requirements_met=met,
        requirements_missing=total - met,
        checks=checks,
        critical_missing=critical_missing,
        analysis_timestamp=datetime.now(timezone.utc),
    )


def _analyze_chunk(
    contract_text: str,
    requirements: list[dict],
    contract_id: str,
) -> ContractChecklistResult:
    llm = get_llm(temperature=0)
    structured = llm.with_structured_output(ContractChecklistResult)

    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
    )
    chain = prompt | structured
    req_json = format_requirements_for_prompt(_build_requirements_list(requirements))

    logger.info("Analisando chunk ({} tokens)", count_tokens(contract_text))
    result: ContractChecklistResult = chain.invoke(
        {"contract_text": contract_text, "requirements_json": req_json}
    )
    result.contract_id = contract_id
    return result


def check_requirements(
    contract_text: str,
    requirements: list[dict],
    contract_id: str,
) -> ContractChecklistResult:
    """
    Verifica requisitos no contrato via OpenAI.
    Contratos > 6000 tokens usam map-reduce por chunks.
    """
    token_count = count_tokens(contract_text)
    logger.info("check_requirements: {} tokens, {} requisitos", token_count, len(requirements))

    if token_count <= 6000:
        return _analyze_chunk(contract_text, requirements, contract_id)

    logger.warning("Contrato grande ({} tokens); aplicando chunking.", token_count)
    chunks = chunk_text(contract_text)
    all_checks: list[RequirementCheck] = []

    for i, chunk in enumerate(chunks):
        logger.info("Processando chunk {}/{}", i + 1, len(chunks))
        partial = _analyze_chunk(chunk, requirements, contract_id)
        all_checks.extend(partial.checks)

    return _merge_chunk_results(all_checks, requirements, contract_id)
