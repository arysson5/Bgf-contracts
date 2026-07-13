"""Testa revisão de comentários — requer GOOGLE_API_KEY."""

from app.core.reviewer import review_comments
from app.core.text_diff import compute_text_diff

TEXT_ORIGINAL = """
Cláusula 3 - Pagamento
O pagamento será realizado em 30 dias após a entrega do serviço.
"""

TEXT_NEW = """
Cláusula 3 - Pagamento
O pagamento será realizado em 15 dias após a entrega do serviço,
sujeito a multa de 2% por atraso.
"""

COMMENTS = [
    {
        "id": "c1",
        "page": 1,
        "comment_text": "Reduzir prazo de pagamento para 15 dias",
        "referenced_text": "pagamento será realizado em 30 dias",
        "author": "Admin",
        "date": "",
    },
    {
        "id": "c2",
        "page": 1,
        "comment_text": "Incluir multa por atraso de 2%",
        "referenced_text": "pagamento será realizado",
        "author": "Admin",
        "date": "",
    },
    {
        "id": "c3",
        "page": 2,
        "comment_text": "Adicionar cláusula de propriedade intelectual",
        "referenced_text": "",
        "author": "Admin",
        "date": "",
    },
]


def main() -> None:
    text_diff = compute_text_diff(TEXT_ORIGINAL, TEXT_NEW, contract_id="test")
    result = review_comments(COMMENTS, TEXT_ORIGINAL, TEXT_NEW, text_diff, "test")
    print(result.admin_summary)
    for r in result.reviews:
        print(f"\n[{r.status.value}] {r.original_comment}")
        print(f"  -> {r.suggested_response[:120]}...")


if __name__ == "__main__":
    main()
