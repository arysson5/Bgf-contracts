"""Fixtures compartilhadas — contratos reais em contracts/."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


@pytest.fixture(scope="session")
def contracts_dir() -> Path:
    return CONTRACTS


@pytest.fixture(scope="session")
def bgf_base_pdf(contracts_dir: Path) -> Path:
    path = contracts_dir / "BVVPRESTACAODESERVICOSBGFConsultoriaemEngenharia27042026 - BGF.pdf"
    if not path.is_file():
        pytest.skip(f"Contrato base não encontrado: {path.name}")
    return path


@pytest.fixture(scope="session")
def bgf_revised_pdf(contracts_dir: Path) -> Path:
    path = contracts_dir / "BVVPRESTACAODESERVICOSBGFConsultoriaemEngenharia27042026 - BGF_revisao.pdf"
    if not path.is_file():
        pytest.skip(f"Contrato revisado não encontrado: {path.name}")
    return path


@pytest.fixture(scope="session")
def bgf_plain_pair(contracts_dir: Path) -> tuple[Path, Path]:
    base = contracts_dir / "BVVPRESTACAODESERVICOSBGFConsultoriaemEngenharia27042026.pdf"
    rev = contracts_dir / "BVVPRESTACAODESERVICOSBGFConsultoriaemEngenharia27042026_revisao.pdf"
    if not base.is_file() or not rev.is_file():
        pytest.skip("Par sem sufixo BGF não disponível")
    return base, rev


@pytest.fixture(scope="session")
def psi_bgf_docx(contracts_dir: Path) -> Path:
    path = contracts_dir / "2026.04.14 - Contrato de Prestação de Serviços - PSI x BGF (v.05) - BGF.docx"
    if not path.is_file():
        pytest.skip(f"Contrato DOCX não encontrado: {path.name}")
    return path


@pytest.fixture(scope="session")
def temp_compare_pair(contracts_dir: Path) -> tuple[Path, Path]:
    """Par opcional em contracts/_temp/ para testes de diff/comentários reais."""
    temp_dir = contracts_dir / "_temp"
    if not temp_dir.is_dir():
        pytest.skip("Pasta contracts/_temp/ não disponível")
    bases = sorted(temp_dir.glob("a_*_comentarios.pdf"))
    revs = sorted(temp_dir.glob("b_*_devolutiva_revisao.pdf"))
    if not bases or not revs:
        pytest.skip("Par a_*_comentarios / b_*_devolutiva_revisao não encontrado em _temp/")
    return bases[0], revs[0]
