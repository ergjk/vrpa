"""M6-04 测试：插件接口、故障隔离与 moments 示例。"""

from __future__ import annotations

from datetime import datetime

from vrpa.plugins import Plugin, PluginContext, PluginManager, PluginMeta
from wechat_agent.plugins.moments import MomentsPlugin
from wechat_agent.tools.plugin import run_plugin


class GoodPlugin:
    meta = PluginMeta(name="good", version="1.0", description="正常插件")

    def __init__(self) -> None:
        self.started = 0
        self.ticked = 0

    def on_start(self, context: PluginContext) -> None:
        self.started += 1

    def on_tick(self, context: PluginContext, tick: int) -> None:
        self.ticked += 1

    def on_message(self, context: PluginContext, chat: str, content: str) -> None:
        return None

    def on_stop(self, context: PluginContext) -> None:
        return None


class BadPlugin(GoodPlugin):
    meta = PluginMeta(name="bad", version="1.0")

    def on_tick(self, context: PluginContext, tick: int) -> None:
        raise RuntimeError("插件崩溃")


def test_manager_register_dispatch_and_isolation() -> None:
    manager = PluginManager()
    good, bad = GoodPlugin(), BadPlugin()
    manager.register(good)
    manager.register(bad)
    assert isinstance(good, Plugin)
    assert [meta.name for meta in manager.plugins()] == ["good", "bad"]
    successes = manager.dispatch("on_tick", PluginContext(), 1)
    assert successes == 1 and good.ticked == 1
    assert any("bad.on_tick" in error for error in manager.errors)
    assert manager.unregister("bad") is True
    assert manager.unregister("bad") is False
    assert manager.get("good") is good


def test_duplicate_plugin_rejected() -> None:
    manager = PluginManager()
    manager.register(GoodPlugin())
    try:
        manager.register(GoodPlugin())
    except ValueError as exc:
        assert "已注册" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("重复注册应失败")


def test_moments_creates_one_draft_per_day() -> None:
    plugin = MomentsPlugin(
        schedule=("09:00",), clock=lambda: datetime(2026, 1, 1, 9, 0), generator=lambda day: "今天分享"
    )
    context = PluginContext(dry_run=True)
    plugin.on_tick(context, 1)
    plugin.on_tick(context, 2)
    drafts = plugin.drain()
    assert len(drafts) == 1
    assert drafts[0].content == "今天分享"
    assert drafts[0].visibility == "private"
    assert plugin.drain() == ()


def test_moments_dry_run_never_sends() -> None:
    plugin = MomentsPlugin(schedule=("10:30",), clock=lambda: datetime(2026, 1, 1, 10, 30))
    plugin.on_tick(PluginContext(dry_run=True), 1)
    drafts = plugin.drain()
    assert drafts and "2026-01-01" in drafts[0].scheduled_for


def test_moments_skips_unscheduled_minute() -> None:
    plugin = MomentsPlugin(schedule=("09:00",), clock=lambda: datetime(2026, 1, 1, 8, 0))
    plugin.on_tick(PluginContext(), 1)
    assert plugin.drain() == ()


def test_plugin_cli(capsys) -> None:
    assert run_plugin(["list"]) == 0
    assert "moments" in capsys.readouterr().out
    assert run_plugin(["plan", "moments"]) == 0
    assert "dry_run" in capsys.readouterr().out
    assert run_plugin(["plan", "missing"]) == 2
