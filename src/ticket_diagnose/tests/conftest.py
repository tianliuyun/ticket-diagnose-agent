"""共享 pytest fixtures：Mock 后端注入 + 路径配置。"""
import os
import sys

import pytest

# tests 目录: <项目根>/src/ticket_diagnose/tests
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_TESTS_DIR)))  # <项目根>
_PROJECTS_DIR = os.path.dirname(_PROJECT_ROOT)  # 项目工作区根目录

# 把新项目 src 与两个源项目 src 加入搜索路径
for p in [
    os.path.join(_PROJECT_ROOT, "src"),                                  # ticket-diagnose-agent/src
    os.path.join(_PROJECTS_DIR, "ticket-classifier", "src"),
    os.path.join(_PROJECTS_DIR, "parallel-code-reviewer", "src"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from code_reviewer import llm_client  # noqa: E402
from ticket_diagnose import mock_backend as diag_mock  # noqa: E402


@pytest.fixture(autouse=True)
def mock_backend(monkeypatch):
    """所有测试走诊断 Mock 后端（离线规则、秒级、幂等），测试间重置。"""
    monkeypatch.setenv("CODE_REVIEW_MOCK", "0")
    llm_client.reset_backend()
    diag_mock.install_mock_backend()
    yield
    llm_client.reset_backend()