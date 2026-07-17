-- 营销话术同义词/规则扩充 + 全文检索向量纳入标签与摘要

INSERT INTO synonym_dictionary (business_term, standard_term, risk_type_id, weight)
SELECT v.business_term, v.standard_term, v.risk_type_id, v.weight
FROM (VALUES
    ('打折', '给予投保人保险合同约定以外的其他利益', 'R002', 0.85),
    ('折扣', '给予投保人保险合同约定以外的其他利益', 'R002', 0.85),
    ('优惠', '给予投保人保险合同约定以外的其他利益', 'R002', 0.7),
    ('预交', '给予投保人保险合同约定以外的其他利益', 'R002', 0.75),
    ('预缴', '给予投保人保险合同约定以外的其他利益', 'R002', 0.75),
    ('首年保费', '给予投保人保险合同约定以外的其他利益', 'R002', 0.7),
    ('保费优惠', '给予投保人保险合同约定以外的其他利益', 'R002', 0.9),
    ('利息翻倍', '欺骗投保人 夸大收益', 'R001', 0.95),
    ('翻好几倍', '欺骗投保人 夸大收益', 'R001', 0.95),
    ('储蓄计划', '欺骗投保人 销售误导', 'R001', 0.9),
    ('活期转', '欺骗投保人 销售误导', 'R001', 0.85),
    ('存钱', '欺骗投保人 销售误导', 'R001', 0.8),
    ('像存款', '欺骗投保人 销售误导', 'R001', 0.85),
    ('和银行存款', '欺骗投保人 不当比较', 'R001', 0.9),
    ('比银行更安全', '欺骗投保人 弱化风险提示', 'R001', 0.95),
    ('完全无风险', '欺骗投保人 弱化风险提示', 'R001', 1.0),
    ('不用担心', '欺骗投保人 弱化风险提示', 'R001', 0.85),
    ('一定会赔', '欺骗投保人 弱化风险提示', 'R001', 0.95),
    ('免责不重要', '欺骗投保人 弱化风险提示', 'R001', 0.9),
    ('保本', '欺骗投保人 承诺收益', 'R001', 0.9),
    ('保息', '欺骗投保人 承诺收益', 'R001', 0.9),
    ('稳赚不赔', '欺骗投保人 夸大收益', 'R001', 1.0),
    ('固定收益', '欺骗投保人 承诺收益', 'R001', 0.9),
    ('年化', '欺骗投保人 夸大收益', 'R001', 0.7),
    ('撬动杠杆', '欺骗投保人 夸大收益', 'R001', 0.8),
    ('赚钱概率', '欺骗投保人 夸大收益', 'R001', 0.75),
    ('体检卡', '给予投保人保险合同约定以外的其他利益', 'R002', 0.9),
    ('加油卡', '给予投保人保险合同约定以外的其他利益', 'R002', 0.9),
    ('赠送礼品', '给予投保人保险合同约定以外的其他利益', 'R002', 0.9),
    ('免费领', '给予投保人保险合同约定以外的其他利益', 'R002', 0.85),
    ('避债', '欺骗投保人 不当宣传', 'R001', 0.85),
    ('避税', '欺骗投保人 不当宣传', 'R001', 0.85),
    ('回访', '未按规定回访', 'R001', 0.7),
    ('产说会', '宣传材料数据资料不真实', 'R003', 0.85)
) AS v(business_term, standard_term, risk_type_id, weight)
WHERE NOT EXISTS (
    SELECT 1 FROM synonym_dictionary s WHERE s.business_term = v.business_term
);

INSERT INTO rule_dictionary (pattern, risk_type_id, severity, description)
SELECT v.pattern, v.risk_type_id, v.severity, v.description
FROM (VALUES
    ('打折|折扣|保费优惠|预交.*保费|预缴.*保费|首年.*折', 'R002', 'high', '费用折扣/预缴优惠'),
    ('储蓄计划|活期|利息.*倍|像.*存款|把.*保费.*说成.*存', 'R001', 'high', '保险包装为存款/储蓄'),
    ('保本|保息|保本保息|固定收益|稳赚不赔', 'R001', 'high', '承诺/保证收益'),
    ('完全无风险|比银行更安全|不用担心|一定会赔|免责.*不重要', 'R001', 'high', '弱化风险提示'),
    ('年化|最高收益|翻.*倍|撬动杠杆', 'R001', 'medium', '夸大收益'),
    ('赠送|领取.*礼|体检卡|加油卡|洗车券|代金券|油卡', 'R002', 'high', '礼品卡券诱导'),
    ('避债|避税|规避债务', 'R001', 'medium', '避债避税宣传')
) AS v(pattern, risk_type_id, severity, description)
WHERE NOT EXISTS (
    SELECT 1 FROM rule_dictionary r WHERE r.pattern = v.pattern
);

-- 全文向量：纳入风险标签与摘要，提升营销口语→法言法语的 BM25 命中
CREATE OR REPLACE FUNCTION cases_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        to_tsvector('zhparser_config',
            coalesce(NEW.violation_behavior, '') || ' ' ||
            coalesce(NEW.penalty_content, '') || ' ' ||
            coalesce(NEW.party_name, '') || ' ' ||
            coalesce(NEW.case_summary, '') || ' ' ||
            coalesce(array_to_string(NEW.risk_tags, ' '), ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cases_search_vector ON penalty_cases;
CREATE TRIGGER trg_cases_search_vector
    BEFORE INSERT OR UPDATE OF violation_behavior, penalty_content, party_name, case_summary, risk_tags
    ON penalty_cases
    FOR EACH ROW EXECUTE FUNCTION cases_search_vector_update();

-- 刷新已有案例的 search_vector（须触碰触发器监听列）
UPDATE penalty_cases SET violation_behavior = violation_behavior;
