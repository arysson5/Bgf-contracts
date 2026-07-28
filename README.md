# Contract Analyzer

Sistema desktop (Streamlit) para análise e comparação de contratos em PDF e DOCX, com IA via **OpenAI**.

## Funcionalidades

1. **Checklist automático** — verifica requisitos mínimos no contrato
2. **Comparação de versões** — análise contratual criteriosa entre original e versão do cliente
3. **Revisão de comentários** — verifica se comentários do admin foram atendidos, com sugestão de resposta
4. **Histórico** — consulta análises anteriores por contrato

## Requisitos

- **Python 3.11 ou 3.12 estável** (evite builds alpha)
- Windows, macOS ou Linux
- Chave da API OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

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
OPENAI_API_KEY=sua_chave_aqui
MODEL_NAME=gpt-4o-mini
MODEL_NAME_PRO=gpt-4o
MAX_TOKENS=16384
CONTRACTS_DIR=./contracts
DB_PATH=./contract_analyzer.db
```

## Executar

**Windows:** `run.bat` ou:

```bash
streamlit run app/main.py
```

Acesse: http://127.0.0.1:8501 (somente nesta máquina, por padrão).

## Docker (servidor / produção)

Encapsula app, Python e dependências em um container Linux. Banco e contratos ficam em **volume persistente**.

### Pré-requisitos

- [Docker Engine](https://docs.docker.com/engine/install/) ou Docker Desktop (Windows)
- Arquivo `.env` com `OPENAI_API_KEY`

### Subir em 3 passos

```bash
copy .env.docker.example .env    # Windows
# cp .env.docker.example .env      # Linux

# Edite .env e coloque sua OPENAI_API_KEY

docker compose up -d --build
```

Acesse: **http://localhost:8501** (ou a porta definida em `APP_PORT` no `.env`).

**Windows (atalho):**

```powershell
.\scripts\docker-up.ps1
```

**Linux/macOS:**

```bash
chmod +x scripts/docker-up.sh
./scripts/docker-up.sh
```

### Dados persistentes

Por padrão o Docker cria o volume nomeado `bgf-contract-analyzer-data` (banco + PDFs).

Para gravar em pasta local `./data` (backup mais fácil no servidor):

```bash
docker compose -f docker-compose.yml -f docker-compose.bind-mount.yml up -d --build
```

### Comandos úteis

```bash
docker compose logs -f          # acompanhar logs
docker compose down             # parar
docker compose up -d --build    # atualizar após git pull
```

### Publicar na rede (VPN / IIS)

O container escuta em `0.0.0.0:8501`. No servidor, use proxy reverso (IIS/nginx) com HTTPS na frente da porta mapeada — não exponha diretamente na internet sem autenticação.

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
- Dados de contratos permanecem locais; texto é enviado à API OpenAI para análise

Detalhes: [SECURITY.md](SECURITY.md)

## Testes

```bash
python test_schemas.py
python test_differ.py
python test_extractor.py contrato.pdf
python test_checker.py      # requer OPENAI_API_KEY
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

Python 3.11+ · Streamlit · LangChain · OpenAI · SQLite · SQLModel
