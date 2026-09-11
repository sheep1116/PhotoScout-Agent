"""Resolve user choices before discovery; stable records come only from AMap."""
from uuid import uuid4

from .models import DestinationLocation
from .providers import gcj_to_wgs

AMBIGUOUS_NAMES = {"鼓楼", "中山公园", "西湖", "老街"}


def text(value):
    return value if isinstance(value, str) else ""


async def choices(query, network):
    key = "destination:v1:" + query
    cached = await network.cache.get(key)
    if cached:
        return [DestinationLocation.model_validate(v) for v in cached]
    params = {"key": network.settings.amap_web_service_key.get_secret_value()}
    if not params["key"]:
        return []
    geo = await network.get("AMap", network.settings.amap_base_url+"/v3/geocode/geo", {**params, "address": query})
    records = []
    for item in geo.get("geocodes", [])[:5]:
        if not item.get("location") or not item.get("adcode"):
            continue
        lon, lat = gcj_to_wgs(*map(float, item["location"].split(",")))
        name = text(item.get("formatted_address")) or query
        records.append(DestinationLocation(id="geo-"+item["adcode"]+"-"+name, adcode=item["adcode"],
            name=name, city=text(item.get("city")) or text(item.get("province")), lat=lat, lon=lon))
    if len(records) != 1 or query in AMBIGUOUS_NAMES:
        data = await network.get("AMap", network.settings.amap_base_url+"/v3/place/text",
                                 {**params, "keywords": query, "offset": 8, "extensions": "base"})
        for item in data.get("pois", [])[:8]:
            if not item.get("location") or not item.get("id") or not item.get("adcode"):
                continue
            lon, lat = gcj_to_wgs(*map(float, item["location"].split(",")))
            name = text(item.get("name"))
            city = text(item.get("cityname")) or text(item.get("pname"))
            records.append(DestinationLocation(id=item["id"], poi_id=item["id"], adcode=item["adcode"],
                name=name, city=city, address=text(item.get("address")), lat=lat, lon=lon))
    unique = {r.id: r for r in records}
    result = list(unique.values())[:10]
    for item in result:
        item.verification_token = uuid4().hex
        await network.cache.put("destination-choice:"+item.verification_token, item.model_dump(mode="json"), 3600)
    if result:
        await network.cache.put(key, [r.model_dump(mode="json") for r in result], 1800)
    return result


async def resolve_notebook(book, network):
    brief = book.brief
    if brief.mode != "live" or not brief.destination:
        return book
    if brief.location:
        stored = await network.cache.get("destination-choice:"+brief.location.verification_token)
        if stored and stored == brief.location.model_dump(mode="json"):
            book.location_status = "confirmed"
            return book
        brief.location = None
    try:
        options = await choices(brief.destination, network)
    except Exception:
        options = []
    if len(options) == 1 and brief.destination not in AMBIGUOUS_NAMES:
        brief.location = options[0]
        book.location_status = "resolved"
    else:
        book.location_choices = options
        book.location_status = "needs_choice" if options else "unavailable"
        book.questions.append("请选择你指的地点后继续。" if options else "地点查询暂不可用或没有匹配，请补充城市后重试。")
    return book
