"""Banco SQLite via SQLModel — CRUD e engine."""

import json
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    AnalysisResult,
    Contract,
    ContractVersion,
    MatrixItem,
    MatrixTemplate,
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
    "MatrixItem",
    "MatrixTemplate",
    "Requirement",
    "RequirementTemplate",
    "init_db",
    "get_engine",
    "get_session",
    "create_contract",
    "get_contract",
    "get_contracts",
    "set_contract_proposal",
    "contract_has_proposal",
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
    "create_matrix_template",
    "add_matrix_item",
    "get_matrix_templates",
    "get_matrix_items",
    "delete_matrix_items_for_template",
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
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _migrate_contract_proposal_columns(engine)
    _seed_default_template()
    _seed_default_matrix()
    _db_ready = True


def _migrate_contract_proposal_columns(engine) -> None:
    """Adiciona colunas de proposta em bancos SQLite já existentes."""
    columns = [
        ("proposal_file_path", "TEXT NOT NULL DEFAULT ''"),
        ("proposal_file_type", "TEXT NOT NULL DEFAULT ''"),
        ("proposal_extracted_text", "TEXT NOT NULL DEFAULT ''"),
        ("proposal_label", "TEXT NOT NULL DEFAULT 'Proposta comercial'"),
    ]
    with engine.connect() as conn:
        for name, ddl in columns:
            try:
                conn.execute(text(f"ALTER TABLE contract ADD COLUMN {name} {ddl}"))
                conn.commit()
            except Exception:
                pass


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


def _seed_default_matrix() -> None:
    """Cria a matriz padrão Proposta x Contrato (editável) se não existir nenhuma."""
    if get_matrix_templates():
        return
    tpl = create_matrix_template("Proposta x Contrato (BGF)")
    defaults = [
        (
            "Escopo / Objeto",
            "Verificar se todo o escopo do contrato está contemplado na proposta; "
            "atividades adicionais da proposta ausentes no contrato; exclusões/limitações "
            "e obrigações implícitas (assistente do cliente, técnico da mantenedora).",
            "Expansão de escopo não prevista / passivo contratual",
        ),
        (
            "Cronograma e Prazos",
            "Comparar prazos de mobilização, execução em campo e entrega de relatórios; "
            "matriz GUT e acompanhamento; condicionantes de início (aceite, kickoff, formulário).",
            "Prazo operacional divergente do prazo contratual",
        ),
        (
            "Entregáveis e Resultados",
            "Comparar entregáveis: relatórios técnicos, checklists, planilha GUT, ART, reunião "
            "de fechamento, plataforma digital, evidências fotográficas/termografia.",
            "Entregável previsto sem contrapartida na proposta",
        ),
        (
            "Documentação",
            "Conferir documentos legais/regulatórios (bombeiros, alvarás, licenças), projetos/plantas, "
            "certificados (elevadores, HVAC, SPDA, elétrica, incêndio), CND/ART/CREA. Quem fornece e prazo.",
            "Dependência documental gerando atraso na execução",
        ),
        (
            "Itens Incluídos vs. Excluídos",
            "Analisar se exclusões explícitas da proposta estão cobertas pelo contrato e se inclusões "
            "criam obrigação adicional (áreas privativas, obras, ensaios laboratoriais, finais de semana).",
            "Conflito operacional/financeiro de escopo",
        ),
        (
            "Valor e Modelo de Precificação",
            "Comparar valor total do contrato x valor detalhado da proposta; despesas inclusas/não inclusas "
            "(passagens, hospedagem, alimentação, veículos); reembolso e nota de débito.",
            "Custo extra fora do escopo contratual",
        ),
        (
            "Forma e Prazo de Pagamento",
            "Comparar percentuais/fases (ex.: 30%/70% ou por fase), vencimentos, retenção em garantia, "
            "multa/juros/atualização por atraso.",
            "Divergência no fluxo financeiro",
        ),
        (
            "Condições Operacionais e Jurídicas",
            "Verificar confidencialidade, validade da proposta, início condicionado à assinatura, seguros e "
            "responsabilidade civil, e divergências de obrigações (ex.: não realizar obras).",
            "Insegurança jurídica / ampliação de passivo",
        ),
        (
            "Tributos e Reajuste",
            "Conferir tributação (PIS, COFINS, CSLL, IRRF, ISS) e condições de reajuste anual "
            "(IPCA/INCC/IGP-M) ou revisão por mudança tributária.",
            "Divergência fiscal ou de reajuste",
        ),
    ]
    for i, (categoria, parametro, risco) in enumerate(defaults):
        add_matrix_item(tpl.id, categoria, parametro, risco, i)


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


def set_contract_proposal(
    contract_id: str,
    file_path: str,
    file_type: str,
    extracted_text: str,
    label: str = "Proposta comercial",
) -> Contract | None:
    with get_session() as session:
        contract = session.get(Contract, contract_id)
        if not contract:
            return None
        contract.proposal_file_path = file_path
        contract.proposal_file_type = file_type
        contract.proposal_extracted_text = extracted_text
        contract.proposal_label = label or "Proposta comercial"
        contract.updated_at = utc_now()
        session.add(contract)
        session.commit()
        session.refresh(contract)
    return contract


def contract_has_proposal(contract: Contract | None) -> bool:
    if not contract:
        return False
    return bool(
        (contract.proposal_extracted_text or "").strip()
        or (contract.proposal_file_path or "").strip()
    )


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


# --- CRUD Matriz Proposta x Contrato ---

def create_matrix_template(name: str) -> MatrixTemplate:
    template = MatrixTemplate(name=name)
    with get_session() as session:
        session.add(template)
        session.commit()
        session.refresh(template)
    return template


def add_matrix_item(
    template_id: str,
    categoria: str,
    parametro_verificacao: str,
    risco_padrao: str,
    order: int,
) -> MatrixItem:
    item = MatrixItem(
        template_id=template_id,
        categoria=categoria,
        parametro_verificacao=parametro_verificacao,
        risco_padrao=risco_padrao,
        order=order,
    )
    with get_session() as session:
        session.add(item)
        session.commit()
        session.refresh(item)
    return item


def get_matrix_templates() -> list[MatrixTemplate]:
    with get_session() as session:
        return list(
            session.exec(
                select(MatrixTemplate).order_by(MatrixTemplate.name)
            ).all()
        )


def get_matrix_items(template_id: str) -> list[MatrixItem]:
    with get_session() as session:
        rows = session.exec(
            select(MatrixItem)
            .where(MatrixItem.template_id == template_id)
            .order_by(MatrixItem.order)
        ).all()
        return list(rows)


def delete_matrix_items_for_template(template_id: str) -> None:
    with get_session() as session:
        rows = session.exec(
            select(MatrixItem).where(MatrixItem.template_id == template_id)
        ).all()
        for row in rows:
            session.delete(row)
        session.commit()
