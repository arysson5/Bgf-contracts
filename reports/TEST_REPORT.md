# Relatório de testes automatizados — BGF Contract Analyzer

**Data:** 2026-07-06  
**Resultado:** **61 passed**, 0 failed, 0 skipped  
**Duração:** ~29s  
**Relatório HTML:** [pytest_report_latest.html](pytest_report_latest.html)

---

## Auditoria de imports e dependências

| Verificação | Resultado |
|-------------|-----------|
| 40 módulos `app.core`, `app.db`, `app.utils`, `app.api` | ✅ Importam sem erro |
| Dependências críticas (streamlit, diff-match-patch, bcrypt, pymupdf, langchain-google-genai, etc.) | ✅ Presentes |
| Páginas Streamlit (`app.main`, `app.pages.*`) | Excluídas do scan (exigem runtime Streamlit) |

**Bibliotecas em `requirements.txt`:** todas instaladas no `.venv`. Nenhuma dependência faltando para os serviços testados.

---

## Suites de teste

### 1. `test_text_diff` — diff determinístico (sem IA)

| Teste | O que valida |
|-------|----------------|
| Textos idênticos | 0 hunks alterados, similaridade 100% |
| Textos sintéticos com mudanças | ≥2 hunks, marcações HTML verde/vermelho |
| Performance sintética | < 2s em texto repetido |
| **BGF.pdf × BGF_revisao.pdf** | Texto extraído **idêntico** → **zero falsos positivos** |
| Par `_temp` comentários × devolutiva | Diferenças reais detectadas em < 3s |
| Modo `TEXT_DIFF` | Sem alterações materiais quando textos iguais |

### 2. `test_extractor_comments` — extração em PDFs reais

| Contrato | Resultado |
|----------|-----------|
| `...BGF.pdf` | ~56k chars, **89 comentários** em < 5s |
| `...BGF_revisao.pdf` | **91 comentários** |
| Par sem anotações | 0 comentários |
| `_temp/a_*_comentarios.pdf` | 9 comentários |
| IDs estáveis (`stable_id`) | Determinísticos (inclui data do PDF) |

### 3. `test_reviewer_offline` — comentários sem Gemini

| Teste | Resultado |
|-------|-----------|
| Trecho inalterado | `NOT_ATTENDED` via regra local |
| 15 comentários BGF + `skip_llm=True` | 15 revisões em paralelo, sem API |
| Lista vazia | Retorno zerado |

### 4. `test_auth_database` — login e isolamento

| Teste | Resultado |
|-------|-----------|
| bcrypt hash/verify | OK |
| `owner_user_id` filtra contratos | OK |
| `CommentRecord` persistido | OK |
| `delete_analysis_result` | OK |

### 5. `test_imports_core` — 41 testes de import

Todos os módulos de serviço importam corretamente.

---

## Conclusões principais

1. **Falsos positivos no diff:** O par BGF (texto extraído idêntico entre base e revisão) produz **0 alterações** — o motor não inventa diferenças quando o texto é o mesmo.
2. **Diferenças reais:** O par `_temp` (comentários × devolutiva revisada) detecta **15 hunks** alterados em **5ms**.
3. **Comentários:** Extração completa dos **89 comentários** do PDF BGF com IDs estáveis para vínculo entre análises.
4. **Velocidade:** Diff em ~56k caracteres < 8s; extração de comentários < 5s.

---

## Como executar novamente

```powershell
cd c:\Users\arysson.silva\Documents\projetos\Bgf-contracts
.\scripts\run_tests.ps1
```

Ou diretamente:

```powershell
$env:PYTHONPATH = (Get-Location).Path
.venv\Scripts\python.exe -m pytest tests -v --html=reports/pytest_report_latest.html --self-contained-html
```

---

## Cobertura (app.core + app.db)

~43% dos statements — foco nos módulos de diff, extração e revisão offline. Módulos de UI Streamlit e LLM ao vivo não são exercitados nos testes automatizados (sem chamadas à API Gemini).
