"""Extração de texto e comentários em PDFs reais."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.extractor import (
    compute_comment_stable_id,
    extract_comments,
    extract_comments_from_pdf,
    extract_text,
)


class TestExtractorBGF:
    def test_extract_text_large_pdf(self, bgf_base_pdf: Path) -> None:
        t0 = time.perf_counter()
        text, doc_type = extract_text(str(bgf_base_pdf))
        elapsed = time.perf_counter() - t0
        assert doc_type.value == "pdf"
        assert len(text) > 10_000
        assert elapsed < 15.0, f"Extração lenta: {elapsed:.1f}s"

    def test_extract_all_comments_bgf_base(self, bgf_base_pdf: Path) -> None:
        t0 = time.perf_counter()
        comments = extract_comments_from_pdf(str(bgf_base_pdf))
        elapsed = time.perf_counter() - t0
        assert len(comments) >= 80, f"Esperado ~89 comentários, obteve {len(comments)}"
        assert elapsed < 5.0, f"Extração de comentários lenta: {elapsed:.1f}s"

        for c in comments:
            assert c.get("comment_text", "").strip()
            assert c.get("id")
            assert c.get("stable_id") == c.get("id")
            assert c.get("page", 0) >= 1

    def test_stable_id_is_deterministic(self, bgf_base_pdf: Path) -> None:
        comments = extract_comments_from_pdf(str(bgf_base_pdf))
        assert comments
        c = comments[0]
        sid1 = compute_comment_stable_id(
            str(bgf_base_pdf),
            page=c["page"],
            author=c.get("author", ""),
            comment_text=c["comment_text"],
            referenced_text=c.get("referenced_text", ""),
            date_str=c.get("date", ""),
        )
        sid2 = compute_comment_stable_id(
            str(bgf_base_pdf),
            page=c["page"],
            author=c.get("author", ""),
            comment_text=c["comment_text"],
            referenced_text=c.get("referenced_text", ""),
            date_str=c.get("date", ""),
        )
        assert sid1 == sid2 == c["stable_id"]
        assert len(sid1) == 16

    def test_bgf_revised_has_comments(self, bgf_revised_pdf: Path) -> None:
        comments = extract_comments(str(bgf_revised_pdf))
        assert len(comments) >= 80

    def test_plain_pair_has_no_embedded_comments(self, bgf_plain_pair: tuple[Path, Path]) -> None:
        base, rev = bgf_plain_pair
        assert len(extract_comments(str(base))) == 0
        assert len(extract_comments(str(rev))) == 0

    def test_psi_docx_extracts_all_comments_including_tables(self, psi_bgf_docx: Path) -> None:
        comments = extract_comments(str(psi_bgf_docx))
        assert len(comments) == 21, f"Esperado 21 comentários DOCX, obteve {len(comments)}"
        assert all(c.get("comment_text", "").strip() for c in comments)
        # Comentários em tabela (antes só vinham 17)
        texts = " | ".join(c["comment_text"] for c in comments)
        assert "imagens anexadas" in texts.lower() or "adequações solicitadas" in texts.lower()


class TestExtractorTemp:
    def test_temp_pair_comment_counts(self, temp_compare_pair: tuple[Path, Path]) -> None:
        base, rev = temp_compare_pair
        base_comments = extract_comments(str(base))
        rev_comments = extract_comments(str(rev))
        assert len(base_comments) >= 5
        assert len(rev_comments) >= 1
