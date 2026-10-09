"""评测集生成器测试。"""
import pytest

from ticket_diagnose.eval_set import generate_eval_set, to_ticket_text

CONCEPT_COUNT = 10


def test_eval_set_size_and_seed_reproducible():
    a = generate_eval_set(n=300, seed=42)
    b = generate_eval_set(n=300, seed=42)
    assert len(a) == 300
    assert a == b  # 固定 seed 可复现


def test_eval_set_covers_all_concepts():
    tickets = generate_eval_set()
    cats = {t["expect_category"] for t in tickets}
    subs = {t["expect_sub"] for t in tickets}
    assert len(cats) == 5  # 云桌面 / 超融合 / 网络安全 / 存储 / 服务器
    assert len(subs) == CONCEPT_COUNT  # 10 个故障概念全覆盖


def test_eval_set_annotations_complete():
    for t in generate_eval_set():
        assert t["id"].startswith("EVAL-")
        assert t["city"]
        assert t["title"]
        assert t["description"]
        assert t["expect_category"]
        assert t["expect_sub"]
        assert t["expect_priority"] in {"critical", "high", "medium", "low"}


def test_to_ticket_text_joins_title_and_description():
    t = generate_eval_set()[0]
    text = to_ticket_text(t)
    assert t["title"] in text
    assert t["description"] in text


def test_eval_set_priority_distribution_balanced():
    """六档严重度轮转，优先级分布应覆盖全部四级。"""
    tickets = generate_eval_set()
    pris = {t["expect_priority"] for t in tickets}
    assert pris == {"critical", "high", "medium", "low"}
