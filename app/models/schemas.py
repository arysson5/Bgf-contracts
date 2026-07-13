import uuid

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum


class DocumentType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


class DiffType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


class AnalysisMode(str, Enum):
    """Modos de comparação entre versões."""
    TEXT_DIFF = "text_diff"
    DIFERENCAS = "diferencas"
    VALIDACAO = "validacao"
    CRITERIOSA = "criteriosa"


class ChangeRisk(str, Enum):
    LOW = "baixo"
    MEDIUM = "medio"
    HIGH = "alto"


class ChangeCategory(str, Enum):
    CLAUSE_ADDED = "clausula_adicionada"
    CLAUSE_REMOVED = "clausula_removida"
    CLAUSE_MODIFIED = "clausula_alterada"
    COMMERCIAL = "condicoes_comerciais"
    LIABILITY = "responsabilidade"
    TERMINATION = "rescissao"
    CONFIDENTIALITY = "confidencialidade"
    OTHER = "outro"


# --- Localização no documento (PDF ou DOCX) ---

class PdfRect(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class TextLocation(BaseModel):
    """Trecho localizado no arquivo (página PDF ou parágrafo DOCX)."""
    page: int  # página PDF (1-based) ou índice do parágrafo DOCX
    text: str
    rects: list[PdfRect] = []
    match_score: float = 1.0
    document_type: Optional[str] = None  # pdf | docx
    paragraph_index: Optional[int] = None


class DiffLocation(BaseModel):
    change_id: str
    block_type: DiffType
    text: str
    locations: list[TextLocation] = []
    source_version: str = "new"


# --- Análise contratual entre versões ---

class ContractualChange(BaseModel):
    change_id: str
    category: ChangeCategory
    clause_reference: str
    title: str
    description: str
    original_text: Optional[str] = None
    new_text: Optional[str] = None
    legal_impact: str
    affected_party: str = "ambas"
    risk_level: ChangeRisk
    requires_attention: bool
    locations_base: list[TextLocation] = []
    locations_new: list[TextLocation] = []


# --- Checklist ---

class RequirementCheck(BaseModel):
    requirement_id: str
    requirement_text: str
    present: bool
    confidence: float = Field(ge=0.0, le=1.0)
    found_excerpt: Optional[str] = None
    page_hint: Optional[str] = None
    observation: str
    locations: list[TextLocation] = []


class ContractChecklistResult(BaseModel):
    contract_id: str
    overall_score: float = Field(ge=0.0, le=1.0)
    total_requirements: int
    requirements_met: int
    requirements_missing: int
    checks: list[RequirementCheck]
    critical_missing: list[str]
    analysis_timestamp: datetime


# --- Análise inicial por parâmetros de verificação (documento único) ---

class MatrixParameterCheck(BaseModel):
    """Verificação de um parâmetro da matriz no contrato (com referência opcional à proposta)."""
    item_id: str
    categoria: str
    parametro_verificacao: str
    risco_padrao: str = ""
    present: bool
    confidence: float = Field(ge=0.0, le=1.0)
    found_excerpt: Optional[str] = None
    proposal_excerpt: Optional[str] = None
    aligns_with_proposal: Optional[bool] = None
    page_hint: Optional[str] = None
    observation: str
    validation_steps: str = ""
    risk_level: ChangeRisk = ChangeRisk.LOW
    locations: list[TextLocation] = []


class ContractMatrixInitialResult(BaseModel):
    """Resultado da análise inicial do contrato contra a matriz de parâmetros."""
    contract_id: str
    executive_summary: str = ""
    overall_score: float = Field(ge=0.0, le=1.0)
    total_items: int
    items_met: int
    items_missing: int
    checks: list[MatrixParameterCheck]
    critical_gaps: list[str] = []
    risk_alerts: list[str] = []
    proposal_used: bool = False
    proposal_label: str = ""
    analysis_mode: str = ""
    analysis_timestamp: datetime


class VersionRegressionAlert(BaseModel):
    """Alerta: retirada ou enfraquecimento na nova versão vs proposta/matriz."""
    alert_id: str
    title: str
    description: str
    matrix_item_id: Optional[str] = None
    contract_excerpt: Optional[str] = None
    proposal_excerpt: Optional[str] = None
    removed_in_new_version: bool = True
    risk_level: ChangeRisk = ChangeRisk.HIGH
    negotiation_impact: str = ""


class VersionRegressionResult(BaseModel):
    contract_id: str
    base_version_label: str = ""
    new_version_label: str = ""
    proposal_label: str = ""
    executive_summary: str = ""
    alerts: list[VersionRegressionAlert] = []
    analysis_timestamp: datetime


# --- Diff textual determinístico (sem IA) ---

class TextDiffHunk(BaseModel):
    hunk_id: str
    change_type: str  # unchanged | added | removed | modified
    text_a: Optional[str] = None
    text_b: Optional[str] = None
    locations_base: list[TextLocation] = []
    locations_new: list[TextLocation] = []


class TextDiffResult(BaseModel):
    contract_id: str
    version_a_label: str
    version_b_label: str
    hunks: list[TextDiffHunk] = []
    paragraph_hunks: list[TextDiffHunk] = []
    paragraphs_added: int = 0
    paragraphs_removed: int = 0
    paragraphs_modified: int = 0
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    side_by_side_html: str = ""
    inline_diff_html: str = ""
    analysis_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Comparação de versões (análise contratual) ---

class DiffBlock(BaseModel):
    block_type: DiffType
    text: str
    position_start: int
    position_end: int


class ContractDiffResult(BaseModel):
    """Resultado da comparação — análise contratual (não diff de caracteres)."""
    contract_id: str
    version_a_label: str
    version_b_label: str
    executive_summary: str
    recommendation: str
    material_changes_count: int
    high_risk_count: int
    has_significant_changes: bool
    contractual_changes: list[ContractualChange]
    # legado (opcional, não usado na UI principal)
    summary: str = ""
    diff_blocks: list[DiffBlock] = []
    total_additions: int = 0
    total_removals: int = 0
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    diff_locations: list[DiffLocation] = []

    @classmethod
    def from_stored(cls, data: dict) -> "ContractDiffResult":
        """Carrega do JSON do banco — compatível com análises antigas (diff textual)."""
        if "contractual_changes" in data:
            return cls.model_validate(data)
        return cls._from_legacy_diff(data)

    @classmethod
    def _from_legacy_diff(cls, data: dict) -> "ContractDiffResult":
        loc_changes = _legacy_diff_locations_to_changes(data.get("diff_locations") or [])
        block_changes = _legacy_diff_blocks_to_changes(data.get("diff_blocks") or [])
        loc_has_positions = any(c.locations_new or c.locations_base for c in loc_changes)
        if loc_has_positions:
            changes = loc_changes
        elif len(block_changes) > len(loc_changes):
            changes = block_changes
        else:
            changes = loc_changes or block_changes

        summary = (data.get("summary") or "").strip()
        if not summary:
            summary = (
                "Análise salva no formato anterior (comparação textual). "
                "Execute uma nova comparação para obter análise contratual completa."
            )

        material = len(changes) or (data.get("total_additions", 0) + data.get("total_removals", 0))

        return cls(
            contract_id=data["contract_id"],
            version_a_label=data.get("version_a_label", "Original"),
            version_b_label=data.get("version_b_label", "Nova"),
            executive_summary=summary,
            recommendation="",
            material_changes_count=material,
            high_risk_count=0,
            has_significant_changes=data.get("has_significant_changes", material > 0),
            contractual_changes=changes,
            summary=summary,
            diff_blocks=[DiffBlock.model_validate(b) for b in data.get("diff_blocks") or []],
            total_additions=data.get("total_additions", 0),
            total_removals=data.get("total_removals", 0),
            similarity_score=data.get("similarity_score", 0.0),
            diff_locations=[DiffLocation.model_validate(loc) for loc in data.get("diff_locations") or []],
        )


def _legacy_block_title(block_type: str) -> str:
    return {
        "added": "Texto adicionado",
        "removed": "Texto removido",
        "unchanged": "Trecho inalterado",
    }.get(block_type, "Alteração contratual")


def _legacy_block_category(block_type: str) -> ChangeCategory:
    if block_type == "added":
        return ChangeCategory.CLAUSE_ADDED
    if block_type == "removed":
        return ChangeCategory.CLAUSE_REMOVED
    return ChangeCategory.CLAUSE_MODIFIED


def _legacy_diff_locations_to_changes(locations: list) -> list[ContractualChange]:
    changes: list[ContractualChange] = []
    for loc in locations:
        if not isinstance(loc, dict):
            loc = loc.model_dump() if hasattr(loc, "model_dump") else {}
        block_type = loc.get("block_type", "added")
        if block_type == "unchanged":
            continue
        text = (loc.get("text") or "").strip()
        src = loc.get("source_version", "new")
        locs = [TextLocation.model_validate(x) for x in (loc.get("locations") or [])]
        changes.append(
            ContractualChange(
                change_id=loc.get("change_id") or str(uuid.uuid4())[:8],
                category=_legacy_block_category(block_type),
                clause_reference="Alteração (análise anterior)",
                title=_legacy_block_title(block_type),
                description=text[:800] if text else _legacy_block_title(block_type),
                original_text=text if block_type == "removed" else None,
                new_text=text if block_type == "added" else text or None,
                legal_impact="Registrado em análise anterior (diff textual).",
                risk_level=ChangeRisk.MEDIUM,
                requires_attention=True,
                locations_base=locs if src == "base" else [],
                locations_new=locs if src == "new" else [],
            )
        )
    return changes


def _legacy_diff_blocks_to_changes(blocks: list) -> list[ContractualChange]:
    changes: list[ContractualChange] = []
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            block = block.model_dump() if hasattr(block, "model_dump") else {}
        block_type = block.get("block_type", "added")
        if block_type == "unchanged":
            continue
        text = (block.get("text") or "").strip()
        changes.append(
            ContractualChange(
                change_id=f"legacy_{i}",
                category=_legacy_block_category(block_type),
                clause_reference="Trecho alterado",
                title=_legacy_block_title(block_type),
                description=text[:800] if text else _legacy_block_title(block_type),
                original_text=text if block_type == "removed" else None,
                new_text=text if block_type != "removed" else None,
                legal_impact="Registrado em análise anterior (diff textual).",
                risk_level=ChangeRisk.MEDIUM,
                requires_attention=True,
            )
        )
    return changes


# --- Comentários ancorados no documento (revisão integrada) ---

class DocumentCommentSource(str, Enum):
    MANUAL = "manual"
    EXTRACTED = "extracted"
    MATRIX_GAP = "matrix_gap"
    MATRIX_DIVERGENCE = "matrix_divergence"
    CHECKLIST_GAP = "checklist_gap"
    REINFORCEMENT = "reinforcement"


class DocumentCommentDraft(BaseModel):
    """Comentário de revisão a ser fixado no PDF/DOCX."""
    comment_id: str
    comment_text: str
    anchor_text: Optional[str] = None
    source: DocumentCommentSource = DocumentCommentSource.MANUAL
    source_ref: Optional[str] = None
    page_hint: Optional[str] = None
    locations: list[TextLocation] = []
    include_in_export: bool = True


class DocumentCommentsBundle(BaseModel):
    """Comentários pendentes/exportáveis de uma versão do contrato."""
    version_id: str
    contract_id: str
    comments: list[DocumentCommentDraft] = []
    annotated_file_path: Optional[str] = None
    analysis_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Revisão de Comentários (verificação entre versões) ---

class CommentStatus(str, Enum):
    ATTENDED = "attended"
    NOT_ATTENDED = "not_attended"
    PARTIALLY = "partially"


class CommentReview(BaseModel):
    comment_id: str
    original_comment: str
    referenced_excerpt: Optional[str] = None
    status: CommentStatus
    justification: str
    change_found: Optional[str] = None
    suggested_response: str
    matched_hunk_ids: list[str] = []
    locations: list[TextLocation] = []
    locations_base: list[TextLocation] = []
    comment_approved: bool = False


class CommentsReviewResult(BaseModel):
    contract_id: str
    total_comments: int
    attended: int
    not_attended: int
    partially: int
    reviews: list[CommentReview]
    overall_attended_rate: float
    admin_summary: str
    annotated_file_path: Optional[str] = None


# --- Matriz de Análise Proposta x Contrato ---

class MatrixItemStatus(str, Enum):
    CONFORME = "conforme"
    DIVERGENTE = "divergente"
    AUSENTE_CONTRATO = "ausente_contrato"
    AUSENTE_PROPOSTA = "ausente_proposta"
    OBRIGACAO_ADICIONAL = "obrigacao_adicional"


class MatrixItemResult(BaseModel):
    """Resultado da análise de um item da matriz Proposta x Contrato."""
    item_id: str
    categoria: str
    parametro_verificacao: str
    risco_padrao: str = ""
    status: MatrixItemStatus
    contrato_evidencia: Optional[str] = None
    proposta_evidencia: Optional[str] = None
    divergencia: str = ""
    impacto: str = ""
    recomendacao: str = ""
    gera_obrigacao_adicional: bool = False
    risk_level: ChangeRisk = ChangeRisk.MEDIUM
    locations_contrato: list[TextLocation] = []
    locations_proposta: list[TextLocation] = []


class ProposalContractMatrixResult(BaseModel):
    """Relatório consolidado da comparação Proposta técnica/comercial x Contrato."""
    analysis_id: str
    proposal_label: str = "Proposta"
    contract_label: str = "Contrato"
    executive_summary: str
    items: list[MatrixItemResult]
    divergences_count: int
    additional_obligations: list[str] = []
    risk_alerts: list[str] = []
    high_risk_count: int = 0
    analysis_timestamp: datetime
