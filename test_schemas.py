"""Testa instanciação de todos os schemas Pydantic com dados fake."""

from datetime import datetime, timezone

from app.models.schemas import (
    ChangeRisk,
    CommentReview,
    CommentsReviewResult,
    CommentStatus,
    ContractChecklistResult,
    ContractDiffResult,
    ContractMatrixInitialResult,
    DiffBlock,
    DiffType,
    DocumentType,
    MatrixItemResult,
    MatrixItemStatus,
    MatrixParameterCheck,
    ProposalContractMatrixResult,
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
        executive_summary="Alterações menores em cláusulas de pagamento.",
        recommendation="Revisar prazo de pagamento.",
        material_changes_count=2,
        high_risk_count=0,
        has_significant_changes=False,
        contractual_changes=[],
        diff_blocks=[block],
        total_additions=3,
        total_removals=1,
        similarity_score=0.92,
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

    print("\n=== MatrixItemResult + ProposalContractMatrixResult ===")
    item = MatrixItemResult(
        item_id="row-1",
        categoria="Valor e Modelo de Precificação",
        parametro_verificacao="Comparar valor total do contrato x valor da proposta.",
        risco_padrao="Custo extra fora do escopo",
        status=MatrixItemStatus.OBRIGACAO_ADICIONAL,
        contrato_evidencia="R$ 79.830,00 referente ao serviço.",
        proposta_evidencia="R$ 14.370,00 de despesas reembolsáveis.",
        divergencia="Despesas de viagem reembolsáveis não previstas no valor fechado.",
        impacto="Possível custo adicional ao contratante.",
        recomendacao="Formalizar reembolso via aditivo.",
        gera_obrigacao_adicional=True,
        risk_level=ChangeRisk.HIGH,
    )
    matrix = ProposalContractMatrixResult(
        analysis_id="matrix-abc",
        proposal_label="Proposta 51042026",
        contract_label="Contrato BVV",
        executive_summary="Identificadas divergências em valor e documentação.",
        items=[item],
        divergences_count=1,
        additional_obligations=["Valor: despesas reembolsáveis não previstas."],
        risk_alerts=["[alto] Valor: despesas reembolsáveis não previstas."],
        high_risk_count=1,
        analysis_timestamp=datetime.now(timezone.utc),
    )
    print(matrix.model_dump_json(indent=2))
    restored = ProposalContractMatrixResult.model_validate_json(matrix.model_dump_json())
    assert restored.divergences_count == 1
    assert restored.items[0].status == MatrixItemStatus.OBRIGACAO_ADICIONAL

    print("\n=== MatrixParameterCheck + ContractMatrixInitialResult ===")
    param = MatrixParameterCheck(
        item_id="m-1",
        categoria="Escopo",
        parametro_verificacao="Objeto do contrato alinhado ao QR.",
        present=True,
        confidence=0.9,
        observation="Cláusula 1 descreve o objeto.",
    )
    initial = ContractMatrixInitialResult(
        contract_id="contract-abc",
        overall_score=1.0,
        total_items=1,
        items_met=1,
        items_missing=0,
        checks=[param],
        analysis_timestamp=datetime.now(timezone.utc),
    )
    print(initial.model_dump_json(indent=2))

    print("\n[OK] Todos os schemas instanciados com sucesso.")


if __name__ == "__main__":
    main()
