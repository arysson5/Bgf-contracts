# Política de segurança — Contract Analyzer

## Escopo

Aplicação **local/desktop** (Streamlit) para análise de contratos. Não é um SaaS multiusuário; o modelo de ameaça assume uso em máquina ou rede interna confiável.

## Dados sensíveis

- Contratos (PDF/DOCX) ficam em `contracts/` no disco.
- Resultados de análise ficam em `contract_analyzer.db` (SQLite).
- A chave `OPENAI_API_KEY` fica **somente** no arquivo `.env` (nunca commitar).

## O que NÃO enviar ao GitHub

| Item | Motivo |
|------|--------|
| `.env` | Contém chave da API |
| `*.db` | Dados de contratos e análises |
| `contracts/*` (exceto `.gitkeep`) | Arquivos de clientes |
| `.streamlit/secrets.toml` | Segredos do Streamlit Cloud |

## Configuração recomendada

1. Copie `.env.example` → `.env` e preencha a chave localmente.
2. Execute com `run.bat` ou `streamlit run` — o servidor fica em **127.0.0.1** por padrão (apenas esta máquina).
3. Não exponha a porta 8501 na internet sem autenticação e HTTPS.

## Medidas implementadas no código

- **Uploads:** nomes sanitizados, sem path traversal; apenas `.pdf` e `.docx`.
- **Caminhos:** resolução de arquivos restrita ao diretório `contracts/`.
- **Servidor:** `address = 127.0.0.1` em `.streamlit/config.toml`.
- **API:** chave lida via variável de ambiente; não hardcoded no repositório.

## Riscos conhecidos (aceitos no uso local)

- Sem autenticação de usuário — quem acessar o Streamlit vê todos os contratos do banco local.
- Texto do contrato é enviado à API OpenAI para análise — revise os [termos da OpenAI](https://openai.com/policies/terms-of-use/).
- Dados em repouso não são criptografados no SQLite.

## Reportar vulnerabilidades

Abra uma issue privada ou entre em contato com o mantenedor do repositório. Não publique chaves de API ou trechos de contratos reais em issues públicas.
