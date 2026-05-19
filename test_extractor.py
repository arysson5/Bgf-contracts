"""Testa extração de PDF e DOCX — passe caminhos como argumentos."""

import sys
from pathlib import Path

from app.core.extractor import extract_comments_from_pdf, extract_text


def main() -> None:
    if len(sys.argv) < 3:
        print("Uso: python test_extractor.py <arquivo.pdf> <arquivo.docx>")
        print("Criando arquivos de teste mínimos se não informados...")
        _run_with_generated()
        return

    pdf_path, docx_path = sys.argv[1], sys.argv[2]
    for path in (pdf_path, docx_path):
        text, dtype = extract_text(path)
        print(f"\n=== {path} ({dtype.value}) ===")
        print(text[:500])
        print(f"... total {len(text)} caracteres")

    if pdf_path.endswith(".pdf"):
        comments = extract_comments_from_pdf(pdf_path)
        print(f"\nComentários extraídos: {len(comments)}")
        for c in comments[:3]:
            print(c)


def _run_with_generated() -> None:
    """Gera DOCX mínimo via python-docx se disponível."""
    try:
        from docx import Document

        docx_path = Path("contracts/_test_sample.docx")
        docx_path.parent.mkdir(exist_ok=True)
        doc = Document()
        doc.add_paragraph("CONTRATO DE TESTE. Cláusula 1: Objeto. Cláusula 2: Prazo de 12 meses.")
        doc.save(docx_path)
        text, dtype = extract_text(str(docx_path))
        print(f"DOCX OK ({dtype.value}): {text[:200]}")
    except ImportError:
        print("python-docx não instalado — pule teste DOCX ou instale dependências.")
    print("\nPara PDF, forneça um arquivo real: python test_extractor.py contrato.pdf contrato.docx")


if __name__ == "__main__":
    main()
