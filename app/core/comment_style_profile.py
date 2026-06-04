"""
Perfil de estilo de comentários em PDF — baseado nos arquivos em «arquivos fonte/»
e na documentação do sistema de análise BGF.
"""

from __future__ import annotations

from pathlib import Path

# Aberturas recorrentes nos PDFs de referência (revisão jurídica BGF)
OPENING_PHRASES = (
    "Por favor, incluir a seguinte cláusula, conforme solicitação do jurídico:",
    "Por favor, incluir os seguintes itens nesta cláusula:",
    "Por favor, adequar o trecho abaixo para alinhar à proposta técnica e comercial:",
    "Solicitamos revisar o dispositivo abaixo em razão da divergência identificada na análise:",
)

# Categorias alinhadas ao «sistema de analise.md»
COMMENT_CATEGORIES = (
    "Escopo / Objeto",
    "Cronograma e Prazos",
    "Entregáveis e Resultados",
    "Documentação",
    "Itens incluídos vs excluídos",
    "Valor do serviço",
    "Forma e prazo de pagamento",
    "Condições operacionais e jurídicas",
    "Tributos e reajustes",
    "Riscos de divergência",
)

# Amostras literais extraídas de PDFs com comentários (arquivos fonte)
REFERENCE_SAMPLES: list[str] = [
 (
        "Por favor, incluir a seguinte cláusula, conforme solicitação do jurídico:\n\n"
        "3.2. Adicionalmente, serão reembolsadas despesas estimadas [...] "
        "mediante emissão de Notas de Débito (ND) [...]"
    ),
    (
        "Por favor, incluir os seguintes itens nesta cláusula:\n\n"
        "5.2. O pagamento dos serviços será realizado em 100% (cem por cento) "
        "do valor correspondente a cada fase, estando condicionado à entrega do e-mail resumo "
        "[...] Nota Fiscal [...] prazo de até 10 (dez) dias."
    ),
    (
        "Por favor, incluir a seguinte cláusula, conforme solicitação do jurídico:\n\n"
        "6.3. POR ATRASO NO PAGAMENTO: [...] multa moratória de 2% [...] "
        "juros de mora de 1% ao mês e atualização monetária [...] IPCA/IBGE."
    ),
    "Por favor, incluir a numeração nesta página.",
]

_STYLE_RULES = """
Regras de redação (replicar o padrão BGF dos PDFs de referência):
- Abrir com «Por favor, incluir...» ou «Solicitamos...», tom profissional e direto.
- Indicar cláusula ou seção alvo quando possível (ex.: «nesta cláusula», «item 5.2»).
- Se houver texto sugerido, colocá-lo após linha em branco, numerado como no contrato.
- Mencionar alinhamento à proposta, jurídico ou risco operacional/financeiro quando couber.
- Português brasileiro; sem saudações; 2–6 frases ou um parágrafo com itens numerados.
- Não inventar valores ou cláusulas inteiras sem base na análise fornecida.
"""


def style_guide_for_llm() -> str:
    samples = "\n\n---\n\n".join(f"Exemplo {i + 1}:\n{s}" for i, s in enumerate(REFERENCE_SAMPLES))
    cats = ", ".join(COMMENT_CATEGORIES)
    openings = "\n".join(f"- {p}" for p in OPENING_PHRASES)
    return (
        f"{_STYLE_RULES}\n\n"
        f"Categorias típicas da análise: {cats}.\n\n"
        f"Aberturas preferidas:\n{openings}\n\n"
        f"Exemplos reais de comentários em PDF:\n{samples}"
    )


def opening_for_category(categoria: str) -> str:
    c = (categoria or "").lower()
    if "pagamento" in c or "valor" in c or "tribut" in c:
        return OPENING_PHRASES[1]
    if "escopo" in c or "entreg" in c or "document" in c:
        return OPENING_PHRASES[2]
    return OPENING_PHRASES[0]


def fallback_matrix_comment(
    categoria: str,
    parametro: str,
    observation: str,
    *,
    page_hint: str | None = None,
) -> str:
    ref = f" ({page_hint})" if page_hint else ""
    opening = opening_for_category(categoria)
    return (
        f"{opening}\n\n"
        f"[{categoria}{ref}] Adequar o contrato ao parâmetro verificado na análise: "
        f"{parametro[:300]}. {observation[:400]}"
    ).strip()


def load_reference_pdf_comments(source_dir: str | Path | None = None) -> list[dict]:
    """Carrega comentários dos PDFs em «arquivos fonte» para enriquecer sugestões."""
    from app.core.extractor import extract_comments_from_pdf

    if source_dir is None:
        source_dir = Path(__file__).resolve().parents[2].parent / "arquivos fonte"
    root = Path(source_dir)
    if not root.is_dir():
        return []

    out: list[dict] = []
    for pdf in sorted(root.glob("*.pdf")):
        try:
            out.extend(extract_comments_from_pdf(str(pdf)))
        except Exception:
            continue
    return out
