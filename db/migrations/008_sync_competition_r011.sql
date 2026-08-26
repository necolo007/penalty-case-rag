-- 对齐赛题粗类 R001–R011（名称与配套 risk_type_dictionary.csv 一致）
-- 幂等：已存在则更新名称；缺失则插入

INSERT INTO risk_type_dict (risk_type_id, competition_id, parent_id, level, risk_type_name, display_tags, keywords, is_active)
VALUES
('R001', 'R001', NULL, 1, '销售误导', '{"销售误导"}', '{"欺骗投保人","销售误导","夸大收益","承诺收益","保证收益"}', TRUE),
('R002', 'R002', NULL, 1, '合同外利益', '{"合同外利益"}', '{"合同外利益","赠送利益","回扣返佣"}', TRUE),
('R003', 'R003', NULL, 1, '宣传材料不真实', '{"宣传不实"}', '{"虚假宣传","产品说明会违规","绝对化表述","虚构收益率","避债避税"}', TRUE),
('R004', 'R004', NULL, 1, '销售人员职业登记管理不规范', '{"执业登记"}', '{"代理人管理不到位","委托无资质机构销售"}', TRUE),
('R005', 'R005', NULL, 1, '虚挂中介费用套取资金', '{"虚挂中介"}', '{"虚列费用套取资金","虚构中介业务"}', TRUE),
('R006', 'R006', NULL, 1, '编制虚假财务资料', '{"虚假财务"}', '{"编制虚假财务资料","虚假报表","业务财务数据不真实"}', TRUE),
('R007', 'R007', NULL, 1, '售后服务违规', '{"售后违规"}', '{"回访违规"}', TRUE),
('R008', 'R008', NULL, 1, '客户信息与隐私违规', '{"客户信息"}', '{"客户信息不真实"}', TRUE),
('R009', 'R009', NULL, 1, '产品费率及合同执行违规', '{"费率条款"}', '{"未按规定使用费率条款"}', TRUE),
('R010', 'R010', NULL, 1, '内部管理与培训违规', '{"培训违规"}', '{"培训材料违规"}', TRUE),
('R011', 'R011', NULL, 1, '其他类型违规行为', '{"其他"}', '{"其他"}', TRUE)
ON CONFLICT (risk_type_id) DO UPDATE SET
  competition_id = EXCLUDED.competition_id,
  parent_id = EXCLUDED.parent_id,
  level = EXCLUDED.level,
  risk_type_name = EXCLUDED.risk_type_name,
  display_tags = EXCLUDED.display_tags,
  keywords = EXCLUDED.keywords,
  is_active = TRUE;
