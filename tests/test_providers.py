import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.engine import Ledger
from backend.app.models import Position
from backend.app.providers import Cache, ProviderError, Providers, source_mentions_location


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


async def test_search_repeated_frames_dedup_and_usage_sums(settings, brief, respx_mock):
    from pydantic import SecretStr
    settings.dashscope_api_key = SecretStr("stream-test-key")
    source = {"index": 1, "url": "https://example.com/source", "title": "source"}
    pieces = ['{"candidates":', '[]}']
    frames = [{"output": {"search_info": {"search_results": [source]}, "choices": [
        {"message": {"content": [{"text": part}]}}]}, "usage": {"total_tokens": count}}
        for part, count in zip(pieces, [10, 20])]
    route = respx_mock.post(settings.dashscope_native_base_url
        + "/services/aigc/multimodal-generation/generation").mock(return_value=httpx.Response(200,
        text="".join("data: " + json.dumps(frame) + "\n\n" for frame in frames)))
    provider = Providers(settings)
    try:
        first = await provider.search(brief, "stream-dedup-one")
        assert len(first["sources"]) == 1
        await provider.search(brief, "stream-dedup-two")
        assert provider.tokens == 40
        assert provider.search_calls == route.call_count == 2
        await provider.search(brief, "stream-dedup-two")
        assert provider.tokens == 40
        assert provider.search_cache_hits == 1
        assert route.call_count == 2
    finally:
        await provider.client.aclose()


@pytest.mark.parametrize("query,names,expected", [
    ("鱼嘴湿地公园", ["南京鱼嘴湿地公园1号停车场", "南京鱼嘴湿地公园"], "南京鱼嘴湿地公园"),
    ("中山陵", ["中山陵南广场", "中山陵景区"], "中山陵景区"),
    ("先锋书店（五台山店）", ["先锋书店(五台山总店)", "先锋书店(五台山总店)-文字墙"], "先锋书店(五台山总店)"),
    ("老门东街区", ["老门东-步行街", "老门东"], "老门东"),
    ("人民公园", ["人民公园东区"], None),
    ("人民公园", ["人民公园", "人民公园"], None),
])
async def test_poi_aliases_keep_distinct_places_ambiguous(settings, respx_mock, query, names, expected):
    respx_mock.get(settings.amap_base_url + "/v3/place/text").mock(return_value=httpx.Response(200,
        json={"status": "1", "pois": [{"name": n} for n in names]}))
    provider = Providers(settings)
    try:
        if expected:
            assert (await provider.poi(query, "南京市"))["name"] == expected
        else:
            with pytest.raises(ProviderError, match="AMBIGUOUS_POI"):
                await provider.poi(query, "南京市")
    finally:
        await provider.client.aclose()


async def test_amap_business_rate_limit_retries_and_redacts(settings, respx_mock):
    route = respx_mock.get(settings.amap_base_url + "/v3/place/text").mock(side_effect=[
        httpx.Response(200, json={"status": "0", "infocode": "10021", "info": "secret-not-for-output"}),
        httpx.Response(200, json={"status": "1", "pois": [{"name": "玄武湖"}]})])
    provider = Providers(settings)
    try:
        assert (await provider.poi("玄武湖", "南京市"))["name"] == "玄武湖"
        assert route.call_count == 2
        route.mock(return_value=httpx.Response(200,
            json={"status": "0", "infocode": "10001", "info": "secret-not-for-output"}))
        with pytest.raises(ProviderError, match="API_10001") as error:
            await provider.poi("玄武湖", "南京市")
        assert "secret-not-for-output" not in str(error.value)
    finally:
        await provider.client.aclose()


@pytest.mark.parametrize("title,expected", [
    ("10种基本摄影构图方法", False),
    ("重庆摄影学校场景解析", False),
    ("南京旅行拍照地点攻略", True),
    ("玄武湖公园游览指南", True),
])
def test_source_location_relevance(title, expected):
    assert source_mentions_location(title, "玄武湖公园", "南京市") is expected
