"""Utilitários de segurança — uploads e caminhos de arquivo."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx"}


def sanitize_filename(name: str, *, default: str = "documento") -> str:
    """Remove path traversal e caracteres perigosos do nome do arquivo."""
    base = Path(name).name.strip()
    base = re.sub(r"[^\w.\- ()]", "_", base, flags=re.UNICODE)
    base = base.strip("._ ")
    if not base or base in {".", ".."}:
        base = default
    return base[:180]


def validate_upload_extension(filename: str) -> str:
    """Retorna extensão em minúsculas ou levanta ValueError."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError(
            f"Tipo de arquivo não permitido: {ext or '(sem extensão)'}. "
            f"Use: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
        )
    return ext


def resolve_under(base_dir: Path, *parts: str) -> Path:
    """Garante que o caminho final permanece dentro de base_dir."""
    root = base_dir.resolve()
    dest = (root / Path(*parts)).resolve()
    if dest != root and root not in dest.parents:
        raise ValueError("Caminho de arquivo inválido.")
    return dest


def safe_upload_path(contracts_dir: Path, original_filename: str) -> Path:
    """Caminho seguro para salvar upload em contracts_dir."""
    ext = validate_upload_extension(original_filename)
    safe_name = sanitize_filename(original_filename)
    if not safe_name.lower().endswith(ext):
        safe_name = f"{Path(safe_name).stem}{ext}"
    return resolve_under(contracts_dir, safe_name)


def safe_temp_path(contracts_dir: Path, original_filename: str, prefix: str = "tmp") -> Path:
    """Caminho seguro em contracts/_temp para comparação rápida."""
    ext = validate_upload_extension(original_filename)
    safe_name = sanitize_filename(original_filename)
    uid = uuid.uuid4().hex[:8]
    temp_dir = contracts_dir / "_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    final_name = f"{prefix}_{uid}_{Path(safe_name).stem}{ext}"
    return resolve_under(temp_dir, final_name)
