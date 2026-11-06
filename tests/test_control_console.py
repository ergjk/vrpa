"""M6-02 测试：控制台指令集 + NLU 路由（发送默认 dry_run）。"""

from __future__ import annotations

from pathlib import Path

from vrpa.scheduling.loop import ControlChannel
from vrpa.testing.fakes import FakeExecutor
from wechat_agent.act.executor import WeChatExecutor
from wechat_agent.control.console import CommandRouter
from wechat_agent.control.knowledge import KnowledgeConsole
from wechat_agent.core.config import load_config
from wechat_agent.tools.plugin import default_registry

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")


def _router(tmp_path: Path) -> tuple[CommandRouter, ControlChannel]:
    control = ControlChannel()
    router = CommandRouter(
        executor=WeChatExecutor(CFG),
        control=control,
        knowledge=KnowledgeConsole(tmp_path / "knowledge"),
        plugins=default_registry(),
        status_provider=lambda: {"dry_run": True, "state": "running"},
    )
    return router, control


def test_help_and_status(tmp_path: Path) -> None:
    router, _ = _router(tmp_path)
    assert "/say" in router.dispatch("/help").text
    status = router.dispatch("/status").text
    assert "dry_run=True" in status and "state=running" in status


def test_control_commands(tmp_path: Path) -> None:
    router, control = _router(tmp_path)
    assert router.dispatch("/pause").ok is True
    commands = control.drain()
    assert [command.action for command in commands] == ["pause"]


def test_say_uses_dry_run(tmp_path: Path) -> None:
    router, _ = _router(tmp_path)
    reply = router.dispatch("/say 张三 你好")
    assert reply.ok and "dry_run" in reply.text


def test_takeover_and_knowledge_and_plugin(tmp_path: Path) -> None:
    router, control = _router(tmp_path)
    assert router.dispatch("/takeover 张三 手动接管").ok is True
    assert control.drain()[0].action == "takeover"
    assert router.dispatch("/knowledge list").ok is True
    assert "moments" in router.dispatch("/plugin list").text


def test_nlu_routing(tmp_path: Path) -> None:
    router, control = _router(tmp_path)
    assert router.dispatch("暂停").ok and control.drain()[0].action == "pause"
    assert router.dispatch("恢复").ok and control.drain()[0].action == "resume"
    assert "dry_run" in router.dispatch("状态").text
    assert "dry_run" in router.dispatch("发送给张三：你好").text
    assert router.dispatch("接管张三：手动").ok
    assert router.dispatch("知识列表").ok
    assert "moments" in router.dispatch("插件列表").text


def test_unknown_and_quit(tmp_path: Path) -> None:
    router, _ = _router(tmp_path)
    assert router.dispatch("今天天气不错").ok is False
    assert router.dispatch("/nope").ok is False
    assert router.dispatch("/quit").should_exit is True
    assert router.dispatch("").ok is False


def test_fake_executor_say_stage() -> None:
    router = CommandRouter(executor=FakeExecutor(dry_run=True))
    assert router.dispatch("/say 张三 你好").text.endswith("dry_run")
