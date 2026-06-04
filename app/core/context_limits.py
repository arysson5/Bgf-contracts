"""Limites de contexto enviados à IA (proposta, contrato, trechos, chunking)."""

# Texto completo no prompt (caracteres)
PROPOSAL_CTX_CHARS = 80_000
CONTRACT_CTX_CHARS = 80_000

# Trechos citados em cada item de análise
MAX_EXCERPT_CHARS = 1200

# Chunking quando o documento é muito grande (tokens)
CHUNK_TOKEN_LIMIT = 12_000
CHUNK_SIZE_CHARS = 8000
CHUNK_OVERLAP_CHARS = 400
