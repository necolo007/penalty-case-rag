"""RiskTagger 与评测共用中文 LLM 打标。"""

from engine.classification.risk_tagger import predict_cn_tags_with_llm


class _FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload
        self.last_prompt = ""
        self.last_system = ""

    def complete(self, prompt, *, system=None, **kwargs):
        self.last_prompt = prompt
        self.last_system = system or ""
        return self.payload


def test_predict_cn_tags_with_llm_uses_cn_prompt_and_refine():
    llm = _FakeLLM('{"risk_tags": ["虚假宣传", "赠送利益"]}')
    tags = predict_cn_tags_with_llm(llm, "宣传单页夸大责任，并赠送油卡。")
    assert "虚假宣传" in tags
    assert "赠送利益" in tags
    assert "合同外利益" in tags
    assert "欺骗投保人" in llm.last_system or "风险标签" in llm.last_system
    assert "赠送" in llm.last_prompt or "油卡" in llm.last_prompt
