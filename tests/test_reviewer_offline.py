"""Revisão de comentários offline — diff textual, sem OpenAI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.core.extractor import extract_comments_from_pdf, extract_text
from app.core.reviewer import (
    _calibrate_review,
    _evidence_strength,
    _local_diff_verdict,
    format_hunks_for_review,
    review_comments,
    select_relevant_hunks,
)
from app.core.text_diff import compute_text_diff, paragraph_diff_hunks
from app.models.schemas import CommentReview, CommentStatus, TextDiffResult


TEXT_OLD = "O prazo de vigência é de 12 meses conforme cláusula 2."
TEXT_NEW = "O prazo de vigência é de 24 meses conforme cláusula 2."


def _make_paragraph_diff(text_a: str, text_b: str) -> list:
    return paragraph_diff_hunks(text_a, text_b)


class TestDiffBasedReviewer:
    def test_unchanged_excerpt_defers_to_llm(self) -> None:
        review = _local_diff_verdict(
            "Alterar prazo para 24 meses",
            TEXT_OLD,
            [],
        )
        assert review is None

    def test_modified_hunk_marks_attended_locally(self) -> None:
        changed = _make_paragraph_diff(TEXT_OLD, TEXT_NEW)
        relevant = select_relevant_hunks(
            "Alterar prazo para 24 meses",
            "prazo de vigência é de 12 meses",
            changed,
        )
        review = _local_diff_verdict(
            "Alterar prazo para 24 meses",
            "prazo de vigência é de 12 meses",
            relevant,
        )
        assert review is not None
        assert review.status == CommentStatus.ATTENDED
        assert "24" in (review.change_found or "")

    def test_select_hunks_finds_value_in_added_paragraph(self) -> None:
        text_old = "O valor total é R$ 50.000,00 conforme item 3.1."
        text_new = (
            "O valor total é R$ 50.000,00 conforme item 3.1.\n\n"
            "5.1. O valor total de R$ 70.700,00 será pago conforme cronograma."
        )
        relevant = select_relevant_hunks(
            "Ajustar valor para R$ 70.700,00",
            "O valor total é R$ 50.000,00",
            paragraph_diff_hunks(text_old, text_new),
        )
        blocks = format_hunks_for_review(relevant)
        assert "70.700" in blocks

    def test_no_relevant_hunks_means_not_attended_offline(self) -> None:
        text_diff = compute_text_diff(TEXT_OLD, TEXT_OLD, contract_id="same-doc")
        result = review_comments(
            [
                {
                    "id": "c1",
                    "comment_text": "Alterar prazo para 24 meses",
                    "referenced_text": "12 meses",
                    "page": 1,
                }
            ],
            TEXT_OLD,
            TEXT_OLD,
            text_diff,
            "same-doc",
            skip_llm=True,
        )
        assert result.reviews[0].status == CommentStatus.NOT_ATTENDED

    def test_calibrate_keeps_attended_when_diff_exists(self) -> None:
        rev = CommentReview(
            comment_id="x",
            original_comment="Alterar prazo",
            status=CommentStatus.ATTENDED,
            justification="Atendido pela IA.",
            suggested_response="ok",
            change_found="",
        )
        out = _calibrate_review(
            rev,
            "[ALTERADO]\nAntes: 12 meses\nDepois: 13 meses",
            evidence_score=2.0,
            has_diff_blocks=True,
        )
        assert out.status == CommentStatus.ATTENDED

    def test_calibrate_not_attended_without_diff(self) -> None:
        rev = CommentReview(
            comment_id="x",
            original_comment="Alterar prazo",
            status=CommentStatus.ATTENDED,
            justification="Atendido pela IA.",
            suggested_response="ok",
        )
        out = _calibrate_review(
            rev,
            "(nenhum bloco de diferença entre as versões)",
            evidence_score=0.0,
            has_diff_blocks=False,
        )
        assert out.status == CommentStatus.NOT_ATTENDED

    def test_evidence_zero_without_diff_blocks(self) -> None:
        label, score = _evidence_strength(
            "Alterar prazo",
            "12 meses",
            "(nenhum bloco de diferença relacionado a este comentário)",
        )
        assert score == 0.0
        assert "nenhuma" in label

    def test_review_comments_skip_llm_on_bgf(
        self, bgf_base_pdf: Path, bgf_revised_pdf: Path
    ) -> None:
        text_a, _ = extract_text(str(bgf_base_pdf))
        text_b, _ = extract_text(str(bgf_revised_pdf))
        text_diff = compute_text_diff(text_a, text_b, contract_id="rev-test")
        raw = extract_comments_from_pdf(str(bgf_base_pdf))[:15]
        comments = [
            {
                "id": c["stable_id"],
                "comment_text": c["comment_text"],
                "referenced_text": c.get("referenced_text", ""),
                "page": c.get("page", 1),
            }
            for c in raw
        ]
        result = review_comments(
            comments,
            text_a,
            text_b,
            text_diff,
            "rev-test",
            skip_llm=True,
        )
        assert result.total_comments == len(comments)
        assert len(result.reviews) == len(comments)
        for rev in result.reviews:
            assert rev.comment_id
            assert rev.justification

    def test_empty_comments_returns_zero(self) -> None:
        empty_diff = TextDiffResult(
            contract_id="x",
            version_a_label="A",
            version_b_label="B",
            hunks=[],
            analysis_timestamp=datetime.now(timezone.utc),
        )
        result = review_comments([], "a", "b", empty_diff, "x", skip_llm=True)
        assert result.total_comments == 0
