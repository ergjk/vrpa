"""元素定位器（M1-03，平台无关）：锚点多尺度匹配 + 定位缓存 + 严格失败语义。

- ``locate()``：父元素相对区域裁剪 -> 多尺度锚点匹配 -> 绝对坐标；
- 失败必须抛 ``ElementNotVisible``，绝不返回猜测坐标（红线 R3）；
- 缓存默认 2s，任何界面动作后调用 ``invalidate()`` 立即失效；
- ``validate()``：结构校验 + 逐元素现场定位（validate-tree 的数据源）。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from vrpa.errors import ElementNotVisible, TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.matcher import AnchorMatcher, Image, MatchResult, load_image
from vrpa.vision.profile import ElementSpec, Profile
from vrpa.vision.screen import ScreenSource

__all__ = ["AnchorLocator", "ValidationReport"]

TemplateLoader = Callable[[Path], Image]


@dataclass(frozen=True)
class ValidationReport:
    """validate-tree 结果。"""

    problems: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems


class AnchorLocator:
    """带缓存的元素定位器。"""

    def __init__(
        self,
        profile: Profile,
        screen: ScreenSource,
        *,
        matcher: AnchorMatcher | None = None,
        cache_ttl: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        template_loader: TemplateLoader = load_image,
    ) -> None:
        if cache_ttl < 0:
            raise TreeConfigError(f"cache_ttl 不能为负：{cache_ttl}")
        self._profile = profile
        self._screen = screen
        self._matcher = matcher or AnchorMatcher()
        self._cache_ttl = float(cache_ttl)
        self._clock = clock
        self._template_loader = template_loader
        self._cache: dict[str, tuple[Rect, float]] = {}
        self._last_match: dict[str, MatchResult] = {}
        self._best_scores: dict[str, float] = {}

    # ------------------------------------------------------------ 公共 API
    def element_ids(self) -> tuple[str, ...]:
        return self._profile.element_ids()

    def profile_name(self) -> str:
        return self._profile.profile

    def invalidate(self) -> None:
        self._cache.clear()

    def last_match(self, element_id: str) -> MatchResult | None:
        return self._last_match.get(element_id)

    def best_score(self, element_id: str) -> float:
        return self._best_scores.get(element_id, 0.0)

    def locate(self, element_id: str) -> Rect:
        """定位元素；失败抛 ``ElementNotVisible``（禁止坐标兜底）。"""
        cached = self._cache.get(element_id)
        if cached is not None and self._clock() < cached[1]:
            return cached[0]
        spec = self._profile.get(element_id)
        rect = self._locate_spec(spec, visited=[])
        self._cache[element_id] = (rect, self._clock() + self._cache_ttl)
        return rect

    def validate(
        self,
        *,
        required_ids: Sequence[str] = (),
        check_anchor_files: bool = True,
    ) -> ValidationReport:
        """结构校验 + 逐个现场定位，返回问题列表。"""
        problems = list(self._profile.validate(required_ids=required_ids, check_anchor_files=check_anchor_files))
        targets = tuple(required_ids) if required_ids else self._profile.element_ids()
        checked: list[str] = []
        for element_id in targets:
            try:
                self.locate(element_id)
            except (ElementNotVisible, TreeConfigError) as exc:
                problems.append(f"{element_id}: {exc}")
            else:
                checked.append(element_id)
        return ValidationReport(problems=tuple(problems), checked=tuple(checked))

    # ------------------------------------------------------------ 内部
    def _locate_spec(self, spec: ElementSpec, *, visited: list[str]) -> Rect:
        if spec.rect is not None:
            return Rect(*spec.rect)
        if not spec.anchors:
            raise ElementNotVisible(f"元素 {spec.element_id} 未配置锚点图（先执行 calibrate）")
        if spec.element_id in visited:
            raise TreeConfigError(f"元素 {spec.element_id} 的 parent 链存在环：{visited}")
        visited.append(spec.element_id)

        offset_x = offset_y = 0
        region: Image = self._screen.capture()
        if spec.parent is not None:
            parent_rect = self._locate_spec(self._profile.get(spec.parent), visited=visited)
            offset_x, offset_y = parent_rect.x, parent_rect.y
            region = self._crop(region, parent_rect, element_id=spec.element_id)
        visited.pop()

        match = self._match_anchors(spec, region)
        self._best_scores[spec.element_id] = self._matcher.last_score
        if match is None:
            thresholds = ", ".join(
                f"{anchor.path}:{anchor.threshold if anchor.threshold is not None else self._matcher._threshold}"
                for anchor in spec.anchors
            )
            raise ElementNotVisible(
                f"元素 {spec.element_id} 未匹配到锚点（阈值 {thresholds}；"
                f"最高分 {self._matcher.last_score:.3f}；profile={self._profile.profile}）"
            )
        self._last_match[spec.element_id] = match
        return Rect(
            offset_x + match.rect.x,
            offset_y + match.rect.y,
            match.rect.width,
            match.rect.height,
        )

    def _match_anchors(self, spec: ElementSpec, region: Image) -> MatchResult | None:
        for anchor in spec.anchors:
            template = self._template_loader(self._profile.anchor_path(spec.element_id, anchor))
            result = self._matcher.match(
                region,
                template,
                threshold=anchor.threshold,
                scales=anchor.scales or None,
            )
            if result is not None:
                return result
        return None

    @staticmethod
    def _crop(region: Image, rect: Rect, *, element_id: str) -> Image:
        height, width = region.shape[:2]
        if rect.x < 0 or rect.y < 0 or rect.right > width or rect.bottom > height:
            raise ElementNotVisible(f"元素 {element_id} 的父区域越界：{rect.as_tuple()}（屏幕 {width}x{height}）")
        return region[rect.y : rect.bottom, rect.x : rect.right]
