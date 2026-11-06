"""通用配置校验原语（平台无关）。

约定：
    - 所有函数错误统一抛 ``ConfigError``（退出码 2），错误信息带配置路径；
    - 未知键一律报错（防止拼写错误被静默忽略）；
    - 布尔值不接受字符串/整数，整数不接受布尔，区间必须 ``[下限, 上限]`` 且下限不大于上限。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import Any

from vrpa.errors import ConfigError

__all__ = [
    "as_bool",
    "as_float",
    "as_int",
    "as_number_list",
    "as_range",
    "as_ratio",
    "as_str",
    "as_str_list",
    "check_keys",
    "expect_mapping",
    "mask_secret",
    "section",
]


def expect_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} 必须是映射（dict），实际为 {type(value).__name__}")
    return value


def section(root: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if name not in root:
        raise ConfigError(f"配置缺少段落：{name}")
    return expect_mapping(root[name], name)


def check_keys(raw: Mapping[str, Any], allowed: Sequence[str], where: str) -> None:
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise ConfigError(f"{where} 存在未知键：{unknown}（允许：{sorted(allowed)}）")


def as_bool(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{where} 必须是布尔值 true/false，实际为 {value!r}")


def as_int(
    value: Any,
    where: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where} 必须是整数，实际为 {value!r}")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{where} 必须 >= {minimum}，实际为 {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{where} 必须 <= {maximum}，实际为 {value}")
    return value


def as_float(
    value: Any,
    where: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_exclusive: bool = False,
    maximum_exclusive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} 必须是数字，实际为 {value!r}")
    result = float(value)
    if minimum is not None:
        if minimum_exclusive and not result > minimum:
            raise ConfigError(f"{where} 必须 > {minimum}，实际为 {result}")
        if not minimum_exclusive and result < minimum:
            raise ConfigError(f"{where} 必须 >= {minimum}，实际为 {result}")
    if maximum is not None:
        if maximum_exclusive and not result < maximum:
            raise ConfigError(f"{where} 必须 < {maximum}，实际为 {result}")
        if not maximum_exclusive and result > maximum:
            raise ConfigError(f"{where} 必须 <= {maximum}，实际为 {result}")
    return result


def as_str(value: Any, where: str, *, choices: AbstractSet[str] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} 必须是非空字符串，实际为 {value!r}")
    result = value.strip()
    if choices is not None and result not in choices:
        raise ConfigError(f"{where} 必须是 {sorted(choices)} 之一，实际为 {result!r}")
    return result


def as_str_list(value: Any, where: str, *, non_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"{where} 必须是字符串列表，实际为 {type(value).__name__}")
    items = tuple(as_str(item, f"{where}[{index}]") for index, item in enumerate(value))
    if non_empty and not items:
        raise ConfigError(f"{where} 不能为空列表")
    return items


def as_number_list(value: Any, where: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ConfigError(f"{where} 必须是非空数字列表，实际为 {value!r}")
    return tuple(value)


def as_range(value: Any, where: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConfigError(f"{where} 必须是 [最小, 最大] 两元素区间，实际为 {value!r}")
    low = as_float(value[0], f"{where}[0]", minimum=0.0)
    high = as_float(value[1], f"{where}[1]", minimum=0.0)
    if low > high:
        raise ConfigError(f"{where} 区间下限不能大于上限：{low} > {high}")
    return (low, high)


def as_ratio(value: Any, where: str) -> float:
    return as_float(value, where, minimum=0.0, maximum=1.0)


def mask_secret(value: str | None) -> str:
    """密钥掩码：保留前 3 位与后 4 位；过短/未设置给固定占位。"""
    if not value:
        return "<未设置>"
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}***{value[-4:]}"
