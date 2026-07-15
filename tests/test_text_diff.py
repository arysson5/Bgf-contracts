"""Testes do diff textual determinístico — sem IA, sem falsos positivos."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.extractor import extract_text
from app.core.text_diff import (
    changed_hunks,
    compile_changed_blocks_digest,
    compute_text_diff,
    get_html_diff,
    paragraph_diff_hunks,
    render_side_by_side_html,
)
from app.models.schemas import AnalysisMode
from app.core.contract_comparator import compare_contracts

TEXT_A = """
CONTRATO DE PRESTAÇÃO DE SERVIÇOS

Cláusula 1 - Objeto
O CONTRATADO prestará serviços de consultoria.

Cláusula 2 - Prazo
O prazo de vigência é de 12 meses.

Cláusula 3 - Pagamento
O pagamento será realizado em 30 dias após a entrega.
"""

TEXT_B = """
CONTRATO DE PRESTAÇÃO DE SERVIÇOS

Cláusula 1 - Objeto
O CONTRATADO prestará serviços de consultoria especializada.

Cláusula 2 - Prazo
O prazo de vigência é de 24 meses.

Cláusula 3 - Pagamento
O pagamento será realizado em 15 dias após a entrega, com multa de 2% por atraso.
"""


class TestTextDiffSynthetic:
    def test_identical_text_zero_changes(self) -> None:
        result = compute_text_diff(TEXT_A, TEXT_A)
        changed = [h for h in result.hunks if h.change_type != "unchanged"]
        assert changed == []
        assert result.similarity_score == 1.0
        assert result.paragraphs_added == 0
        assert result.paragraphs_removed == 0
        assert result.paragraphs_modified == 0

    def test_real_changes_detected(self) -> None:
        result = compute_text_diff(TEXT_A, TEXT_B)
        changed = [h for h in result.hunks if h.change_type != "unchanged"]
        assert len(changed) >= 2
        assert result.similarity_score < 1.0
        html = result.side_by_side_html or ""
        assert "especializada" in html or "multa" in html
        assert any(h.change_type == "added" for h in changed)

    def test_html_markers(self) -> None:
        html = get_html_diff(TEXT_A, TEXT_B)
        assert "bgf-diff" in html
        assert "bgf-diff-added" in html or "bgf-diff-removed" in html

    def test_side_by_side_html_structure(self) -> None:
        html = render_side_by_side_html(TEXT_A, TEXT_B, label_a="Base", label_b="Revisada")
        assert "Base" in html and "Revisada" in html
        assert "bgf-diff-side" in html

    def test_diff_is_fast_on_synthetic(self) -> None:
        big_a = TEXT_A * 50
        big_b = TEXT_B * 50
        t0 = time.perf_counter()
        compute_text_diff(big_a, big_b)
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"Diff sintético lento: {elapsed:.2f}s"


class TestTextDiffRealContracts:
    def test_identical_extracted_text_no_false_positives(
        self, bgf_base_pdf: Path, bgf_revised_pdf: Path
    ) -> None:
        """BGF base × revisão: texto extraído idêntico → zero alterações."""
        text_a, _ = extract_text(str(bgf_base_pdf))
        text_b, _ = extract_text(str(bgf_revised_pdf))
        assert text_a == text_b, "Pré-condição: textos extraídos devem ser iguais"

        t0 = time.perf_counter()
        result = compute_text_diff(text_a, text_b, label_a="BGF", label_b="BGF revisão")
        elapsed = time.perf_counter() - t0

        changed = [h for h in result.hunks if h.change_type != "unchanged"]
        assert changed == [], f"Falso positivo: {len(changed)} hunk(s) em textos idênticos"
        assert result.similarity_score == 1.0
        assert elapsed < 8.0, f"Diff em ~56k chars demorou {elapsed:.1f}s (meta < 8s)"

    def test_real_differences_in_temp_pair(self, temp_compare_pair: tuple[Path, Path]) -> None:
        base, rev = temp_compare_pair
        text_a, _ = extract_text(str(base))
        text_b, _ = extract_text(str(rev))
        assert text_a != text_b

        t0 = time.perf_counter()
        result = compute_text_diff(text_a, text_b)
        elapsed = time.perf_counter() - t0

        changed = [h for h in result.hunks if h.change_type != "unchanged"]
        assert len(changed) >= 1
        assert result.similarity_score < 1.0
        assert elapsed < 3.0, f"Diff par _temp lento: {elapsed:.2f}s"

    def test_compile_changed_blocks_digest(self) -> None:
        result = compute_text_diff(TEXT_A, TEXT_B)
        digest = compile_changed_blocks_digest(result.hunks)
        assert "[ALTERADO]" in digest or "[ADICIONADO]" in digest
        assert changed_hunks(result.hunks)

    def test_paragraph_diff_hunks_whole_paragraph(self) -> None:
        old = "O prazo de vigência é de 12 meses conforme cláusula 2."
        new = "O prazo de vigência é de 24 meses conforme cláusula 2."
        hunks = paragraph_diff_hunks(old, new)
        assert len(hunks) == 1
        assert hunks[0].change_type == "modified"
        assert "12" in (hunks[0].text_a or "")
        assert "24" in (hunks[0].text_b or "")

    def test_paragraph_diff_hunks_includes_neighbor_context(self) -> None:
        old = "Intro\n\nPrazo 12 meses\n\nRodapé"
        new = "Intro\n\nPrazo 24 meses\n\nRodapé"
        hunks = paragraph_diff_hunks(old, new, context_paragraphs=1)
        assert len(hunks) == 1
        assert "Intro" in (hunks[0].text_a or "")
        assert "Rodapé" in (hunks[0].text_b or "")
        assert "12" in (hunks[0].text_a or "")
        assert "24" in (hunks[0].text_b or "")

    def test_compare_contracts_text_diff_mode_no_llm(
        self, bgf_base_pdf: Path, bgf_revised_pdf: Path
    ) -> None:
        text_a, _ = extract_text(str(bgf_base_pdf))
        text_b, _ = extract_text(str(bgf_revised_pdf))
        result = compare_contracts(
            text_a,
            text_b,
            "Base",
            "Revisada",
            "test-bgf",
            mode=AnalysisMode.TEXT_DIFF,
        )
        material = [c for c in result.contractual_changes if c.requires_attention]
        assert material == []
        assert result.similarity_score == 1.0
        assert not isinstance(result, tuple)
