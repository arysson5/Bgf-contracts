"""Modelos SQLModel — tabelas do banco (módulo separado para evitar redefinição no Streamlit)."""

import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

# Permite hot-reload do Streamlit sem InvalidRequestError na mesma MetaData
_TABLE_ARGS = {"extend_existing": True}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Contract(SQLModel, table=True):
    __tablename__ = "contract"
    __table_args__ = _TABLE_ARGS

    id: str = Field(primary_key=True, default_factory=new_id)
    name: str
    client_name: str
    proposal_file_path: str = ""
    proposal_file_type: str = ""
    proposal_extracted_text: str = ""
    proposal_label: str = "Proposta comercial"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ContractVersion(SQLModel, table=True):
    __tablename__ = "contract_version"
    __table_args__ = _TABLE_ARGS

    id: str = Field(primary_key=True, default_factory=new_id)
    contract_id: str = Field(foreign_key="contract.id", index=True)
    version_number: int
    label: str
    file_path: str
    file_type: str  # pdf | docx
    extracted_text: str = ""
    uploaded_at: datetime = Field(default_factory=utc_now)


class RequirementTemplate(SQLModel, table=True):
    __tablename__ = "requirement_template"
    __table_args__ = _TABLE_ARGS

    id: str = Field(primary_key=True, default_factory=new_id)
    name: str
    created_at: datetime = Field(default_factory=utc_now)


class Requirement(SQLModel, table=True):
    __tablename__ = "requirement"
    __table_args__ = _TABLE_ARGS

    id: str = Field(primary_key=True, default_factory=new_id)
    template_id: str = Field(foreign_key="requirement_template.id", index=True)
    text: str
    is_critical: bool = False
    order: int = 0


class AnalysisResult(SQLModel, table=True):
    __tablename__ = "analysis_result"
    __table_args__ = _TABLE_ARGS

    id: str = Field(primary_key=True, default_factory=new_id)
    version_id: str = Field(foreign_key="contract_version.id", index=True)
    analysis_type: str  # checklist | diff | comments | matrix
    result_json: str
    created_at: datetime = Field(default_factory=utc_now)


class MatrixTemplate(SQLModel, table=True):
    __tablename__ = "matrix_template"
    __table_args__ = _TABLE_ARGS

    id: str = Field(primary_key=True, default_factory=new_id)
    name: str
    created_at: datetime = Field(default_factory=utc_now)


class MatrixItem(SQLModel, table=True):
    __tablename__ = "matrix_item"
    __table_args__ = _TABLE_ARGS

    id: str = Field(primary_key=True, default_factory=new_id)
    template_id: str = Field(foreign_key="matrix_template.id", index=True)
    categoria: str
    parametro_verificacao: str
    risco_padrao: str = ""
    order: int = 0
