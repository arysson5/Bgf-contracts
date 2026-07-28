"""
API REST complementar ao Streamlit (Contract Analyzer).

Arquitetura:
- Streamlit (app/main.py + pages/) = UI principal para analistas jurídicos.
- FastAPI (este módulo) = endpoints leves para integrações, health-check e
  visualização externa (ex.: viewer PDF.js). Compartilha o mesmo banco SQLite,
  settings (.env) e módulos core (text_diff, extractor).
- Execute com: uvicorn app.api.main:app --reload --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core.text_diff import compute_text_diff, get_html_diff
from app.utils.settings import get_settings

app = FastAPI(
    title="BGF Contract Analyzer API",
    description="Endpoints complementares ao Streamlit",
    version="1.0.0",
)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


class TextDiffRequest(BaseModel):
    text_a: str = Field(..., description="Texto da versão base")
    text_b: str = Field(..., description="Texto da versão revisada")
    label_a: str = "Base"
    label_b: str = "Revisada"
    contract_id: str = ""


class TextDiffResponse(BaseModel):
    similarity_score: float
    paragraphs_added: int
    paragraphs_removed: int
    paragraphs_modified: int
    paragraphs_moved: int = 0
    inline_diff_html: str
    side_by_side_html: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/text-diff", response_model=TextDiffResponse)
def api_text_diff(body: TextDiffRequest) -> TextDiffResponse:
    result = compute_text_diff(
        body.text_a,
        body.text_b,
        contract_id=body.contract_id,
        label_a=body.label_a,
        label_b=body.label_b,
    )
    return TextDiffResponse(
        similarity_score=result.similarity_score,
        paragraphs_added=result.paragraphs_added,
        paragraphs_removed=result.paragraphs_removed,
        paragraphs_modified=result.paragraphs_modified,
        paragraphs_moved=result.paragraphs_moved,
        inline_diff_html=result.inline_diff_html,
        side_by_side_html=result.side_by_side_html,
    )


def _resolve_document_path(path: str) -> Path:
    """Resolve caminho somente dentro de contracts_dir (read-only)."""
    settings = get_settings()
    base = settings.contracts_path.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if base not in candidate.parents and candidate != base:
        raise HTTPException(status_code=403, detail="Acesso ao arquivo negado.")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return candidate


@app.get("/api/document/{file_path:path}")
def api_document(file_path: str) -> FileResponse:
    """Serve PDF/DOCX do diretório de contratos (somente leitura)."""
    resolved = _resolve_document_path(file_path)
    media = "application/pdf" if resolved.suffix.lower() == ".pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(resolved, media_type=media, filename=resolved.name)


@app.get("/viewer", response_class=HTMLResponse)
def viewer_placeholder() -> HTMLResponse:
    """Redireciona para o viewer PDF.js estático."""
    viewer = _STATIC_DIR / "viewer.html"
    if not viewer.is_file():
        raise HTTPException(status_code=404, detail="viewer.html não encontrado.")
    return HTMLResponse(viewer.read_text(encoding="utf-8"))
