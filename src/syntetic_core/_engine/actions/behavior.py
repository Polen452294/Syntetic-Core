"""Bounded, configurable interaction timing for normal scenario execution."""

import asyncio
import math
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from hashlib import sha256
from time import monotonic
from typing import Any
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Locator, Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeout

from syntetic_core._engine.errors import NavigationError, SearchEntryError, VisitDurationExceeded
from syntetic_core._engine.pacing import _sample_pause_ms
from syntetic_core._engine.personas import BehaviorConfig
from syntetic_core._engine.scenarios.validation import StepTiming
from syntetic_core._engine.schemas.analytics import AnalyticsRoute


class InteractionBehavior:
    def __init__(
        self, config: BehaviorConfig, *, main_world: bool = False, touch: bool = False
    ) -> None:
        self.config = config
        self.main_world = main_world
        self.touch = touch
        self.random = random.Random(config.seed)
        self.cursor: tuple[float, float] = (0, 0)
        self.native_cursor = False
        self.last_pause_ms = 0

    def _sample_pause_ms(self, minimum: int, maximum: int) -> int:
        return _sample_pause_ms(minimum, maximum, self.config, self.random)

    async def pause(self, timing: StepTiming | None = None) -> None:
        self.last_pause_ms = 0
        if timing is not None:
            self.last_pause_ms = self._sample_pause_ms(timing.min_ms, timing.max_ms)
        elif self.config.enabled:
            self.last_pause_ms = self._sample_pause_ms(
                self.config.pause_min_ms, self.config.pause_max_ms
            )
        if self.last_pause_ms:
            await asyncio.sleep(self.last_pause_ms / 1000)

    async def type(self, locator: Locator, value: str) -> None:
        if self.touch:
            from syntetic_core._engine.browser.mobile import type_mobile_text

            await locator.focus()
            await type_mobile_text(locator.page, value, self.config, self.random)
            return
        if not self.config.enabled:
            await locator.press_sequentially(value)
            return
        for character in value:
            await locator.press_sequentially(
                character,
                delay=self._sample_pause_ms(self.config.key_min_ms, self.config.key_max_ms),
            )

    async def approach(self, page: Page, locator: Locator) -> None:
        if not self.config.enabled or self.native_cursor or self.touch:
            return
        await locator.scroll_into_view_if_needed()
        box = await locator.bounding_box()
        if box is None:
            return
        target = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await self.move_to(page, target, (box["width"], box["height"]))

    async def move_to(
        self,
        page: Page,
        target: tuple[float, float],
        size: tuple[float, float],
        *,
        bounds: tuple[float, float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        perlin_tremor: bool = False,
    ) -> None:
        """Fitts timing, bounded hand tremor and occasional corrective submovement."""
        sleep = sleep or asyncio.sleep
        start = self.cursor
        delta = (target[0] - start[0], target[1] - start[1])
        distance = math.hypot(*delta)
        # Effective width of the rectangle along the approach vector.
        width = max(
            1.0,
            min(
                size[0] * distance / max(abs(delta[0]), 1e-9),
                size[1] * distance / max(abs(delta[1]), 1e-9),
            ),
        )
        duration = min(
            self.config.cursor_seconds,
            (0.07 + 0.11 * math.log2(1 + distance / width)) * self.random.uniform(0.85, 1.15),
        )
        if self.native_cursor:
            await page.mouse.move(*target)
            self.cursor = target
            await sleep(duration)
            return
        steps = self.random.randint(15, 35)
        overshoot = distance > width and self.random.random() < 0.15
        peak = target
        if overshoot:
            extra = width / 2 + self.random.uniform(3, 12)
            peak = (
                target[0] + delta[0] / distance * extra,
                target[1] + delta[1] / distance * extra,
            )
        bend = self.random.uniform(-0.25, 0.25)
        control = (
            start[0] + delta[0] / 2 - delta[1] * bend,
            start[1] + delta[1] / 2 + delta[0] * bend,
        )
        intervals = [self.random.uniform(0.7, 1.3) for _ in range(steps)]
        total = sum(intervals)
        primary = steps - 5 if overshoot else steps
        amplitude = self.random.uniform(1, 3)
        for index, interval in enumerate(intervals, start=1):
            progress = min(1.0, index / primary)
            t = progress * progress * (3 - 2 * progress)
            x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control[0] + t**2 * peak[0]
            y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control[1] + t**2 * peak[1]
            if index > primary:
                t = (index - primary) / (steps - primary)
                t = t * t * (3 - 2 * t)
                x, y = peak[0] + (target[0] - peak[0]) * t, peak[1] + (target[1] - peak[1]) * t
            if index < steps:
                taper = min(1.0, (steps - index) / 3)
                if perlin_tremor:
                    from syntetic_core._engine.browser.sensors import perlin_value_and_rate

                    seed = self.config.seed or 0
                    x += perlin_value_and_rate(progress * 4, seed)[0] * amplitude * taper
                    y += perlin_value_and_rate(progress * 4, seed + 1)[0] * amplitude * taper
                else:
                    x += self.random.uniform(-amplitude, amplitude) * taper
                    y += self.random.uniform(-amplitude, amplitude) * taper
            else:
                x, y = target
            x, y = max(0, x), max(0, y)
            if bounds is not None:
                x, y = min(bounds[0], x), min(bounds[1], y)
            await page.mouse.move(x, y)
            self.cursor = x, y
            await sleep(duration * interval / total)

    async def scroll(self, page: Page, percent: float, *, deadline: float | None = None) -> None:
        geometry = await page.evaluate("""() => ({y: scrollY, height: innerHeight,
            max: Math.max(0, document.documentElement.scrollHeight-innerHeight)})""")
        target = geometry["max"] * percent / 100
        peak_cost = 0.0
        if self.touch:
            steps = min(
                self.config.scroll_steps if self.config.enabled else 1,
                max(1, math.ceil(abs(target - geometry["y"]) / max(1, geometry["height"] * 0.8))),
            )
            for index in range(1, steps + 1):
                step_started = monotonic()
                if deadline is not None and step_started + max(1.0, peak_cost * 2) >= deadline:
                    break
                position = geometry["y"] + (target - geometry["y"]) * index / steps
                await page.evaluate(
                    "target => window.scrollTo({top: target, behavior: 'smooth'})", position
                )
                await page.wait_for_function(
                    "target => Math.abs(scrollY-target) <= 3", arg=position, timeout=3000
                )
                if self.config.enabled and index < steps:
                    await asyncio.sleep(self.random.uniform(0.06, 0.28))
                peak_cost = max(peak_cost, monotonic() - step_started)
            else:
                return
            await page.evaluate(
                "target => window.scrollTo({top: target, behavior: 'smooth'})", target
            )
            await page.wait_for_function(
                "target => Math.abs(scrollY-target) <= 3",
                arg=target,
                timeout=max(1, (deadline - monotonic()) * 1000) if deadline is not None else 3000,
            )
            return
        current = geometry["y"]
        steps = self.config.scroll_steps
        gain = 1.0
        stalled = 0
        # Wheel acceleration differs by browser/OS. Measure actual movement and
        # converge on the requested position instead of assuming delta == pixels.
        for index in range(steps + 6):
            step_started = monotonic()
            if deadline is not None and step_started + max(1.0, peak_cost * 2) >= deadline:
                break
            remaining = target - current
            if abs(remaining) <= 3:
                break
            delta = remaining / max(1, steps - index) / gain
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(self.random.uniform(0.06, 0.18))
            new_position = await page.evaluate("scrollY")
            # Measure settled movement: Firefox smooth scrolling may continue
            # well beyond two animation frames and otherwise corrupts the gain.
            stable_samples = 0
            for _ in range(8):
                await asyncio.sleep(0.06)
                sample = await page.evaluate("scrollY")
                stable_samples = stable_samples + 1 if abs(sample - new_position) <= 0.5 else 0
                new_position = sample
                if stable_samples >= 2:
                    break
            if abs(new_position - current) > 0.5 and abs(delta) > 0.5:
                gain = min(4, max(0.25, abs((new_position - current) / delta)))
            stalled = stalled + 1 if abs(new_position - current) <= 0.5 else 0
            current = new_position
            peak_cost = max(peak_cost, monotonic() - step_started)
            if stalled >= 2:
                break
        # Linux wheel events can quantize small deltas to zero. Finish the
        # requested position with the browser's native smooth scroll animation.
        if abs(target - current) > 3:
            prefix = "mw:" if self.main_world else ""
            await page.evaluate(
                prefix + f"() => window.scrollTo({{top: {target}, behavior: 'smooth'}})"
            )
        await page.wait_for_function(
            "target => Math.abs(scrollY-target) <= 3",
            arg=target,
            timeout=min(3000, max(1, (deadline - monotonic()) * 1000))
            if deadline is not None
            else 3000,
        )


class OrganicSearchNavigator:
    """Native search interactions; the scenario owns authorization and its total budget."""

    def __init__(self, interactions: InteractionBehavior) -> None:
        self.interactions = interactions
        self.session_identifiers: dict[str, list[dict[str, str]]] = {}
        self.popup_captured = False

    async def initialize(self, page: Page, home: str) -> Response | None:
        await page.bring_to_front()
        return await page.goto(home, wait_until="domcontentloaded")

    async def capture_identifiers(self, page: Page) -> dict[str, Any]:
        """Keep native values in memory; expose only domain-scoped hashes to events."""
        self.session_identifiers = {"yandexuid": [], "_ym_uid": []}
        for cookie in await page.context.cookies(["https://ya.ru/", "https://yandex.ru/"]):
            if cookie["name"] in self.session_identifiers:
                self.session_identifiers[cookie["name"]].append(
                    {"domain": cookie["domain"], "value": cookie["value"]}
                )
        return {
            "identifiers": {
                name: [
                    {
                        "domain": item["domain"],
                        "value_hash": sha256(item["value"].encode()).hexdigest(),
                    }
                    for item in items
                ]
                for name, items in self.session_identifiers.items()
            },
            "missing": [name for name, items in self.session_identifiers.items() if not items],
        }

    async def type_query(self, field: Locator, query: str) -> None:
        await field.focus()
        await field.select_text()
        await field.press("Backspace")
        if self.interactions.touch:
            await self.interactions.type(field, query)
            return
        config = self.interactions.config
        for character in query:
            delay = self.interactions._sample_pause_ms(config.key_min_ms, config.key_max_ms)
            await field.press_sequentially(character, delay=delay)

    async def before_submit(self) -> None:
        await asyncio.sleep(self.interactions.random.uniform(0.4, 0.85))

    async def scroll_serp(self, page: Page) -> bool:
        prefix = "mw:" if self.interactions.main_world else ""
        geometry = await page.evaluate(
            prefix + "() => ({y: scrollY, max: Math.max(0, "
            "document.documentElement.scrollHeight - innerHeight)})"
        )
        before = geometry["y"]
        if before >= geometry["max"] - 1:
            return False
        step = self.interactions.random.randint(150, 350)
        if self.interactions.touch:
            await page.evaluate(prefix + "step => window.scrollBy(0, step)", step)
        else:
            await page.mouse.wheel(0, step)
        await asyncio.sleep(self.interactions.random.uniform(1, 3))
        after = await page.evaluate(prefix + "() => scrollY")
        return abs(after - before) > 0.5

    async def inspect_link(self, page: Page, link: Locator) -> None:
        prefix = "mw:" if self.interactions.main_world else ""
        while (box := await link.bounding_box()) is not None:
            height = await page.evaluate(prefix + "() => innerHeight")
            if box["y"] < height and box["y"] + box["height"] > 0:
                return
            # Inspection proceeds down the SERP; an already passed result needs no scroll.
            if box["y"] < 0 or not await self.scroll_serp(page):
                return

    async def click_result(
        self,
        page: Page,
        link: Locator,
        wait_for_navigation: Callable[[Page], Awaitable[None]],
        timeout_ms: float,
    ) -> Page:
        """Subscribe at context scope before the click; support same-tab results too."""
        self.popup_captured = False
        # Creating the expectation installs its listener synchronously, before clicking.
        expectation = page.context.expect_page(timeout=timeout_ms)

        async def wait_popup() -> Page:
            async with expectation as pending:
                return await pending.value

        popup = asyncio.create_task(wait_popup())
        navigation = asyncio.ensure_future(wait_for_navigation(page))
        try:
            await link.click(timeout=timeout_ms, no_wait_after=True)
            done, _ = await asyncio.wait({navigation, popup}, return_when=asyncio.FIRST_COMPLETED)
            if popup in done and not popup.cancelled() and popup.exception() is None:
                target = popup.result()
                if await target.opener() != page:
                    raise SearchEntryError("Search click opened an unrelated page")
                await target.bring_to_front()
                self.popup_captured = True
                return target
            await navigation
            await page.bring_to_front()
            return page
        finally:
            for task in (navigation, popup):
                if not task.done():
                    task.cancel()
            await asyncio.gather(navigation, popup, return_exceptions=True)


_VISIBILITY_GUARD = """key => {
    if (window[key]) return;
    const saved = new Map();
    const getters = new Map();
    const restoreVisibility = () => {
        for (const [name, descriptor] of saved) {
            if (Object.getOwnPropertyDescriptor(document, name)?.get !== getters.get(name))
                continue;
            if (descriptor) Object.defineProperty(document, name, descriptor);
            else delete document[name];
        }
    };
    try {
        for (const [name, value] of [['hidden', false], ['visibilityState', 'visible']]) {
            saved.set(name, Object.getOwnPropertyDescriptor(document, name));
            const get = () => value;
            getters.set(name, get);
            Object.defineProperty(document, name, {configurable: true, get});
        }
    } catch (error) {
        restoreVisibility();
        throw error;
    }
    const stop = event => event.stopImmediatePropagation();
    window.addEventListener('visibilitychange', stop, true);
    const state = {range: null, previous: [], protocol: null};
    state.clearSelection = () => {
        const selection = window.getSelection();
        if (state.range && selection && selection.rangeCount === 1 &&
            selection.getRangeAt(0) === state.range) {
            selection.removeAllRanges();
            for (const range of state.previous) {
                if (range.startContainer.isConnected && range.endContainer.isConnected)
                    selection.addRange(range);
            }
        }
        state.range = null;
        state.previous = [];
    };
    state.restore = () => {
        state.clearSelection();
        if (state.protocol) window.removeEventListener('click', state.protocol, true);
        window.removeEventListener('visibilitychange', stop, true);
        window.removeEventListener('pagehide', onPageHide);
        restoreVisibility();
        delete window[key];
    };
    // Restore before a document enters the back/forward cache as well as on final cleanup.
    const onPageHide = () => state.restore();
    window.addEventListener('pagehide', onPageHide, {once: true});
    window[key] = state;
}"""

_CONTENT_TARGET = """fraction => {
    const width = innerWidth, height = innerHeight;
    const boxes = [...document.querySelectorAll('p, span, img')].slice(0, 2000)
        .filter(element => {
            const style = getComputedStyle(element);
            return style.visibility === 'visible' && style.opacity !== '0';
        }).map(element => element.getBoundingClientRect())
        .filter(r => r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 &&
            r.left < width && r.top < height);
    const r = boxes[Math.min(boxes.length - 1, Math.floor(fraction * boxes.length))];
    const mix = 0.2 + 0.6 * fraction;
    const left = r ? Math.max(0, r.left) : 0, top = r ? Math.max(0, r.top) : 0;
    return {width, height,
        target_width: r ? r.width : 24, target_height: r ? r.height : 24,
        x: r ? left + (Math.min(width - 1, r.right) - left) * mix : width * fraction,
        y: r ? top + (Math.min(height - 1, r.bottom) - top) * (1 - mix) : height / 2};
}"""

_SELECT_TEXT = """({key, fraction}) => {
    const state = window[key], selection = window.getSelection();
    if (!state || !selection || !document.body) return false;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let node, count = 0;
    while ((node = walker.nextNode()) && count++ < 5000) {
        const parent = node.parentElement;
        if (node.textContent.trim().length < 40 || !parent ||
            parent.closest('script, style, noscript, input, textarea, [contenteditable]')) continue;
        const style = getComputedStyle(parent), r = parent.getBoundingClientRect();
        if (style.visibility !== 'visible' || style.opacity === '0' ||
            !r.width || !r.height || r.bottom <= 0 || r.top >= innerHeight ||
            r.right <= 0 || r.left >= innerWidth) continue;
        nodes.push(node);
    }
    if (!nodes.length) return false;
    node = nodes[Math.min(nodes.length - 1, Math.floor(fraction * nodes.length))];
    const range = document.createRange();
    const length = Math.min(120, node.textContent.length);
    const start = Math.floor(fraction * (node.textContent.length - length + 1));
    range.setStart(node, start);
    range.setEnd(node, start + length);
    state.previous = Array.from({length: selection.rangeCount}, (_, i) =>
        selection.getRangeAt(i).cloneRange());
    selection.removeAllRanges();
    selection.addRange(range);
    state.range = range;
    return true;
}"""


class UXActivityDispatcher:
    """Scoped synthetic UX activity; tracker accounting remains site-dependent."""

    def __init__(
        self,
        config: BehaviorConfig,
        *,
        interactions: InteractionBehavior | None = None,
        interaction_lock: asyncio.Lock | None = None,
        page_provider: Callable[[], Page] | None = None,
        allow_scroll: bool = True,
        allow_clicks: bool = True,
    ) -> None:
        self.config = config
        self.interactions = interactions or InteractionBehavior(config)
        self.random = random.Random(config.seed)
        self.lock = interaction_lock or asyncio.Lock()
        self.page_provider = page_provider
        self.allow_scroll = allow_scroll
        self.allow_clicks = allow_clicks
        self._key = "__uxActivity_" + uuid4().hex
        self._page: Page | None = None
        self._active = False
        self._running = False
        self._refresh_tasks: set[asyncio.Task[None]] = set()
        self._refresh_errors: list[BaseException] = []
        self._selection_count = 0
        self._selection_limit = self.random.randint(1, 2)
        self._down_scrolls = 0
        self._reverse_after = self.random.randint(4, 6)
        self._end = 0.0
        self._last_motion = 0.0
        self._motion_possible = allow_scroll or not self.interactions.touch
        self._wake_at = 0.0

    @property
    def enabled(self) -> bool:
        return self.config.enabled and self.config.heartbeat_enabled

    async def _evaluate(self, page: Page, expression: str, arg: Any = None) -> Any:
        return await page.evaluate(
            ("mw:" if self.interactions.main_world else "") + expression, arg
        )

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0, min(seconds, self._wake_at - asyncio.get_running_loop().time())))

    def _on_document(self, page: Page) -> None:
        if self._active and self._page is page:
            task = asyncio.create_task(self._refresh_document(page))
            self._refresh_tasks.add(task)
            task.add_done_callback(self._refresh_done)

    def _on_frame(self, frame: Frame) -> None:
        if self._page is not None and frame == self._page.main_frame:
            self._on_document(self._page)

    def _refresh_done(self, task: asyncio.Task[None]) -> None:
        self._refresh_tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self._refresh_errors.append(error)

    async def _refresh_document(self, page: Page) -> None:
        async with self.lock:
            if self._active and self._page is page and not page.is_closed():
                try:
                    await self._evaluate(page, _VISIBILITY_GUARD, self._key)
                except PlaywrightError as exc:
                    if not self._navigation_error(page, exc):
                        raise

    @staticmethod
    def _navigation_error(page: Page, exc: PlaywrightError) -> bool:
        return page.is_closed() or any(
            text in str(exc) for text in ("Execution context was destroyed", "Cannot find context")
        )

    async def _restore_page(self, page: Page) -> None:
        page.remove_listener("domcontentloaded", self._on_document)
        page.remove_listener("framenavigated", self._on_frame)
        if not page.is_closed():
            with suppress(PlaywrightError, TimeoutError):
                async with asyncio.timeout(1):
                    await self._evaluate(page, "key => window[key]?.restore()", self._key)

    async def _use_page(self, page: Page) -> None:
        if self._page is not page:
            if self._page is not None:
                await self._restore_page(self._page)
            self._page = page
            page.on("domcontentloaded", self._on_document)
            page.on("framenavigated", self._on_frame)
            await page.bring_to_front()
        await self._evaluate(page, _VISIBILITY_GUARD, self._key)

    async def _execute_smooth_micro_scroll(self, page: Page) -> bool:
        reverse = self._down_scrolls >= self._reverse_after
        delta = -self.random.uniform(10, 15) if reverse else self.random.uniform(20, 70)
        moved = await self._evaluate(
            page,
            """delta => {
            const max = Math.max(0, document.documentElement.scrollHeight - innerHeight);
            if ((delta > 0 && scrollY >= max) || (delta < 0 && scrollY <= 0)) return false;
            window.scrollBy({top: delta, behavior: 'smooth'});
            return true;
        }""",
            delta,
        )
        if moved:
            self._down_scrolls = 0 if reverse else self._down_scrolls + 1
            if reverse:
                self._reverse_after = self.random.randint(4, 6)
        return bool(moved)

    async def _execute_curved_mouse_move(self, page: Page) -> bool:
        box = await self._evaluate(page, _CONTENT_TARGET, self.random.random())
        width, height = max(1, box["width"] - 1), max(1, box["height"] - 1)
        target = (max(0, min(width, box["x"])), max(0, min(height, box["y"])))
        await self.interactions.move_to(
            page,
            target,
            (box.get("target_width", 24), box.get("target_height", 24)),
            bounds=(width, height),
            sleep=self._sleep,
        )
        self._last_motion = asyncio.get_running_loop().time()
        await self._sleep(self.random.uniform(0.5, 2.0))
        return True

    async def _execute_text_selection(self, page: Page) -> bool:
        selected = await self._evaluate(
            page, _SELECT_TEXT, {"key": self._key, "fraction": self.random.random()}
        )
        if not selected:
            return False
        self._selection_count += 1
        try:
            await self._sleep(self.random.uniform(1.5, 4.0))
        finally:
            with suppress(PlaywrightError, TimeoutError):
                async with asyncio.timeout(0.5):
                    await self._evaluate(page, "key => window[key]?.clearSelection()", self._key)
        return True

    async def _execute_checkpoint(self, page: Page) -> None:
        selector = (
            "details:not([open]) > summary, "
            'button[type="button"][role="tab"][aria-controls][aria-selected="false"], '
            'a[href^="tel:" i], a[href^="mailto:" i]'
        )
        candidates = page.locator(selector)
        indexes = await candidates.evaluate_all("""elements => elements.flatMap((element, i) => {
            const r = element.getBoundingClientRect(), style = getComputedStyle(element);
            return r.width > 0 && r.height > 0 && r.top >= 0 && r.left >= 0 &&
                r.bottom <= innerHeight && r.right <= innerWidth &&
                style.visibility === 'visible' && style.opacity !== '0' &&
                !element.disabled && element.getAttribute('aria-disabled') !== 'true' ? [i] : [];
        })""")
        if not indexes:
            return
        locator = candidates.nth(self.random.choice(indexes))
        # Cancel only the browser's protocol default; page click listeners still run.
        await self._evaluate(
            page,
            """key => {
            const state = window[key];
            state.protocol = event => {
                if (event.target instanceof Element &&
                    event.target.closest('a[href^="tel:" i], a[href^="mailto:" i]'))
                    event.preventDefault();
            };
            window.addEventListener('click', state.protocol, true);
        }""",
            self._key,
        )
        try:
            if self.interactions.touch:
                await locator.tap(timeout=1000)
            else:
                await locator.click(timeout=1000)
        except PlaywrightTimeout:
            # Optional controls can disappear or become covered after DOM sampling.
            pass
        finally:
            with suppress(PlaywrightError, TimeoutError):
                async with asyncio.timeout(0.5):
                    await self._evaluate(
                        page,
                        """key => {
                        const state = window[key];
                        if (state?.protocol) {
                            window.removeEventListener('click', state.protocol, true);
                            state.protocol = null;
                        }
                    }""",
                        self._key,
                    )

    def _choose_action(self, previous: str | None) -> str:
        actions, weights = [], []
        overdue = (
            self._motion_possible and asyncio.get_running_loop().time() - self._last_motion >= 5
        )
        for name, weight in (("scroll", 40), ("mouse_move", 35), ("select_text", 10), ("idle", 15)):
            if name == "scroll" and not self.allow_scroll:
                continue
            if name == "mouse_move" and self.interactions.touch:
                continue
            if name == "select_text" and self._selection_count >= self._selection_limit:
                continue
            if overdue and name in {"select_text", "idle"}:
                continue
            actions.append(name)
            weights.append(weight)
        if not actions:
            return "idle"
        if len(actions) > 1 and previous in actions:
            index = actions.index(previous)
            actions.pop(index)
            weights.pop(index)
        return self.random.choices(actions, weights=weights, k=1)[0]

    async def maintain_active_presence(self, page: Page, target_duration_seconds: float) -> None:
        """Run until the monotonic deadline; cancellation restores document state."""
        if not math.isfinite(target_duration_seconds) or target_duration_seconds < 0:
            raise ValueError("Presence duration must be finite and nonnegative")
        if self._running:
            raise RuntimeError("Activity dispatcher is already running")
        self._running = True
        loop = asyncio.get_running_loop()
        self._end = loop.time() + target_duration_seconds
        self._wake_at = self._end
        self._last_motion = loop.time()
        self._selection_count = 0
        self._down_scrolls = 0
        self._motion_possible = self.allow_scroll or not self.interactions.touch
        self._refresh_errors.clear()
        previous = None
        checkpoint_done = False
        budget = asyncio.timeout_at(self._end)
        try:
            async with budget:
                if not self.enabled:
                    await self._sleep(target_duration_seconds)
                    return
                self._active = True
                checkpoints = self.allow_clicks and self.config.heartbeat_checkpoints
                checkpoint_at = max(loop.time(), self._end - 3)
                self._wake_at = checkpoint_at if checkpoints else self._end
                while loop.time() < self._end:
                    if self._refresh_errors:
                        raise self._refresh_errors.pop(0)
                    current = self.page_provider() if self.page_provider else page
                    if current.is_closed():
                        return
                    try:
                        async with self.lock:
                            await self._use_page(current)
                            if checkpoints and not checkpoint_done and loop.time() >= checkpoint_at:
                                checkpoint_done = True
                                self._wake_at = self._end
                                await self._execute_checkpoint(current)
                            action = self._choose_action(previous)
                            if action == "scroll":
                                moved = await self._execute_smooth_micro_scroll(current)
                                if moved:
                                    self._motion_possible = True
                                    self._last_motion = loop.time()
                                elif not self.interactions.touch:
                                    await self._execute_curved_mouse_move(current)
                                else:
                                    self._motion_possible = False
                            elif action == "mouse_move":
                                await self._execute_curved_mouse_move(current)
                            elif action == "select_text":
                                await self._execute_text_selection(current)
                            # Idle holds no input lock so foreground steps can continue.
                        if action == "idle":
                            idle = self.random.uniform(3, 8)
                            if self._motion_possible:
                                idle = min(idle, max(0, self._last_motion + 9 - loop.time()))
                            await self._sleep(idle)
                        previous = action
                    except PlaywrightError as exc:
                        if not self._navigation_error(current, exc):
                            raise
                    delay = self.random.uniform(
                        self.config.heartbeat_min_seconds, self.config.heartbeat_max_seconds
                    )
                    if self._motion_possible:
                        delay = min(delay, max(0.05, self._last_motion + 9 - loop.time()))
                    await self._sleep(delay)
        except TimeoutError:
            if not budget.expired():
                raise
        finally:
            self._active = False
            for task in tuple(self._refresh_tasks):
                task.cancel()
            if self._refresh_tasks:
                await asyncio.gather(*self._refresh_tasks, return_exceptions=True)
            if self._page is not None:
                await self._restore_page(self._page)
            self._page = None
            self._running = False

    @asynccontextmanager
    async def background(self, page: Page, seconds: float) -> AsyncIterator[None]:
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.maintain_active_presence(page, seconds), name="ux-activity")
                yield
        except BaseExceptionGroup as errors:
            # Keep the runner's existing single-error contract for scenario failures.
            if len(errors.exceptions) == 1:
                raise errors.exceptions[0] from None
            raise


async def maintain_active_presence(page: Page, target_duration_seconds: float) -> None:
    """Convenience coroutine; schedule with create_task to run beside a scenario."""
    await UXActivityDispatcher(BehaviorConfig()).maintain_active_presence(
        page, target_duration_seconds
    )


async def execute_targeted_ux_scenario(
    page: Page,
    config: AnalyticsRoute,
    *,
    activity: UXActivityDispatcher,
    navigate: Callable[[], Awaitable[bool]],
    rng: random.Random | None = None,
) -> int:
    """Execute an assigned route and return measured, successfully reached depth."""
    rng = rng or random.SystemRandom()
    if activity.allow_clicks:
        raise ValueError("Targeted activity must disable incidental clicks")
    if config.session_behavior_pattern == "PATTERN_A":
        started = monotonic()
        try:
            # Include time already spent loading/checking this document in the bounce budget.
            async with asyncio.timeout(13):
                age = await page.evaluate(
                    ("mw:" if activity.interactions.main_world else "")
                    + """() => {
                        window.scrollBy({top: 150, behavior: 'smooth'});
                        return performance.now() / 1000;
                    }"""
                )
                observed = monotonic()
                if age >= 13:
                    raise VisitDurationExceeded("Target document exceeded the bounce budget")
                await asyncio.sleep(max(0, rng.uniform(8, 12) - age))
                if age + monotonic() - observed >= 13:
                    raise VisitDurationExceeded("Target document exceeded the bounce budget")
        finally:
            # Close before trace/diagnostic finalization can extend this target visit.
            async with asyncio.timeout(1):
                await page.close()
        if monotonic() - started >= 14:
            raise VisitDurationExceeded("Bounce session did not close within 14 seconds")
        return 1

    async def presence(seconds: float) -> None:
        current = activity.page_provider() if activity.page_provider else page
        await activity.maintain_active_presence(current, seconds)
        current = activity.page_provider() if activity.page_provider else page
        if current.is_closed():
            raise NavigationError("Target page closed during analytics activity")

    if config.session_behavior_pattern == "PATTERN_B":
        await presence(rng.uniform(30, 180))
        return 1

    depth = 1
    while depth < config.max_depth_limit:
        await presence(rng.uniform(30, 60))
        if not await navigate():
            break
        depth += 1
    await presence(rng.uniform(20, 40))
    return depth
