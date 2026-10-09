"""业务 Mock 数据：一批跨多城市的真实感企业 IT 故障工单样例。

覆盖三个城市（北京 / 上海 / 深圳）各产品大类，供演示与单测使用。
表述均为「企业 IT 故障工单」通用语言，不含任何厂商专有产品名。
"""
from typing import Dict, List

# 多城市工单样例：id / city / title / description / 期望类别(便于演示校验)
SAMPLE_TICKETS: List[Dict] = [
    {
        "id": "T-0001", "city": "北京",
        "title": "桌面云登录大面积超时",
        "description": "北京分公司办公区桌面云上午 10 点起大面积登录超时，业务中断约 30 分钟，急需恢复",
        "expect_category": "云桌面", "expect_sub": "登录连接", "expect_priority": "critical",
    },
    {
        "id": "T-0002", "city": "上海",
        "title": "虚拟桌面鼠标卡顿严重",
        "description": "上海分部部分虚拟桌面操作卡顿、鼠标延迟明显，影响日常办公，概率性出现",
        "expect_category": "云桌面", "expect_sub": "性能卡顿", "expect_priority": "medium",
    },
    {
        "id": "T-0003", "city": "深圳",
        "title": "超融合集群存储池降级",
        "description": "深圳机房超融合集群存储池报降级，节点风扇报警，疑似物理机宕机",
        "expect_category": "超融合", "expect_sub": "存储集群", "expect_priority": "high",
    },
    {
        "id": "T-0004", "city": "北京",
        "title": "防火墙策略误拦截导致业务端口不通",
        "description": "北京总部防火墙策略不生效，误拦截了财务系统的 443 端口，个别员工连不上",
        "expect_category": "网络安全", "expect_sub": "防火墙", "expect_priority": "high",
    },
    {
        "id": "T-0005", "city": "上海",
        "title": "VPN 隧道中断员工拨不上",
        "description": "上海出差员工 VPN 隧道中断无法拨上，多方验证是证书失效导致",
        "expect_category": "网络安全", "expect_sub": "VPN", "expect_priority": "high",
    },
    {
        "id": "T-0006", "city": "深圳",
        "title": "存储磁盘亮灯 RAID 降级",
        "description": "深圳机房的存储阵列磁盘亮灯、RAID 降级，IO 开始报错，需要尽快定位坏盘",
        "expect_category": "存储", "expect_sub": "磁盘故障", "expect_priority": "high",
    },
    {
        "id": "T-0007", "city": "北京",
        "title": "服务器电源报警风扇异响",
        "description": "北京服务器电源报警、风扇异响，指示灯异常，疑似硬件故障",
        "expect_category": "服务器", "expect_sub": "硬件故障", "expect_priority": "high",
    },
    {
        "id": "T-0008", "city": "上海",
        "title": "云主机启动失败资源不足",
        "description": "上海私有云因内存超分、计算资源不足导致云主机启动失败，需要调整",
        "expect_category": "私有云", "expect_sub": "计算资源", "expect_priority": "high",
    },
    {
        "id": "T-0009", "city": "北京",
        "title": "服务器操作系统蓝屏引导失败",
        "description": "北京某服务器操作系统蓝屏，重启后引导失败，怀疑是驱动冲突",
        "expect_category": "服务器", "expect_sub": "操作系统", "expect_priority": "high",
    },
    {
        "id": "T-0010", "city": "深圳",
        "title": "桌面云外设 U 盘无法重定向",
        "description": "深圳员工虚拟桌面里 U 盘外设无法重定向，使用读卡器时识别不到，偶尔出现",
        "expect_category": "云桌面", "expect_sub": "外设重定向", "expect_priority": "medium",
    },
]


def tickets_by_city(city: str) -> List[Dict]:
    """按城市过滤工单样例。"""
    return [t for t in SAMPLE_TICKETS if t["city"] == city]


def ticket_by_id(ticket_id: str) -> Dict:
    """按工单号取样例。"""
    for t in SAMPLE_TICKETS:
        if t["id"] == ticket_id:
            return t
    raise KeyError(f"工单不存在: {ticket_id}")