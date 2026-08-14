"""HyDE / 改写器单测（不依赖外网）。"""

import pytest

from engine.retrieval.query_rewriter import QueryRewriter


class _FakeLLM:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        self.last_prompt = ""

    def complete(self, prompt, **kwargs):
        self.calls += 1
        self.last_prompt = prompt
        return self.text


@pytest.mark.asyncio
async def test_hyde_returns_decision_style_text():
    fake = _FakeLLM("经查，你公司在销售过程中存在承诺保本保息、夸大收益的违法行为。")
    rw = QueryRewriter(fake)
    out = await rw.hyde("这款产品保本保息，利息翻倍")
    assert "保本保息" in out or "夸大收益" in out
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_hyde_failure_returns_empty():
    class _Boom:
        def complete(self, *a, **k):
            raise RuntimeError("down")

    rw = QueryRewriter(_Boom())
    assert await rw.hyde("任意话术") == ""


@pytest.mark.asyncio
async def test_rewrite_parses_normalized_violation_json():
    fake = _FakeLLM(
        '{"normalized_violation":"以赠送体检卡作为投保优惠，给予投保人保险合同约定以外利益"}'
    )
    rw = QueryRewriter(fake, use_llm_rewrite=True)
    out = await rw.rewrite("送1000元体检卡")
    assert "体检卡" in out
    assert "合同约定以外" in out
    # dense_raw 保留原文，改写通道不再强制拼接口语
    assert out != "送1000元体检卡"


@pytest.mark.asyncio
async def test_rewrite_plain_text_fallback():
    fake = _FakeLLM("给予投保人合同外利益")
    rw = QueryRewriter(fake, use_llm_rewrite=True)
    out = await rw.rewrite("送1000元体检卡")
    assert "合同外利益" in out


@pytest.mark.asyncio
async def test_rewrite_can_skip_llm_and_keep_hyde():
    fake = _FakeLLM("经查你公司存在欺骗投保人行为")
    rw = QueryRewriter(fake, use_llm_rewrite=False)
    # 无同义词器时 rewrite 原样返回
    assert await rw.rewrite("原话术") == "原话术"
    assert await rw.hyde("原话术")
    assert "欺骗投保人" in fake.last_prompt or fake.calls >= 1
