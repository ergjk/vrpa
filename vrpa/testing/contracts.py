"""适配器合规测试套件（M0-F-04）：任何平台适配器必须全绿才能接入 VRPA 底座。

判定标准（docs/ADR/0003-interface-stability.md）：
    1. 身份与能力：kind / display_name / adapter_version / capabilities 完整；
    2. 配置插件：实现 PlatformPlugin 结构且 kind 与适配器一致；
    3. 元素树 profile 规范与解析策略包存在且结构合规；
    4. create_ports 返回五端口集合，且五个端口满足协议；
    5. 端口冒烟：可完成一次「激活 -> 采集 -> 推理 -> 发送 -> 回写」的最小调用；
    6. 幂等：create_ports 可重复调用。

使用方式：
    代码：``from vrpa.testing.contracts import run_all`` -> ``report = run_all(adapter)``
    命令行：``python -m vrpa.testing.contracts --adapter mypkg.adapter:MyAdapter [--json]``

注意：端口冒烟检查会在**受控环境**中真实调用适配器端口一次（激活窗口 / 采集 / 发送到 dry-run）。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from vrpa.config.plugin import is_platform_plugin
from vrpa.platform import AdapterInfo, PlatformAdapter, is_platform_adapter
from vrpa.ports import Brain, ElementTree, Executor, MemoryStore, Perception, Ports, Rect

__all__ = [
    "ContractCheck",
    "ContractReport",
    "load_adapter",
    "main",
    "run_all",
]

_PROBE_SESSION = "contract-probe"


@dataclass(frozen=True)
class ContractCheck:
    """单条契约检查结果。"""

    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class ContractReport:
    """适配器契约报告。"""

    adapter_kind: str
    adapter_version: str
    checks: tuple[ContractCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failed(self) -> tuple[ContractCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def render(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines = [
            "== VRPA adapter contract report ==",
            f"adapter : {self.adapter_kind} v{self.adapter_version}",
            "checks  :",
        ]
        for check in self.checks:
            marker = "OK  " if check.ok else "FAIL"
            lines.append(f"  [{marker}] {check.name} :: {check.detail}")
        passed = sum(1 for check in self.checks if check.ok)
        lines.append(f"RESULT: {status} ({passed}/{len(self.checks)})")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "adapter": {"kind": self.adapter_kind, "version": self.adapter_version},
            "checks": [{"name": check.name, "ok": check.ok, "detail": check.detail} for check in self.checks],
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _non_empty_str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} 必须是非空字符串，实际为 {value!r}")
    return value


def run_all(adapter: PlatformAdapter) -> ContractReport:
    """对适配器执行全部契约检查并返回报告（不抛异常）。"""
    checks: list[ContractCheck] = []

    def run(name: str, fn: Callable[[], str]) -> None:
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 - 契约检查必须捕获一切并落成 FAIL
            checks.append(ContractCheck(name=name, ok=False, detail=str(exc) or repr(exc)))
        else:
            checks.append(ContractCheck(name=name, ok=True, detail=detail))

    def _plugin() -> Any:
        return adapter.config_plugin()

    def _ports() -> Ports:
        return adapter.create_ports(_plugin().default_options())

    def check_identity() -> str:
        _require(is_platform_adapter(adapter), "目标未实现 PlatformAdapter 结构")
        kind = _non_empty_str(adapter.kind, "kind")
        _non_empty_str(adapter.display_name, "display_name")
        _non_empty_str(adapter.adapter_version, "adapter_version")
        return f"{kind} ({adapter.display_name} v{adapter.adapter_version})"

    def check_capabilities() -> str:
        capabilities = adapter.capabilities()
        _require(isinstance(capabilities, frozenset), "capabilities 必须返回 frozenset[str]")
        _require(len(capabilities) > 0, "capabilities 不能为空")
        for capability in capabilities:
            _non_empty_str(capability, "capability")
        return ", ".join(sorted(capabilities))

    def check_config_plugin() -> str:
        plugin = _plugin()
        _require(is_platform_plugin(plugin), "config_plugin() 未实现 PlatformPlugin 结构")
        _require(plugin.kind == adapter.kind, f"插件 kind={plugin.kind!r} 与适配器 kind={adapter.kind!r} 不一致")
        meta = plugin.meta()
        _require(meta.kind == adapter.kind, "插件 meta().kind 与适配器 kind 不一致")
        _require(isinstance(plugin.default_options(), Mapping), "插件 default_options() 必须是 Mapping")
        _non_empty_str(plugin.describe(), "插件 describe()")
        return f"plugin kind={plugin.kind} version={meta.plugin_version}"

    def check_profile_spec() -> str:
        spec = adapter.element_tree_profile_spec()
        _require(isinstance(spec, Mapping), "element_tree_profile_spec 必须是 Mapping")
        _require(isinstance(spec.get("schema"), int), "profile spec 缺少整数 schema")
        elements = spec.get("elements")
        _require(isinstance(elements, Sequence) and len(elements) > 0, "profile spec 缺少非空 elements")
        return f"schema={spec.get('schema')} elements={len(cast(Sequence[Any], elements))}"

    def check_parser_pack() -> str:
        pack = adapter.parser_pack()
        _require(isinstance(pack, Mapping), "parser_pack 必须是 Mapping")
        strategies = pack.get("strategies")
        _require(
            isinstance(strategies, Sequence) and len(strategies) > 0,
            "parser_pack 缺少非空 strategies",
        )
        return f"strategies={len(cast(Sequence[Any], strategies))}"

    def check_create_ports() -> str:
        ports = _ports()
        _require(isinstance(ports, Ports), "create_ports 必须返回 Ports")
        for name, value, proto in (
            ("element_tree", ports.element_tree, ElementTree),
            ("perception", ports.perception, Perception),
            ("executor", ports.executor, Executor),
            ("brain", ports.brain, Brain),
            ("memory", ports.memory, MemoryStore),
        ):
            _require(isinstance(value, proto), f"端口 {name} 不满足协议")
        return "5/5 端口满足协议"

    def check_port_smoke() -> str:
        ports = _ports()
        element_ids = ports.element_tree.element_ids()
        _require(len(element_ids) > 0, "element_ids 不能为空")
        _non_empty_str(ports.element_tree.profile_name(), "profile_name")
        located = ports.element_tree.locate(str(element_ids[0]))
        _require(isinstance(located, Rect), "locate 必须返回 Rect")
        ports.perception.activate()
        captured = ports.perception.capture(_PROBE_SESSION)
        _require(isinstance(captured, str), "capture 必须返回 str")
        _require(isinstance(ports.executor.is_dry_run(), bool), "is_dry_run 必须返回 bool")
        _require(ports.brain.ping() >= 0, "brain.ping 必须返回非负延迟")
        ports.memory.recent_hashes(_PROBE_SESSION, 1)
        ports.memory.writeback(_PROBE_SESSION, "[contract-probe]")
        return f"captured {len(captured)} chars"

    def check_create_ports_idempotent() -> str:
        _ports()
        _ports()
        return "create_ports 可重复调用"

    def check_adapter_info() -> str:
        info = AdapterInfo.from_adapter(adapter)
        _require(info.kind == adapter.kind, "AdapterInfo.kind 不一致")
        return f"capabilities={','.join(info.capabilities)}"

    def check_describe() -> str:
        return _non_empty_str(adapter.describe(), "describe()")

    run("adapter.identity", check_identity)
    run("adapter.capabilities", check_capabilities)
    run("adapter.config_plugin", check_config_plugin)
    run("adapter.element_tree_profile_spec", check_profile_spec)
    run("adapter.parser_pack", check_parser_pack)
    run("adapter.create_ports", check_create_ports)
    run("ports.smoke", check_port_smoke)
    run("adapter.create_ports.idempotent", check_create_ports_idempotent)
    run("adapter.info", check_adapter_info)
    run("adapter.describe", check_describe)

    return ContractReport(
        adapter_kind=str(getattr(adapter, "kind", "<unknown>")),
        adapter_version=str(getattr(adapter, "adapter_version", "<unknown>")),
        checks=tuple(checks),
    )


def load_adapter(spec: str) -> PlatformAdapter:
    """按 ``模块:属性`` 加载适配器（属性可以是类或实例）。"""
    if ":" not in spec:
        raise ValueError("--adapter 需要 <模块>:<属性> 形式，例如 mypkg.adapter:MyAdapter")
    module_name, attribute = spec.split(":", 1)
    module = importlib.import_module(module_name)
    target = getattr(module, attribute)
    adapter = target() if isinstance(target, type) else target
    if not is_platform_adapter(adapter):
        raise ValueError(f"{spec} 未实现 PlatformAdapter 结构")
    return cast(PlatformAdapter, adapter)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI：``python -m vrpa.testing.contracts --adapter module:attr [--json]``"""
    parser = argparse.ArgumentParser(
        prog="python -m vrpa.testing.contracts",
        description="VRPA 平台适配器合规测试套件",
    )
    parser.add_argument("--adapter", required=True, help="模块:属性，如 mypkg.adapter:MyAdapter")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出报告")
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:  # argparse 在用法错误时抛出 SystemExit
        return int(exc.code) if isinstance(exc.code, int) else 2

    adapter_spec = str(args.adapter)
    try:
        adapter = load_adapter(adapter_spec)
    except Exception as exc:  # noqa: BLE001 - CLI 需要把加载失败映射为退出码 2
        print(f"无法加载适配器 {adapter_spec!r}：{exc}", file=sys.stderr)
        return 2

    report = run_all(adapter)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if args.json else report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
