-- 将发号水位同步到现有数据 MAX，修复金标导入后 seq=0 导致撞 C000503 等问题
UPDATE id_sequences AS s
SET value = GREATEST(
    s.value,
    COALESCE((
        SELECT MAX(CAST(SUBSTRING(d.file_id FROM 2) AS BIGINT))
        FROM documents d
        WHERE d.file_id ~ '^F[0-9]+$'
    ), 0)
)
WHERE s.name = 'file_id';

UPDATE id_sequences AS s
SET value = GREATEST(
    s.value,
    COALESCE((
        SELECT MAX(CAST(SUBSTRING(c.case_id FROM 2) AS BIGINT))
        FROM penalty_cases c
        WHERE c.case_id ~ '^C[0-9]+$'
    ), 0)
)
WHERE s.name = 'case_id';
