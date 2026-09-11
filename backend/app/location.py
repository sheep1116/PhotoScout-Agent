"""Default city suggestions only. No automatic research, no stored location history."""
import asyncio

from pydantic import BaseModel, Field

from .providers import Providers, wgs_to_gcj


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


async def locate(settings, coordinates=None):
    provider = Providers(settings)
    try:
        async with asyncio.timeout(7):
            if not settings.public_status()["amap_configured"]:
                return {"city": None, "method": "manual", "note": "地图未配置，请填写目的地。"}
            params = {"key": settings.amap_web_service_key.get_secret_value()}
            if coordinates:
                lon, lat = wgs_to_gcj(coordinates.lon, coordinates.lat)
                params.update(location=f"{lon},{lat}", extensions="base", radius=1000)
                result = await provider.get("AMap", settings.amap_base_url + "/v3/geocode/regeo", params)
                address = result.get("regeocode", {}).get("addressComponent", {})
                city = address.get("city") or address.get("province")
                method, note = "browser", "根据浏览器定位建议城市，可随时修改。"
            else:
                cached = await provider.cache.get("location:egress-city")
                if cached:
                    return cached
                result = await provider.get("AMap", settings.amap_base_url + "/v3/ip", params)
                city = result.get("city") or result.get("province")
                method, note = "ip", "网络出口 IP 推测城市；代理或远程部署可能使城市不准，请核对。"
            payload = {"city": city if isinstance(city, str) and city else None, "method": method, "note": note}
            if not coordinates:
                await provider.cache.put("location:egress-city", payload, 1800)
            return payload
    except Exception:
        return {"city": None, "method": "manual", "note": "定位暂不可用，请手动填写目的地。"}
    finally:
        await provider.client.aclose()
