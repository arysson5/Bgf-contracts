"""Testes do índice de diff com embeddings (offline — sem API)."""

from __future__ import annotations

from app.core.diff_index import DiffHunkIndex, location_label
from app.core.embeddings import cosine_similarity
from app.models.schemas import TextLocation


class TestDiffHunkIndex:
    def test_build_attaches_locations_offline(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.core.diff_index.embeddings_available",
            lambda: False,
        )
        monkeypatch.setattr(
            "app.core.diff_index.embed_texts",
            lambda texts: [],
        )

        text_old = "Cláusula 3.\n\nO prazo é de 12 meses."
        text_new = "Cláusula 3.\n\nO prazo é de 24 meses."
        index = DiffHunkIndex.build(text_old, text_new, use_embeddings=False)
        assert len(index.hunks) == 1
        assert index.hunks[0].change_type == "modified"
        assert "24" in (index.hunks[0].text_b or "")

    def test_full_digest_includes_all_blocks(self, monkeypatch) -> None:
        monkeypatch.setattr("app.core.diff_index.embeddings_available", lambda: False)
        text_old = "A.\n\nB antigo.\n\nC."
        text_new = "A.\n\nB novo.\n\nC.\n\nD adicionado."
        index = DiffHunkIndex.build(text_old, text_new, use_embeddings=False)
        digest = index.full_digest()
        assert "B antigo" in digest
        assert "B novo" in digest
        assert "D adicionado" in digest

    def test_rank_blocks_fuzzy_without_embeddings(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.core.diff_index.embeddings_available",
            lambda: False,
        )
        text_old = "O pagamento será em 30 dias."
        text_new = "O pagamento será em 15 dias."
        index = DiffHunkIndex.build(text_old, text_new, use_embeddings=False)
        hits = index.rank_blocks("Reduzir prazo para 15 dias", "pagamento será em 30 dias")
        assert hits
        assert hits[0].source == "fuzzy"

    def test_digest_includes_location_labels(self) -> None:
        from app.models.schemas import TextDiffHunk

        hunk = TextDiffHunk(
            hunk_id="abc",
            change_type="modified",
            text_a="antes",
            text_b="depois",
            locations_new=[
                TextLocation(page=4, text="depois", document_type="pdf"),
            ],
        )
        index = DiffHunkIndex(hunks=[hunk], vectors=[], uses_embeddings=False)
        digest = index.digest_for_hunks([hunk])
        assert "Pág. 4" in digest
        assert location_label(hunk.locations_new[0]) == "Pág. 4"

    def test_cosine_similarity(self) -> None:
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_collect_locations_dedupes(self) -> None:
        from app.models.schemas import TextDiffHunk

        loc = TextLocation(page=2, text="x", document_type="pdf")
        h1 = TextDiffHunk(
            hunk_id="1",
            change_type="modified",
            text_a="a",
            text_b="b",
            locations_new=[loc],
        )
        h2 = TextDiffHunk(
            hunk_id="2",
            change_type="added",
            text_b="c",
            locations_new=[loc],
        )
        index = DiffHunkIndex(hunks=[h1, h2])
        locs = index.collect_locations([h1, h2], side="new")
        assert len(locs) == 1
