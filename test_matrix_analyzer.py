"""Testes offline do matrix_analyzer (sem chamar a API OpenAI).

Verifica a derivação de obrigações adicionais / alertas de risco e o mapeamento
dos itens da matriz a partir de uma resposta simulada da IA.
"""

from app.core.matrix_analyzer import (
    MatrixItemLLM,
    _MatrixPayloadLLM,
    _build_results,
    _merge_passes,
    build_alerts,
)
from app.models.schemas import ChangeRisk, MatrixItemResult, MatrixItemStatus


def _sample_matrix() -> list[dict]:
    return [
        {"id": "row-1", "categoria": "Escopo / Objeto", "parametro_verificacao": "Cobertura do escopo", "risco_padrao": "Expansão"},
        {"id": "row-2", "categoria": "Valor", "parametro_verificacao": "Valor total x proposta", "risco_padrao": "Custo extra"},
        {"id": "row-3", "categoria": "Tributos", "parametro_verificacao": "Reajuste", "risco_padrao": "Fiscal"},
    ]


def test_build_alerts() -> None:
    items = [
        MatrixItemResult(
            item_id="row-1", categoria="Escopo / Objeto",
            parametro_verificacao="Cobertura do escopo",
            status=MatrixItemStatus.CONFORME, risk_level=ChangeRisk.LOW,
        ),
        MatrixItemResult(
            item_id="row-2", categoria="Valor",
            parametro_verificacao="Valor total x proposta",
            status=MatrixItemStatus.OBRIGACAO_ADICIONAL,
            divergencia="Despesas reembolsáveis não previstas.",
            gera_obrigacao_adicional=True, risk_level=ChangeRisk.HIGH,
        ),
        MatrixItemResult(
            item_id="row-3", categoria="Tributos",
            parametro_verificacao="Reajuste",
            status=MatrixItemStatus.DIVERGENTE,
            divergencia="Índice IPCA vs INCC.", risk_level=ChangeRisk.MEDIUM,
        ),
    ]
    obligations, alerts = build_alerts(items)
    assert len(obligations) == 1, obligations
    assert "Valor" in obligations[0]
    # row-2 (obrigação adicional, alto) e row-3 (divergente, medio) geram alertas
    assert len(alerts) == 2, alerts
    assert any(a.startswith("[alto]") for a in alerts)
    print("[OK] build_alerts")


def test_build_results_fills_missing() -> None:
    payload = _MatrixPayloadLLM(
        executive_summary="ok",
        items=[
            MatrixItemLLM(
                item_id="row-2", status=MatrixItemStatus.DIVERGENTE,
                divergencia="Valor diverge", risk_level=ChangeRisk.HIGH,
            )
        ],
    )
    results = _build_results(payload, _sample_matrix(), None, None)
    assert len(results) == 3
    by_id = {r.item_id: r for r in results}
    # item retornado pela IA preserva status/risco
    assert by_id["row-2"].status == MatrixItemStatus.DIVERGENTE
    assert by_id["row-2"].risk_level == ChangeRisk.HIGH
    # itens ausentes na resposta caem em conforme/baixo (não inventa divergência)
    assert by_id["row-1"].status == MatrixItemStatus.CONFORME
    assert by_id["row-1"].risk_level == ChangeRisk.LOW
    # categoria e parâmetro vêm da matriz fonte
    assert by_id["row-1"].categoria == "Escopo / Objeto"
    print("[OK] _build_results")


def test_merge_passes_keeps_most_severe() -> None:
    p1 = _MatrixPayloadLLM(items=[MatrixItemLLM(item_id="row-1", status=MatrixItemStatus.CONFORME)])
    p2 = _MatrixPayloadLLM(items=[MatrixItemLLM(item_id="row-1", status=MatrixItemStatus.DIVERGENTE)])
    merged = _merge_passes([p1, p2])
    by_id = {it.item_id: it for it in merged.items}
    assert by_id["row-1"].status == MatrixItemStatus.DIVERGENTE
    print("[OK] _merge_passes")


def main() -> None:
    test_build_alerts()
    test_build_results_fills_missing()
    test_merge_passes_keeps_most_severe()
    print("\n[OK] matrix_analyzer (offline) passou em todos os testes.")


if __name__ == "__main__":
    main()
