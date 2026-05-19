"""Banco SQLite via SQLModel — CRUD e engine."""

import json
from typing import TypeVar

from pydantic import BaseModel
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    AnalysisResult,
    Contract,
    ContractVersion,
    Requirement,
    RequirementTemplate,
    utc_now,
)
from app.models.schemas import DocumentType
from app.utils.datetime_br import brazil_today, to_brazil_time
from app.utils.settings import get_settings

T = TypeVar("T", bound=BaseModel)

# Reexportar modelos para compatibilidade: from app.db.database import Contract
__all__ = [
    "AnalysisResult",
    "Contract",
    "ContractVersion",
    "Requirement",
    "RequirementTemplate",
    "init_db",
    "get_engine",
    "get_session",
    "create_contract",
    "get_contract",
    "get_contracts",
    "update_contract_timestamp",
    "add_version",
    "get_version",
    "get_versions",
    "save_analysis_result",
    "get_analysis_results",
    "get_recent_analyses",
    "count_analyses_today",
    "load_analysis_json",
    "get_analysis_by_id",
    "get_analyses_for_contract",
    "get_contracts_by_client",
    "create_requirement_template",
    "add_requirement",
    "get_templates",
    "get_requirements",
    "delete_requirements_for_template",
]

# --- Engine ---

_engine = None
_db_ready = False


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            f"sqlite:///{settings.db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _engine


def init_db(*, force: bool = False) -> None:
    """Inicializa schema e seed — executa uma vez por processo (salvo force=True)."""
    global _db_ready
    if _db_ready and not force:
        return
    SQLModel.metadata.create_all(get_engine())
    _seed_default_template()
    _db_ready = True


def _seed_default_template() -> None:
    """Cria template padrão se o banco estiver vazio."""
    if get_templates():
        return
    tpl = create_requirement_template("Contrato Padrão")
    defaults = [
        ("Cláusula de confidencialidade", True),
        ("Prazo de vigência definido", True),
        ("Foro de eleição", True),
        ("Multa por descumprimento", False),
        ("Cláusula de rescisão", False),
    ]
    for i, (text, critical) in enumerate(defaults):
        add_requirement(tpl.id, text, critical, i)


def get_session() -> Session:
    return Session(get_engine())


# --- CRUD Contratos ---

def create_contract(name: str, client_name: str) -> Contract:
    contract = Contract(name=name, client_name=client_name)
    with get_session() as session:
        session.add(contract)
        session.commit()
        session.refresh(contract)
    return contract


def get_contract(contract_id: str) -> Contract | None:
    with get_session() as session:
        return session.get(Contract, contract_id)


def get_contracts() -> list[Contract]:
    with get_session() as session:
        return list(session.exec(select(Contract).order_by(Contract.updated_at.desc())).all())


def update_contract_timestamp(contract_id: str) -> None:
    with get_session() as session:
        contract = session.get(Contract, contract_id)
        if contract:
            contract.updated_at = utc_now()
            session.add(contract)
            session.commit()


# --- CRUD Versões ---

def add_version(
    contract_id: str,
    label: str,
    file_path: str,
    file_type: DocumentType | str,
    text: str,
) -> ContractVersion:
    ft = file_type.value if isinstance(file_type, DocumentType) else file_type
    with get_session() as session:
        existing = session.exec(
            select(ContractVersion).where(ContractVersion.contract_id == contract_id)
        ).all()
        version_number = len(existing) + 1
        version = ContractVersion(
            contract_id=contract_id,
            version_number=version_number,
            label=label,
            file_path=file_path,
            file_type=ft,
            extracted_text=text,
        )
        session.add(version)
        session.commit()
        session.refresh(version)
    update_contract_timestamp(contract_id)
    return version


def get_version(version_id: str) -> ContractVersion | None:
    with get_session() as session:
        return session.get(ContractVersion, version_id)


def get_versions(contract_id: str) -> list[ContractVersion]:
    with get_session() as session:
        rows = session.exec(
            select(ContractVersion)
            .where(ContractVersion.contract_id == contract_id)
            .order_by(ContractVersion.version_number)
        ).all()
        return list(rows)


# --- CRUD Análises ---

def save_analysis_result(
    version_id: str,
    analysis_type: str,
    result_pydantic: BaseModel,
) -> AnalysisResult:
    payload = result_pydantic.model_dump_json()
    record = AnalysisResult(
        version_id=version_id,
        analysis_type=analysis_type,
        result_json=payload,
    )
    with get_session() as session:
        session.add(record)
        session.commit()
        session.refresh(record)
    return record


def get_analysis_results(version_id: str) -> list[AnalysisResult]:
    with get_session() as session:
        rows = session.exec(
            select(AnalysisResult)
            .where(AnalysisResult.version_id == version_id)
            .order_by(AnalysisResult.created_at.desc())
        ).all()
        return list(rows)


def get_recent_analyses(limit: int = 5) -> list[AnalysisResult]:
    with get_session() as session:
        rows = session.exec(
            select(AnalysisResult).order_by(AnalysisResult.created_at.desc()).limit(limit)
        ).all()
        return list(rows)


def count_analyses_today() -> int:
    today = brazil_today()
    with get_session() as session:
        rows = session.exec(select(AnalysisResult)).all()
        return sum(
            1
            for r in rows
            if r.created_at and to_brazil_time(r.created_at).date() == today
        )


def load_analysis_json(record: AnalysisResult) -> dict:
    return json.loads(record.result_json)


def get_analysis_by_id(analysis_id: str) -> AnalysisResult | None:
    with get_session() as session:
        return session.get(AnalysisResult, analysis_id)


def get_analyses_for_contract(contract_id: str) -> list[tuple[AnalysisResult, ContractVersion]]:
    """Retorna análises salvas de todas as versões do contrato."""
    versions = get_versions(contract_id)
    version_map = {v.id: v for v in versions}
    results: list[tuple[AnalysisResult, ContractVersion]] = []
    for vid in version_map:
        for rec in get_analysis_results(vid):
            results.append((rec, version_map[vid]))
    results.sort(key=lambda x: x[0].created_at, reverse=True)
    return results


def get_contracts_by_client(client_name: str) -> list[Contract]:
    with get_session() as session:
        rows = session.exec(
            select(Contract)
            .where(Contract.client_name.contains(client_name))
            .order_by(Contract.updated_at.desc())
        ).all()
        return list(rows)


# --- CRUD Templates ---

def create_requirement_template(name: str) -> RequirementTemplate:
    template = RequirementTemplate(name=name)
    with get_session() as session:
        session.add(template)
        session.commit()
        session.refresh(template)
    return template


def add_requirement(
    template_id: str,
    text: str,
    is_critical: bool,
    order: int,
) -> Requirement:
    req = Requirement(
        template_id=template_id,
        text=text,
        is_critical=is_critical,
        order=order,
    )
    with get_session() as session:
        session.add(req)
        session.commit()
        session.refresh(req)
    return req


def get_templates() -> list[RequirementTemplate]:
    with get_session() as session:
        return list(
            session.exec(
                select(RequirementTemplate).order_by(RequirementTemplate.name)
            ).all()
        )


def get_requirements(template_id: str) -> list[Requirement]:
    with get_session() as session:
        rows = session.exec(
            select(Requirement)
            .where(Requirement.template_id == template_id)
            .order_by(Requirement.order)
        ).all()
        return list(rows)


def delete_requirements_for_template(template_id: str) -> None:
    with get_session() as session:
        rows = session.exec(
            select(Requirement).where(Requirement.template_id == template_id)
        ).all()
        for row in rows:
            session.delete(row)
        session.commit()
