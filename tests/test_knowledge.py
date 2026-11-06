"""M5-02 测试：知识 Provider/检索热加载、物理隔离、控制台接入端。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from vrpa.knowledge import FileKnowledgeProvider, KnowledgeBase, KnowledgeChunk, KnowledgeProvider
from vrpa.llm.client import LLMClient
from vrpa.memory.store import SQLiteMemoryStore
from wechat_agent.brain.client import WeChatBrain
from wechat_agent.control.knowledge import KnowledgeConsole
from wechat_agent.core.config import load_config

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")


def _write(path: Path, title: str, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n{content}", encoding="utf-8")


def _provider(tmp_path: Path) -> FileKnowledgeProvider:
    _write(tmp_path / "global" / "g.md", "全局制度", "报销需在 30 天内提交")
    _write(tmp_path / "chats" / "张三" / "c.md", "专属偏好", "用户喜欢喝美式")
    return FileKnowledgeProvider(tmp_path / "global", tmp_path / "chats")


def test_provider_scopes_and_titles(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    global_chunks = provider.chunks(None)
    assert len(global_chunks) == 1 and global_chunks[0].scope == "global"
    assert global_chunks[0].title == "全局制度"
    all_chunks = provider.chunks("张三")
    assert {(chunk.scope, chunk.title) for chunk in all_chunks} == {
        ("global", "全局制度"),
        ("chat", "专属偏好"),
    }


def test_provider_hot_reload_by_mtime(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    assert len(provider.chunks("张三")) == 2
    new_path = tmp_path / "global" / "h.md"
    _write(new_path, "新增知识", "新内容")
    os.utime(new_path, (2_000_000_000, 2_000_000_000))
    assert len(provider.chunks("张三")) == 3
    provider.reload()
    assert len(provider.chunks("张三")) == 3


def test_provider_implements_protocol(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    assert isinstance(provider, KnowledgeProvider)


def test_select_keyword_and_no_full_dump(tmp_path: Path) -> None:
    base = KnowledgeBase(_provider(tmp_path), max_chunks=6, max_chars=2000)
    assert base.select("张三", "") == ()
    selected = base.select("张三", "美式")
    assert len(selected) == 1 and selected[0].title == "专属偏好"
    assert base.select("张三", "不存在的词") == ()


def test_select_limits(tmp_path: Path) -> None:
    _write(tmp_path / "global" / "g.md", "制度", "报销 " * 500)
    _write(tmp_path / "global" / "h.md", "流程", "报销流程 " * 500)
    base = KnowledgeBase(
        FileKnowledgeProvider(tmp_path / "global", tmp_path / "chats"),
        max_chunks=1,
        max_chars=100,
    )
    selected = base.select("张三", "报销")
    assert len(selected) == 1
    assert len(selected[0].content) <= 100


def test_knowledge_never_written_to_memory_db(tmp_path: Path) -> None:
    provider = _provider(tmp_path / "knowledge")
    base = KnowledgeBase(provider)
    memory_store = SQLiteMemoryStore(tmp_path / "memory")
    try:
        selected = base.select("张三", "美式")
        assert selected
        assert not list(memory_store.recall(None, "", 10))
        assert not list(memory_store.history("张三", 10))
    finally:
        memory_store.close()


def test_console_list_reload_add(tmp_path: Path) -> None:
    console = KnowledgeConsole(tmp_path / "knowledge")
    assert console.handle("/knowledge list") == "（无知识）"
    added = console.handle("/knowledge add global 报销制度 报销需在 30 天内提交")
    assert "已写入" in added
    assert len(list((tmp_path / "knowledge" / "global").glob("*.md"))) == 1
    assert "global" in console.handle("/knowledge list")
    chat_added = console.handle("/knowledge add chat 张三 口味偏好 喜欢美式")
    assert "已写入" in chat_added
    assert "专属" not in console.handle("/knowledge list")
    assert "口味偏好" in console.handle("/knowledge list 张三")
    assert "知识已重载" in console.handle("/knowledge reload")
    assert "用法" in console.handle("/knowledge add bad")
    assert "用法" in console.handle("/bad")


def test_brain_injects_knowledge_without_memory_write(tmp_path: Path, monkeypatch) -> None:
    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method, url, *, headers, payload, timeout):
            self.calls.append({"payload": payload})
            return 200, {
                "model": "fake",
                "choices": [{"message": {"role": "assistant", "content": "喝美式吧"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    transport = FakeTransport()
    knowledge = KnowledgeBase(_provider(tmp_path / "knowledge"))
    client = LLMClient(
        api_key="sk-test", base_url="https://example.invalid/v1", transport=transport, sleep=lambda _s: None
    )
    brain = WeChatBrain(CFG, client=client, knowledge=knowledge)
    result = brain.generate([{"role": "user", "content": "我该喝什么？美式吗"}], session="张三")
    assert result.text == "喝美式吧"
    system = transport.calls[0]["payload"]["messages"][0]["content"]
    assert '<knowledge scope="chat"' in system
    assert "用户喜欢喝美式" in system
    # 检索接口按关键词过滤：无关的全局知识不得塞入
    assert '<knowledge scope="global"' not in system


def test_third_party_provider_protocol() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.reloaded = 0

        def chunks(self, chat_id: str | None = None) -> tuple[KnowledgeChunk, ...]:
            return (KnowledgeChunk(scope="global", title="外部知识", content=f"chat={chat_id} 关键词"),)

        def reload(self) -> None:
            self.reloaded += 1

    provider = FakeProvider()
    assert isinstance(provider, KnowledgeProvider)
    base = KnowledgeBase(provider)
    assert base.select("张三", "关键词")[0].title == "外部知识"
    base.reload()
    assert provider.reloaded == 1
