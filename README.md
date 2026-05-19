# Contract Analyzer

Sistema desktop (Streamlit) para análise e comparação de contratos em PDF e DOCX, com IA via **Google Gemini**.

## Funcionalidades

1. **Checklist automático** — verifica requisitos mínimos no contrato
2. **Comparação de versões** — análise contratual criteriosa entre original e versão do cliente
3. **Revisão de comentários** — verifica se comentários do admin foram atendidos, com sugestão de resposta
4. **Histórico** — consulta análises anteriores por contrato

## Requisitos

- **Python 3.11 ou 3.12 estável** (evite builds alpha)
- Windows, macOS ou Linux
- Chave da API Google (Gemini): [Google AI Studio](https://aistudio.google.com/apikey)

## Instalação

```bash
git clone https://github.com/SEU_USUARIO/contract-analyser.git
cd contract-analyser

py -3.12 -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

python -m pip install --upgrade pip
pip install -r requirements.txt

copy .env.example .env          # Windows
# cp .env.example .env          # Linux/Mac
```

Edite `.env` (nunca commite este arquivo):

```env
GOOGLE_API_KEY=sua_chave_aqui
MODEL_NAME=gemini-2.5-flash
MAX_TOKENS=8192
CONTRACTS_DIR=./contracts
DB_PATH=./contract_analyzer.db
```

## Executar

**Windows:** `run.bat` ou:

```bash
streamlit run app/main.py
```

Acesse: http://127.0.0.1:8501 (somente nesta máquina, por padrão).

## Publicar no GitHub — checklist

Antes do primeiro `git push`, confirme:

- [ ] `.env` **não** está no commit (`git status` não deve listá-lo)
- [ ] `contract_analyzer.db` e arquivos em `contracts/` estão ignorados
- [ ] A chave da API foi **revogada e recriada** se já tiver sido exposta em algum commit
- [ ] Leia [SECURITY.md](SECURITY.md)

```bash
git init
git add .
git status   # revise a lista — sem .env, sem .db, sem PDFs de clientes
git commit -m "Initial commit: Contract Analyzer"
git remote add origin https://github.com/SEU_USUARIO/contract-analyser.git
git push -u origin main
```

## Segurança

- Servidor local em `127.0.0.1` — não expõe a rede automaticamente
- Uploads: apenas PDF/DOCX, nomes sanitizados, sem path traversal
- Dados de contratos permanecem locais; texto é enviado à API Gemini para análise

Detalhes: [SECURITY.md](SECURITY.md)

## Testes

```bash
python test_schemas.py
python test_differ.py
python test_extractor.py contrato.pdf
python test_checker.py      # requer GOOGLE_API_KEY
```

## Estrutura

```
app/
  main.py              # Home
  pages/               # Streamlit multipage
  core/                # IA, extrator, comparador
  models/schemas.py
  db/                  # SQLite
  utils/               # tema, cache, segurança
contracts/             # uploads (gitignored)
.streamlit/config.toml
```

## Stack

Python 3.11+ · Streamlit · LangChain · Google Gemini · SQLite · SQLModel
