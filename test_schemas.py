"""Testa instanciação de todos os schemas Pydantic com dados fake."""

from datetime import datetime, timezone

from app.models.schemas import (
    CommentReview,
    CommentsReviewResult,
    CommentStatus,
    ContractChecklistResult,
    ContractDiffResult,
    DiffBlock,
    DiffType,
    DocumentType,
    RequirementCheck,
)


def main() -> None:
    print("=== DocumentType ===")
    print(DocumentType.PDF, DocumentType.DOCX)

    print("\n=== RequirementCheck ===")
    rc = RequirementCheck(
        requirement_id="req-1",
        requirement_text="Cláusula de confidencialidade",
        present=True,
        confidence=0.95,
        found_excerpt="As partes comprometem-se a manter sigilo...",
        page_hint="Cláusula 8",
        observation="Encontrada cláusula explícita de confidencialidade.",
    )
    print(rc.model_dump_json(indent=2))

    print("\n=== ContractChecklistResult ===")
    checklist = ContractChecklistResult(
        contract_id="contract-abc",
        overall_score=0.8,
        total_requirements=5,
        requirements_met=4,
        requirements_missing=1,
        checks=[rc],
        critical_missing=["Prazo de vigência"],
        analysis_timestamp=datetime.now(timezone.utc),
    )
    print(checklist.model_dump_json(indent=2))

    print("\n=== DiffBlock + ContractDiffResult ===")
    block = DiffBlock(
        block_type=DiffType.ADDED,
        text="Novo parágrafo adicionado.",
        position_start=100,
        position_end=130,
    )
    diff = ContractDiffResult(
        contract_id="contract-abc",
        version_a_label="Original",
        version_b_label="Versão Cliente 1",
        diff_blocks=[block],
        total_additions=3,
        total_removals=1,
        similarity_score=0.92,
        has_significant_changes=False,
        summary="Alterações menores em cláusulas de pagamento.",
    )
    print(diff.model_dump_json(indent=2))

    print("\n=== CommentReview + CommentsReviewResult ===")
    review = CommentReview(
        comment_id="cmt-1",
        original_comment="Incluir multa por atraso",
        referenced_excerpt="O pagamento será realizado em 30 dias.",
        status=CommentStatus.PARTIALLY,
        justification="Multa mencionada mas percentual não especificado.",
        change_found="Adicionada referência a penalidades.",
        suggested_response="Agradecemos a alteração. Solicitamos especificar o percentual da multa.",
    )
    comments_result = CommentsReviewResult(
        contract_id="contract-abc",
        total_comments=3,
        attended=1,
        not_attended=1,
        partially=1,
        reviews=[review],
        overall_attended_rate=0.33,
        admin_summary="2 de 3 comentários precisam de atenção adicional.",
    )
    print(comments_result.model_dump_json(indent=2))

    print("\n[OK] Todos os schemas instanciados com sucesso.")


if __name__ == "__main__":
    main()
