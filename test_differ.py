"""Testa diff entre dois textos de contrato."""

from app.core.text_diff import get_html_diff


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


def test_get_html_diff_marks_changes() -> None:
    html = get_html_diff(TEXT_A, TEXT_B)
    assert "bgf-diff" in html
    assert "bgf-diff-added" in html or "bgf-diff-removed" in html
    assert "consultoria" in html


def test_get_html_diff_unchanged_blocks() -> None:
    html = get_html_diff(TEXT_A, TEXT_A)
    assert "bgf-diff-same" in html
