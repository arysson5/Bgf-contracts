"""Testa checklist — requer OPENAI_API_KEY no .env."""

from app.core.checker import check_requirements

FAKE_CONTRACT = """
CONTRATO DE PRESTAÇÃO DE SERVIÇOS

Cláusula 1 - Objeto: consultoria empresarial.
Cláusula 2 - Confidencialidade: as partes manterão sigilo sobre informações trocadas.
Cláusula 3 - Vigência: 12 meses a partir da assinatura.
Cláusula 4 - Foro: Comarca de São Paulo/SP.
"""

REQUIREMENTS = [
    {"id": "r1", "text": "Cláusula de confidencialidade", "is_critical": True},
    {"id": "r2", "text": "Prazo de vigência definido", "is_critical": True},
    {"id": "r3", "text": "Cláusula de arbitragem internacional", "is_critical": False},
]


def main() -> None:
    print("Analisando contrato fake com OpenAI...")
    result = check_requirements(FAKE_CONTRACT, REQUIREMENTS, "test-contract")
    print(f"Score: {result.overall_score:.0%} ({result.requirements_met}/{result.total_requirements})")
    for c in result.checks:
        icon = "OK" if c.present else "FALTA"
        print(f"  [{icon}] {c.requirement_text}: {c.observation[:80]}")
    if result.critical_missing:
        print("Críticos em falta:", result.critical_missing)


if __name__ == "__main__":
    main()
