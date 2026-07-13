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
