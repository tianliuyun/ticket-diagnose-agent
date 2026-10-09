"""业务 Mock 数据测试：多城市工单样例。"""
from ticket_diagnose.sample_data import SAMPLE_TICKETS, tickets_by_city, ticket_by_id


def test_has_batch_samples():
    """应有一批（>=8）多城市工单样例。"""
    assert len(SAMPLE_TICKETS) >= 8


def test_covers_three_cities():
    """样例覆盖北京/上海/深圳等多个城市。"""
    cities = {t["city"] for t in SAMPLE_TICKETS}
    assert cities >= {"北京", "上海", "深圳"}


def test_each_has_expected_labels():
    """每条样例都带期望类别/子类/优先级（供演示与回归校验）。"""
    for t in SAMPLE_TICKETS:
        assert t["expect_category"] and t["expect_sub"] and t["expect_priority"]


def test_tickets_by_city_filter():
    """按城市过滤正确。"""
    bj = tickets_by_city("北京")
    assert bj and all(t["city"] == "北京" for t in bj)


def test_ticket_by_id():
    """按工单号取样例正确。"""
    t = ticket_by_id("T-0001")
    assert t["city"] == "北京"
    assert t["expect_category"] == "云桌面"