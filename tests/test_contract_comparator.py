"""Pipeline IA (Validação/Criteriosa) — ruído cosmético não vira alteração material."""

from __future__ import annotations

from app.core.contract_comparator import (
    compare_from_hunks,
    validate_hunks_as_changes,
    validate_signing_version,
)
from app.core.text_diff import compute_text_diff
from app.models.schemas import ChangeCategory, ChangeRisk, ContractualChange, TextDiffHunk

COSMETIC_A = "Cláusula de confidencialidade.\n\nO contrato permanece válido."
COSMETIC_B = "CLÁUSULA de confidencialidade.\n\nO  contrato permanece válido."

PRAZO_A = (
    "CONTRATO DE PRESTAÇÃO DE SERVIÇOS\n\n"
    "O prazo de vigência é de 12 meses.\n\n"
    "Encerramento."
)
PRAZO_B = (
    "CONTRATO DE PRESTAÇÃO DE SERVIÇOS\n\n"
    "O prazo de vigência é de 24 meses.\n\n"
    "Encerramento."
)


def _change_from_hunk(hunk: TextDiffHunk, *, title: str) -> ContractualChange:
    return ContractualChange(
        change_id=hunk.hunk_id,
        category=ChangeCategory.CLAUSE_MODIFIED,
        clause_reference="§2",
        title=title,
        description=title,
        original_text=hunk.text_a,
        new_text=hunk.text_b,
        legal_impact="Prazo contratual alterado.",
        risk_level=ChangeRisk.HIGH,
        requires_attention=True,
    )


class TestCriteriosaSkipsNoise:
    def test_cosmetic_only_does_not_call_llm(self, monkeypatch) -> None:
        called: list[str] = []

        def fake_analyze(hunk, index, total):  # noqa: ARG001
            called.append(hunk.hunk_id)
            return []

        monkeypatch.setattr(
            "app.core.contract_comparator._analyze_hunk_llm",
            fake_analyze,
        )
        diff = compute_text_diff(COSMETIC_A, COSMETIC_B)
        result = compare_from_hunks(
            diff.hunks, COSMETIC_A, COSMETIC_B, "Base", "Revisada", "cid-cos"
        )
        assert called == []
        assert result.contractual_changes == []
        assert result.material_changes_count == 0
        assert result.has_significant_changes is False

    def test_empty_llm_response_discards_hunk(self, monkeypatch) -> None:
        def fake_analyze(hunk, index, total):  # noqa: ARG001
            return []

        monkeypatch.setattr(
            "app.core.contract_comparator._analyze_hunk_llm",
            fake_analyze,
        )
        diff = compute_text_diff(PRAZO_A, PRAZO_B)
        result = compare_from_hunks(
            diff.hunks, PRAZO_A, PRAZO_B, "Base", "Revisada", "cid-empty"
        )
        assert result.contractual_changes == []
        assert result.material_changes_count == 0

    def test_real_prazo_change_stays_material(self, monkeypatch) -> None:
        def fake_analyze(hunk, index, total):  # noqa: ARG001
            blob = f"{hunk.text_a or ''} {hunk.text_b or ''}"
            if "12" in blob or "24" in blob:
                return [_change_from_hunk(hunk, title="12 meses → 24 meses")]
            return []

        monkeypatch.setattr(
            "app.core.contract_comparator._analyze_hunk_llm",
            fake_analyze,
        )
        diff = compute_text_diff(PRAZO_A, PRAZO_B)
        result = compare_from_hunks(
            diff.hunks, PRAZO_A, PRAZO_B, "Base", "Revisada", "cid-prazo"
        )
        assert result.material_changes_count >= 1
        assert result.has_significant_changes is True
        assert any(
            "24" in (c.title or "") or "24" in (c.new_text or "")
            for c in result.contractual_changes
        )


class TestValidacaoSkipsNoise:
    def test_cosmetic_only_does_not_call_llm(self, monkeypatch) -> None:
        def boom(*_args, **_kwargs):
            raise AssertionError("LLM não deve ser chamada para ruído cosmético")

        monkeypatch.setattr("app.core.contract_comparator.get_llm", boom)
        diff = compute_text_diff(COSMETIC_A, COSMETIC_B)
        result = validate_signing_version(
            diff.hunks,
            COSMETIC_A,
            COSMETIC_B,
            "Acordada",
            "Assinatura",
            "cid-val",
            similarity_score=1.0,
        )
        assert result.contractual_changes == []
        assert result.material_changes_count == 0
        assert result.has_significant_changes is False

    def test_fallback_rules_ignore_cosmetic(self) -> None:
        hunks = [
            TextDiffHunk(
                hunk_id="cos",
                change_type="modified",
                text_a="O contrato.",
                text_b="O  contrato",
            ),
            TextDiffHunk(
                hunk_id="mov",
                change_type="moved",
                text_a="Bloco idêntico reposicionado.",
            ),
        ]
        result = validate_hunks_as_changes(
            hunks, "O contrato. Bloco.", "O  contrato Bloco.", "A", "B", "cid-fb"
        )
        assert result.contractual_changes == []
        assert result.material_changes_count == 0

    def test_fallback_keeps_prazo_content(self) -> None:
        hunk = TextDiffHunk(
            hunk_id="prazo",
            change_type="modified",
            text_a="O prazo de vigência é de 12 meses.",
            text_b="O prazo de vigência é de 24 meses.",
        )
        result = validate_hunks_as_changes(
            [hunk],
            hunk.text_a or "",
            hunk.text_b or "",
            "A",
            "B",
            "cid-fb-prazo",
        )
        assert len(result.contractual_changes) == 1
        assert result.material_changes_count >= 1
        assert "12" in (result.contractual_changes[0].title or "") or "12" in (
            result.contractual_changes[0].original_text or ""
        )
