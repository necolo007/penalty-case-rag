-- 保险监管处罚案例知识库 初始化 Schema
-- 依赖扩展：uuid-ossp / vector(pgvector)
-- zhparser 全文配置由 db/automigrate.py 按环境自动创建（有 zhparser 用中文分词，否则降级 simple）

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";


-- 1. 原始文档表
CREATE TABLE IF NOT EXISTS documents (
    file_id         VARCHAR(50) PRIMARY KEY,
    file_name       VARCHAR(500) NOT NULL,
    source_url      TEXT,
    source_type     VARCHAR(20) NOT NULL,          -- PDF, WORD, HTML, TXT(OCR)
    source_page     INTEGER,
    publish_date    DATE,
    regulator       VARCHAR(200),
    raw_text        TEXT,                          -- 解析后全文（冗余，便于查询）
    raw_text_path   TEXT,                          -- 赛题要求：raw_text/F000001.txt
    raw_tables      JSONB DEFAULT '[]',
    parse_status    VARCHAR(30) DEFAULT 'pending', -- pending, parsing, done, failed
    parse_error     TEXT,
    parse_metadata  JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(parse_status);
CREATE INDEX IF NOT EXISTS idx_documents_regulator ON documents(regulator);
CREATE INDEX IF NOT EXISTS idx_documents_publish_date ON documents(publish_date);


-- 2. 处罚案例表
CREATE TABLE IF NOT EXISTS penalty_cases (
    case_id             VARCHAR(50) PRIMARY KEY,
    file_id             VARCHAR(50) NOT NULL REFERENCES documents(file_id),

    -- 核心字段
    party_name          TEXT NOT NULL,
    institution_type    VARCHAR(50),
    penalty_doc_no      VARCHAR(100),
    violation_behavior  TEXT NOT NULL,
    penalty_content     TEXT NOT NULL,
    fine_amount         VARCHAR(100),
    regulator           VARCHAR(200),
    publish_date        DATE,
    legal_basis         TEXT,

    -- 分类字段（内外双轨）
    is_insurance_related BOOLEAN DEFAULT FALSE,
    is_insurance_candidate BOOLEAN DEFAULT FALSE,
    candidate_reasons   TEXT[] DEFAULT '{}',
    risk_tags           TEXT[] DEFAULT '{}',        -- 展示标签：["合同外利益","销售违规"]
    risk_type_ids       TEXT[] DEFAULT '{}',        -- 赛题扁平 ID：["R002"]
    risk_category       VARCHAR(50),
    case_summary        TEXT,

    -- 全文搜索
    search_vector       TSVECTOR,

    -- 质量标记
    overall_confidence  FLOAT DEFAULT 0.0,
    field_confidences   JSONB DEFAULT '{}',
    extraction_method   VARCHAR(20) DEFAULT 'regex',

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cases_regulator ON penalty_cases(regulator);
CREATE INDEX IF NOT EXISTS idx_cases_insurance ON penalty_cases(is_insurance_related);
CREATE INDEX IF NOT EXISTS idx_cases_risk_tags ON penalty_cases USING GIN(risk_tags);
CREATE INDEX IF NOT EXISTS idx_cases_risk_type_ids ON penalty_cases USING GIN(risk_type_ids);
CREATE INDEX IF NOT EXISTS idx_cases_publish_date ON penalty_cases(publish_date);
CREATE INDEX IF NOT EXISTS idx_cases_institution ON penalty_cases(institution_type);

-- 全文搜索向量：触发器自动维护
CREATE OR REPLACE FUNCTION cases_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        to_tsvector('zhparser_config',
            coalesce(NEW.violation_behavior, '') || ' ' ||
            coalesce(NEW.penalty_content, '') || ' ' ||
            coalesce(NEW.party_name, ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cases_search_vector ON penalty_cases;
CREATE TRIGGER trg_cases_search_vector
    BEFORE INSERT OR UPDATE OF violation_behavior, penalty_content, party_name
    ON penalty_cases
    FOR EACH ROW EXECUTE FUNCTION cases_search_vector_update();

CREATE INDEX IF NOT EXISTS idx_cases_search ON penalty_cases USING GIN(search_vector);


-- 3. 向量表（1:1 与案例关联）
CREATE TABLE IF NOT EXISTS case_embeddings (
    case_id         VARCHAR(50) PRIMARY KEY REFERENCES penalty_cases(case_id) ON DELETE CASCADE,
    embedding       VECTOR(1024) NOT NULL,
    embedding_model VARCHAR(100) DEFAULT 'qwen-text-embedding-v4',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw ON case_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);


-- 4. 三级风险标签字典（含赛题扁平 ID 映射）
CREATE TABLE IF NOT EXISTS risk_type_dict (
    risk_type_id        VARCHAR(20) PRIMARY KEY,    -- R001, R001-01, R002-01-01
    competition_id      VARCHAR(10),                -- 赛题扁平 ID：R001–R008
    parent_id           VARCHAR(20) REFERENCES risk_type_dict(risk_type_id),
    level               SMALLINT NOT NULL DEFAULT 1,
    risk_type_name      VARCHAR(100) NOT NULL,
    display_tags        TEXT[] DEFAULT '{}',
    description         TEXT,
    keywords            TEXT[] DEFAULT '{}',
    synonym_ids         TEXT[] DEFAULT '{}',
    example_fields      TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);


-- 5. 主体关联表（任务2 交付物）
CREATE TABLE IF NOT EXISTS subject_relations (
    relation_id         SERIAL PRIMARY KEY,
    case_id             VARCHAR(50) NOT NULL REFERENCES penalty_cases(case_id) ON DELETE CASCADE,
    raw_party_name      TEXT NOT NULL,
    normalized_name     TEXT,
    entity_type         VARCHAR(50) NOT NULL,       -- 保险公司/分支机构/代理中介/责任人员/第三方
    parent_entity_id    INTEGER REFERENCES subject_relations(relation_id),
    confidence          FLOAT DEFAULT 0.0,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subject_relations_case ON subject_relations(case_id);


-- 6. 同义词词典（规则召回 + 查询扩展）
CREATE TABLE IF NOT EXISTS synonym_dictionary (
    synonym_id      SERIAL PRIMARY KEY,
    business_term   VARCHAR(200) NOT NULL,          -- 业务口语：「送体检卡」
    standard_term   VARCHAR(200) NOT NULL,          -- 法言法语：「给予合同外利益」
    risk_type_id    VARCHAR(20) REFERENCES risk_type_dict(risk_type_id),
    weight          FLOAT DEFAULT 1.0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_synonym_business ON synonym_dictionary(business_term);
CREATE INDEX IF NOT EXISTS idx_synonym_standard ON synonym_dictionary(standard_term);


-- 7. 规则词典（高危词 → 风险类型映射）
CREATE TABLE IF NOT EXISTS rule_dictionary (
    rule_id         SERIAL PRIMARY KEY,
    pattern         VARCHAR(500) NOT NULL,          -- 正则或关键词
    risk_type_id    VARCHAR(20) REFERENCES risk_type_dict(risk_type_id),
    severity        VARCHAR(10) DEFAULT 'medium',   -- high / medium / low
    description     TEXT,
    is_active       BOOLEAN DEFAULT TRUE
);


-- 8. 审查日志表
CREATE TABLE IF NOT EXISTS review_logs (
    review_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_text      TEXT NOT NULL,
    rewritten_query TEXT,
    risk_types      TEXT[],
    suggestion      TEXT,
    raw_response    JSONB,
    reviewer        VARCHAR(100),
    feedback        VARCHAR(20),                    -- agree / disagree / partial
    feedback_note   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_logs_created ON review_logs(created_at DESC);


-- 9. 审查-案例关联表
CREATE TABLE IF NOT EXISTS review_case_refs (
    review_id   UUID NOT NULL REFERENCES review_logs(review_id) ON DELETE CASCADE,
    case_id     VARCHAR(50) NOT NULL REFERENCES penalty_cases(case_id),
    rank        INTEGER,
    relevance   VARCHAR(20),                        -- strong / medium / weak
    reason      TEXT,
    PRIMARY KEY (review_id, case_id)
);


-- 10. 材料审查表（任务4）
CREATE TABLE IF NOT EXISTS material_reviews (
    material_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type     VARCHAR(20) NOT NULL,           -- paste / upload
    file_name       VARCHAR(500),
    scene           VARCHAR(100),
    raw_text        TEXT NOT NULL,
    review_status   VARCHAR(20) DEFAULT 'pending',  -- pending / reviewing / done / failed
    total_sentences INTEGER,
    risk_sentences  INTEGER,
    overall_risk    VARCHAR(20),                    -- high / medium / low / none
    suggestion      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);


-- 11. 风险句明细表
CREATE TABLE IF NOT EXISTS risk_sentences (
    sentence_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    material_id     UUID NOT NULL REFERENCES material_reviews(material_id) ON DELETE CASCADE,
    sentence_text   TEXT NOT NULL,
    position_start  INTEGER,
    position_end    INTEGER,
    paragraph_idx   INTEGER,
    page_num        INTEGER,
    risk_type_ids   TEXT[],
    severity        VARCHAR(10),                    -- high / medium / low
    detection_method VARCHAR(20),                   -- rule / classifier / llm
    review_id       UUID REFERENCES review_logs(review_id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_sentences_material ON risk_sentences(material_id);
