-- BGE-M3 sparse lexical weights（与 dense 同表，避免 join）
ALTER TABLE case_embeddings
    ADD COLUMN IF NOT EXISTS sparse_weights JSONB,
    ADD COLUMN IF NOT EXISTS sparse_model VARCHAR(100);

COMMENT ON COLUMN case_embeddings.sparse_weights IS
    'BGE-M3 lexical_weights: {"token": weight, ...}';
COMMENT ON COLUMN case_embeddings.sparse_model IS
    '稀疏表征模型名，通常与 embedding_model 同为 bge-m3';
