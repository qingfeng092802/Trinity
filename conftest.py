"""pytest 根夹具：提供全局 ``settings`` fixture（单元测试的配置契约用例依赖它）。

集成测试的专用夹具在 ``tests/integration/conftest.py``，这里只放跨目录共享的
最小集合。 ``settings`` fixture 每次重建配置单例，保证用例之间互不串环境。

另外这里在**导入期**就把 ``data/.test-scratch`` 建出来：多个测试模块把它当临时
落盘根目录，而空目录既进不了 git 也进不了 zip，干净 clone 会让那批用例直接
``FileNotFoundError``。与其要求人手 mkdir，不如让测试自愈。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import PROJECT_ROOT, Settings, get_settings, reset_settings_cache

#: 各测试模块共用的临时落盘根目录（与 tests/unit/* 里的同名常量保持一致）。
TEST_SCRATCH_ROOT: Path = PROJECT_ROOT / "data" / ".test-scratch"
TEST_SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def settings() -> Settings:
    """返回一份 freshly 构建的全局配置（不缓存，避免跨用例污染）。"""
    reset_settings_cache()
    return get_settings()


@pytest.fixture(autouse=True)
def _reset_settings_after() -> None:
    """每个用例结束后清一次配置缓存，防止环境变量泄漏到下一个用例。"""
    yield
    reset_settings_cache()


__all__ = ["TEST_SCRATCH_ROOT", "settings"]
