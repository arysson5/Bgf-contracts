"""Testa diff entre dois textos de contrato."""

from app.core.differ import compare_versions, get_html_diff

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


def main() -> None:
    print("=== compare_versions (sem IA se sem API key) ===")
    try:
        result = compare_versions(TEXT_A, TEXT_B, "Original", "Revisada", "test-id")
        print(f"Similaridade: {result.similarity_score:.1%}")
        print(f"Adições: {result.total_additions}, Remoções: {result.total_removals}")
        print(f"Resumo: {result.summary[:200]}")
    except ValueError as e:
        print(f"Sem API key — diff numérico apenas: {e}")
        from app.core.differ import _dmp
        from app.core.extractor import normalize_text

        diffs = _dmp.diff_main(normalize_text(TEXT_A), normalize_text(TEXT_B))
        _dmp.diff_cleanupSemantic(diffs)
        adds = sum(1 for op, _ in diffs if op == 1)
        rems = sum(1 for op, _ in diffs if op == -1)
        print(f"Ops adicionadas: {adds}, removidas: {rems}")

    html = get_html_diff(TEXT_A, TEXT_B)
    assert 'class="diff-container"' in html
    assert "<ins" in html or "<del" in html
    print("\n[OK] HTML diff gerado corretamente.")
    print(f"Tamanho HTML: {len(html)} chars")


if __name__ == "__main__":
    main()
