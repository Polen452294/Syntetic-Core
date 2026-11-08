import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from syntetic_core._engine.browser.factory import native_client_hint_identity
from syntetic_core._engine.errors import ProfileValidationError


async def test_reference_context_is_closed_after_reading_local_page():
    brands = {"brands": [], "fullVersionList": [], "fullVersion": "123.0.0.0"}
    page = SimpleNamespace(goto=AsyncMock(), evaluate=AsyncMock(return_value=brands))
    reference = SimpleNamespace(
        route=AsyncMock(), new_page=AsyncMock(return_value=page), close=AsyncMock()
    )
    browser = SimpleNamespace(new_context=AsyncMock(return_value=reference))

    assert await native_client_hint_identity(SimpleNamespace(browser=browser)) == brands
    browser.new_context.assert_awaited_once_with()
    reference.route.assert_not_awaited()
    page.goto.assert_awaited_once()
    assert page.goto.call_args.args[0].startswith("file:")
    reference.close.assert_awaited_once_with()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_reference_context_is_closed_when_reading_fails(error_type):
    page = SimpleNamespace(goto=AsyncMock(side_effect=error_type))
    reference = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock())
    browser = SimpleNamespace(new_context=AsyncMock(return_value=reference))

    with pytest.raises(error_type):
        await native_client_hint_identity(SimpleNamespace(browser=browser))
    reference.close.assert_awaited_once_with()


async def test_reference_context_requires_a_live_browser():
    with pytest.raises(ProfileValidationError, match="browser is unavailable"):
        await native_client_hint_identity(SimpleNamespace(browser=None))
