import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.engine import Ledger
from backend.app.models import Position
from backend.app.providers import Cache, ProviderError, Providers


async def test_missing_key_is_safe(settings, brief):
    provider = Providers(settings)
    with pytest.raises(ProviderError, match="MISSING_KEY"):
        await provider.search(brief, "test")
    assert provider.calls == 0
    await provider.client.aclose()


async def test_retry_timeout_redacts_key(settings, respx_mock):
    provider = Providers(settings)
    route = respx_mock.get("https://example.com/weather").mock(side_effect=httpx.ReadTimeout("secret-leak"))
    with pytest.raises(ProviderError) as error:
        await provider.get("test", "https://example.com/weather", {"key": "secret-leak"})
    assert "secret-leak" not in str(error.value)
    assert route.call_count == 2
    await provider.client.aclose()


async def test_forecast_horizon_unknown(settings, brief):
    brief.travel_date = (datetime.now(UTC)+timedelta(days=40)).date()
    provider, ledger = Providers(settings), Ledger()
    result = await provider.weather(brief, Position(lat=32, lon=118, evidence_ids=["a"]), ledger)
    assert result[0].label == "UNKNOWN"
    assert result[0].temperature_c is None
    assert provider.calls == 0
    await provider.client.aclose()


async def test_no_citations_no_search_claims(settings, brief, respx_mock):
    settings.dashscope_api_key = "fake-test-key"
    # Assignment is not validated; instantiate SecretStr explicitly.
    from pydantic import SecretStr
    settings.dashscope_api_key = SecretStr("fake-test-key")
    content = {"output": {"choices": [{"message": {"content": [{"text": '{"candidates":[]}' }]}}]}}
    respx_mock.post(settings.dashscope_native_base_url + "/services/aigc/multimodal-generation/generation").mock(
        return_value=httpx.Response(200, text="data: " + json.dumps(content) + "\n\n"))
    provider = Providers(settings)
    with pytest.raises(ProviderError, match="NO_SOURCES"):
        await provider.search(brief, "test")
    await provider.client.aclose()


async def test_cache_expiry():
    cache = Cache()
    await cache.put("a", {"retrieved_at": "original"}, 30)
    assert (await cache.get("a"))["retrieved_at"] == "original"
    await cache.put("b", {"test": 1}, -1)
    assert await cache.get("b") is None


async def test_poi_ambiguity_is_not_first_hit(settings, respx_mock):
    from pydantic import SecretStr
    settings.amap_web_service_key = SecretStr("fake-test-key")
    respx_mock.get(settings.amap_base_url + "/v3/place/text").mock(return_value=httpx.Response(200,
        json={"status":"1", "pois":[{"name":"人民公园东区"},{"name":"人民公园西区"}]}))
    provider = Providers(settings)
    with pytest.raises(ProviderError, match="AMBIGUOUS_POI"):
        await provider.poi("人民公园", "南京")
    await provider.client.aclose()
