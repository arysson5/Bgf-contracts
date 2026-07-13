"""Índice de embeddings dos blocos de diff textual com localização no PDF/DOCX."""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from app.core.document_locator import find_in_document
from app.core.embeddings import cosine_similarity, embed_query, embed_texts, embeddings_available
from app.core.text_diff import format_hunk_block, paragraph_diff_hunks
from app.models.schemas import TextDiffHunk, TextLocation


def _hunk_embed_text(hunk: TextDiffHunk) -> str:
    """Texto representativo do bloco para embedding."""
    if hunk.change_type == "added":
        return f"[ADICIONADO] {hunk.text_b or ''}"
    if hunk.change_type == "removed":
        return f"[REMOVIDO] {hunk.text_a or ''}"
    return f"[ALTERADO] antes: {hunk.text_a or ''} | depois: {hunk.text_b or ''}"


def _attach_hunk_locations(
    hunk: TextDiffHunk,
    path_base: str | None,
    path_new: str | None,
) -> None:
    if path_base and hunk.text_a:
        hunk.locations_base = find_in_document(path_base, hunk.text_a[:500])
    if path_new:
        query = (hunk.text_b or hunk.text_a or "").strip()
        if query:
            hunk.locations_new = find_in_document(path_new, query[:500])


def location_label(loc: TextLocation) -> str:
    if loc.document_type == "docx" and loc.paragraph_index is not None:
        return f"¶{loc.paragraph_index + 1}"
    return f"Pág. {loc.page}"


def format_hunk_block_with_location(hunk: TextDiffHunk, *, index: int | None = None) -> str:
    block = format_hunk_block(hunk, index=index)
    loc_bits: list[str] = []
    if hunk.locations_base:
        loc_bits.append(f"base {location_label(hunk.locations_base[0])}")
    if hunk.locations_new:
        loc_bits.append(f"revisada {location_label(hunk.locations_new[0])}")
    if loc_bits:
        block = f"{block}\n📍 Localização: {', '.join(loc_bits)}"
    return block


@dataclass
class ScoredHunk:
    hunk: TextDiffHunk
    score: float
    source: str = "embedding"  # embedding | fuzzy


@dataclass
class DiffHunkIndex:
    """Índice em memória: hunks + vetores para busca semântica leve."""

    hunks: list[TextDiffHunk] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)
    uses_embeddings: bool = False

    @classmethod
    def build(
        cls,
        text_a: str,
        text_b: str,
        path_base: str | None = None,
        path_new: str | None = None,
        *,
        use_embeddings: bool = True,
    ) -> DiffHunkIndex:
        hunks = paragraph_diff_hunks(text_a, text_b, context_paragraphs=3)
        for hunk in hunks:
            _attach_hunk_locations(hunk, path_base, path_new)

        vectors: list[list[float]] = []
        active_embeddings = use_embeddings and embeddings_available()
        if active_embeddings and hunks:
            vectors = embed_texts([_hunk_embed_text(h) for h in hunks])
            if len(vectors) != len(hunks):
                logger.warning("Embeddings incompletos — fallback para busca fuzzy")
                vectors = []
                active_embeddings = False

        logger.info(
            "Índice de diff: {} bloco(s), embeddings={}",
            len(hunks),
            active_embeddings,
        )
        return cls(hunks=hunks, vectors=vectors, uses_embeddings=active_embeddings)

    def digest_for_hunks(self, hunks: list[TextDiffHunk]) -> str:
        if not hunks:
            return "(nenhum bloco de diferença entre as versões)"
        return "\n\n".join(
            format_hunk_block_with_location(h, index=i) for i, h in enumerate(hunks, 1)
        )

    def full_digest(self) -> str:
        """Compilado completo — todos os blocos com localização (enviado à IA)."""
        return self.digest_for_hunks(self.hunks)

    def rank_blocks(
        self,
        query: str,
        original_excerpt: str = "",
        *,
        top_k: int = 5,
    ) -> list[ScoredHunk]:
        """Ranking para UI/navegação — não limita o que a IA recebe."""
        if not self.hunks:
            return []

        if self.uses_embeddings and self.vectors:
            q_vec = embed_query(f"{query}\n{original_excerpt}".strip())
            if q_vec:
                scored = [
                    ScoredHunk(hunk=h, score=cosine_similarity(q_vec, vec), source="embedding")
                    for h, vec in zip(self.hunks, self.vectors, strict=True)
                ]
                scored.sort(key=lambda item: item.score, reverse=True)
                return scored[:top_k]

        fuzzy_hunks = self._fuzzy_search(query, original_excerpt, top_k)
        return [
            ScoredHunk(hunk=h, score=self._fuzzy_score(h, query, original_excerpt), source="fuzzy")
            for h in fuzzy_hunks
        ]

    def search(
        self,
        query: str,
        original_excerpt: str = "",
        *,
        top_k: int = 5,
        min_similarity: float = 0.38,
    ) -> list[ScoredHunk]:
        """Alias legado — preferir rank_blocks."""
        ranked = self.rank_blocks(query, original_excerpt, top_k=top_k)
        if min_similarity <= 0:
            return ranked
        return [s for s in ranked if s.score >= min_similarity]

    def _fuzzy_search(self, query: str, original_excerpt: str, top_k: int) -> list[TextDiffHunk]:
        from app.core.reviewer import select_relevant_hunks

        return select_relevant_hunks(query, original_excerpt, self.hunks, max_hunks=top_k)

    def _fuzzy_score(self, hunk: TextDiffHunk, query: str, original_excerpt: str) -> float:
        from app.core.reviewer import _score_hunk_relevance

        return _score_hunk_relevance(hunk, query, original_excerpt) / 10.0

    def collect_locations(
        self,
        hunks: list[TextDiffHunk],
        *,
        side: str = "new",
    ) -> list[TextLocation]:
        locs: list[TextLocation] = []
        seen: set[str] = set()
        for hunk in hunks:
            source = hunk.locations_new if side == "new" else hunk.locations_base
            for loc in source:
                key = f"{loc.page}:{loc.paragraph_index}:{loc.text[:40]}"
                if key in seen:
                    continue
                seen.add(key)
                locs.append(loc)
        return locs[:6]
