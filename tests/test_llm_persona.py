"""M5-04 测试：人设热加载。"""

from __future__ import annotations

from pathlib import Path

from vrpa.llm.persona import DEFAULT_PERSONA, PersonaLoader


def test_load_and_cache(tmp_path: Path) -> None:
    path = tmp_path / "persona.txt"
    path.write_text("第一版人设", encoding="utf-8")
    mtimes = {path: 1.0}
    loader = PersonaLoader(path, mtime=lambda target: mtimes.get(target, -1.0))
    assert loader.load() == "第一版人设"
    assert loader.version == 1
    assert loader.load() == "第一版人设"
    assert loader.version == 1


def test_hot_reload_on_mtime_change(tmp_path: Path) -> None:
    path = tmp_path / "persona.txt"
    path.write_text("第一版", encoding="utf-8")
    mtimes = {path: 1.0}
    loader = PersonaLoader(path, mtime=lambda target: mtimes.get(target, -1.0))
    loader.load()
    path.write_text("第二版", encoding="utf-8")
    mtimes[path] = 2.0
    assert loader.load() == "第二版"
    assert loader.version == 2


def test_missing_file_uses_default(tmp_path: Path) -> None:
    loader = PersonaLoader(tmp_path / "missing.txt", mtime=lambda _target: -1.0)
    assert loader.load() == DEFAULT_PERSONA
    assert loader.version == 1


def test_empty_file_falls_back_to_cached(tmp_path: Path) -> None:
    path = tmp_path / "persona.txt"
    path.write_text("好人设", encoding="utf-8")
    loader = PersonaLoader(path, mtime=lambda target: 1.0)
    loader.load()
    path.write_text("", encoding="utf-8")
    assert loader.reload() == "好人设"
    assert loader.version == 2


def test_force_reload(tmp_path: Path) -> None:
    path = tmp_path / "persona.txt"
    path.write_text("A", encoding="utf-8")
    loader = PersonaLoader(path, mtime=lambda _target: 1.0)
    loader.load()
    path.write_text("B", encoding="utf-8")
    assert loader.load(force=True) == "B"
