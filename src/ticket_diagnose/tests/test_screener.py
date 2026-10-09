"""初筛工具测试：包装 MockClassifier 的 classify_ticket。"""
import pytest

from ticket_diagnose.screener import InitialScreener, classify_ticket


@pytest.fixture
def screener():
    return InitialScreener()


def test_classify_returns_dict_schema(screener):
    """初筛返回 {类别,子类,优先级,置信度} 四要素字典。"""
    r = screener.classify_ticket("桌面云登录大面积超时，业务中断")
    assert set(r) >= {"类别", "子类", "优先级", "置信度"}


def test_classify_cloud_desktop_login(screener):
    """云桌面登录类工单应被初筛为 云桌面/登录连接。"""
    r = screener.classify_ticket("北京桌面云登录超时，全体员工无法登录")
    assert r["类别"] == "云桌面"
    assert r["子类"] == "登录连接"


def test_classify_priority_critical(screener):
    """含"业务中断/大面积"的工单应判 critical。"""
    r = screener.classify_ticket("桌面云大面积登录超时，业务中断，急需恢复")
    assert r["优先级"] == "critical"


def test_classify_network_security(screener):
    """网络/防火墙类工单应判 网络安全/防火墙。"""
    r = screener.classify_ticket("防火墙策略误拦截财务系统 443 端口")
    assert r["类别"] == "网络安全"


def test_classify_storage_disk(screener):
    """存储/磁盘类工单应判 存储/磁盘故障。"""
    r = screener.classify_ticket("存储磁盘亮灯 RAID 降级，IO 报错")
    assert r["类别"] == "存储"
    assert r["子类"] == "磁盘故障"


def test_module_level_classify_ticket():
    """模块级便捷函数 classify_ticket 可用且返回类别。"""
    r = classify_ticket("超融合集群存储池降级")
    assert r["类别"] == "超融合"


def test_str_tool_has_chinese(screener):
    """字符串版初筛工具（供 ReAct 用）是可读中文文本。"""
    s = screener.classify_ticket_str("VPN 隧道中断员工拨不上")
    assert "类别" in s and "优先级" in s