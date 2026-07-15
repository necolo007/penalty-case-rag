-- 文档内容去重与稳健发号
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_sha256 VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_content_sha256
    ON documents (content_sha256) WHERE content_sha256 IS NOT NULL;

-- 序列化发号，避免 COUNT(*)+1 并发撞号（与官方 C001 / F000289 混用时从高水位续号）
CREATE TABLE IF NOT EXISTS id_sequences (
    name    VARCHAR(50) PRIMARY KEY,
    value   BIGINT NOT NULL DEFAULT 0
);

INSERT INTO id_sequences (name, value) VALUES ('file_id', 0), ('case_id', 0)
ON CONFLICT (name) DO NOTHING;
