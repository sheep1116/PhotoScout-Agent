"""Public API discovery adapters. Photo URLs never pass through the language model."""
import asyncio
import hashlib
import html
import re
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .models import PhotoReference, TruthLabel

COMMUNITY_DOMAINS = {
    "xiaohongshu.com": "小红书", "douyin.com": "抖音", "bilibili.com": "Bilibili",
    "weibo.com": "微博", "weibo.cn": "微博", "mafengwo.cn": "马蜂窝",
    "douban.com": "豆瓣", "500px.com.cn": "500px",
}


def community_platform(url):
    host = urlsplit(url).hostname or ""
    return next((name for domain, name in COMMUNITY_DOMAINS.items()
                 if host == domain or host.endswith("." + domain)), None)


def image_url(value):
    """Only documented/trusted image CDNs, no credentials, redirects, SVG or arbitrary hosts."""
    try:
        parsed = urlsplit(str(value))
        host = parsed.hostname or ""
        allowed = host in {"store.is.autonavi.com", "aos-cdn-image.amap.com", "aos-comment.amap.com", "upload.wikimedia.org", "live.staticflickr.com"}
        allowed = allowed or bool(re.fullmatch(r"farm\d+\.staticflickr\.com", host))
        if not allowed or parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        if re.search(r"(?:key|token|secret|signature|credential)", parsed.query, re.I):
            return None
        return urlunsplit(("https", host, parsed.path, parsed.query, ""))
    except (ValueError, TypeError):
        return None


def plain(value):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))[:300]


def reference(ledger, provider, url, source_url, title, **metadata):
    url = image_url(url)
    parsed_source = urlsplit(source_url)
    if parsed_source.hostname not in ("www.amap.com", "commons.wikimedia.org", "www.flickr.com") or parsed_source.username or parsed_source.password:
        return None
    source_url = urlunsplit(("https", parsed_source.hostname, parsed_source.path, "", ""))
    if not url:
        return None
    identity = "photo-" + hashlib.sha256((provider + url).encode()).hexdigest()[:20]
    ids = ledger.add(identity, f"{provider} · {plain(title)}", TruthLabel.REPORTED,
                     "真实图片接口返回；图片可能较旧，不能证明当前季节、开放或精确摄影站位。",
                     {"provider": provider, "relation": metadata.get("relation", "poi")}, source_url)
    return PhotoReference(id=identity, provider=provider, image_url=url, source_url=source_url,
                          source_id=ledger.evidence[-1].source_id, title=plain(title), evidence_ids=ids, **metadata)


class PhotoProvider(Protocol):
    name: str

    async def discover(self, spot, ledger, network) -> list[PhotoReference]: ...


class AMapPhotos:
    name = "amap"

    @staticmethod
    def from_poi(poi, ledger):
        result = []
        for photo in (poi.get("photos") or [])[:4]:
            if not isinstance(photo, dict):
                continue
            item = reference(ledger, "amap", photo.get("url"),
                             "https://www.amap.com/place/" + str(poi["id"]),
                             photo.get("title") or poi["name"])
            if item and item.id not in {p.id for p in result}:
                result.append(item)
        return result


class WikimediaPhotos:
    name = "wikimedia"

    async def discover(self, spot, ledger, network):
        # Geographic results are explicitly NEARBY, never asserted to show this exact viewpoint.
        data = await network.get("Wikimedia", "https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json", "generator": "geosearch", "ggsnamespace": 6,
            "ggscoord": f"{spot.camera.lat}|{spot.camera.lon}", "ggsradius": 500, "ggslimit": 3,
            "prop": "imageinfo|coordinates", "iiprop": "url|extmetadata|mime", "iiurlwidth": 960,
            "iiextmetadatafilter": "Artist|LicenseShortName|DateTimeOriginal", "colimit": "max"})
        result = []
        for page in data.get("query", {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
                continue
            meta = info.get("extmetadata", {})
            def field(key):
                return plain(meta.get(key, {}).get("value", ""))
            coords = (page.get("coordinates") or [{}])[0]
            source_url = info.get("descriptionurl", "")
            if urlsplit(source_url).hostname != "commons.wikimedia.org":
                continue
            item = reference(ledger, self.name, info.get("thumburl") or info.get("url"), source_url,
                             page.get("title", "Wikimedia 参考图"), relation="nearby",
                             author=field("Artist") or "未提供", license=field("LicenseShortName") or "请查阅来源页授权",
                             captured_at=field("DateTimeOriginal") or None,
                             latitude=coords.get("lat"), longitude=coords.get("lon"))
            if item:
                result.append(item)
        return result


class FlickrPhotos:
    name = "flickr"

    async def discover(self, spot, ledger, network):
        key = network.settings.flickr_api_key.get_secret_value()
        if not key or key.startswith("your_"):
            return []
        data = await network.get("Flickr", "https://www.flickr.com/services/rest/", {
            "method": "flickr.photos.search", "api_key": key, "format": "json", "nojsoncallback": 1,
            "lat": spot.camera.lat, "lon": spot.camera.lon, "radius": .5, "radius_units": "km",
            "safe_search": 1, "content_types": 0, "media": "photos", "per_page": 3,
            "extras": "owner_name,license,date_taken,geo,url_z", "license": "4,5"})
        if data.get("stat") == "fail":
            from .providers import ProviderError
            raise ProviderError("Flickr", "API_FAILED")
        result = []
        for photo in data.get("photos", {}).get("photo", []):
            if not re.fullmatch(r"[\w@-]+", str(photo.get("owner", ""))) or not str(photo.get("id", "")).isdigit():
                continue
            item = reference(ledger, self.name, photo.get("url_z"),
                             f"https://www.flickr.com/photos/{photo['owner']}/{photo['id']}",
                             photo.get("title", "Flickr 参考图"), relation="nearby",
                             author=plain(photo.get("ownername")) or "未提供",
                             license={"4": "CC BY 2.0", "5": "CC BY-SA 2.0"}.get(str(photo.get("license")), "请查阅来源页授权"),
                             captured_at=photo.get("datetaken"), latitude=photo.get("latitude"), longitude=photo.get("longitude"))
            if item:
                # Public EXIF is optional; never turn an unavailable EXIF into a made-up camera setting.
                if not result:
                    try:
                        exif = await network.get("Flickr", "https://www.flickr.com/services/rest/", {
                            "method": "flickr.photos.getExif", "api_key": key, "photo_id": photo["id"],
                            "format": "json", "nojsoncallback": 1})
                        item.exif = {plain(e.get("label")): plain(e.get("raw", {}).get("_content"))
                                     for e in exif.get("photo", {}).get("exif", [])
                                     if e.get("tag") in ("Model", "LensModel", "FocalLength", "FNumber", "ExposureTime", "ISO")}
                    except Exception:
                        pass
                result.append(item)
        return result


class CommunityDiscovery:
    """Search-index discovery only: no login bypass, scraping or invented community APIs."""
    purposes = ["site:bilibili.com 摄影机位 拍摄位置 焦段 朝向 光线 构图经验",
                "摄影机位 拍摄位置 构图 攻略 景区官方介绍"]

    async def discover(self, brief, network, warnings):
        from .providers import ProviderError
        batches = []
        for purpose in self.purposes[:network.settings.max_search_calls]:
            # A restricted platform must not consume the useful discovery path.
            # Keep the same two-call ceiling, but broaden the search index when
            # anonymous Bilibili metadata is unavailable.
            status = getattr(getattr(network, "community", None), "status", {}).get("bilibili", "")
            if purpose.startswith("site:bilibili.com") and not status.startswith(("ok", "public_metadata_ok")):
                purpose = "摄影机位 拍摄位置 朝向 光线 构图经验"
            try:
                batches.append(await network.search(brief, purpose))
            except ProviderError as error:
                warnings.append(str(error))
        return batches


class DiscoveryHub:
    providers: tuple[PhotoProvider, ...] = (WikimediaPhotos(), FlickrPhotos())

    async def enrich(self, spots, ledger, network, warnings):
        if not spots:
            return
        if not network.settings.enable_external_photos:
            warnings.append("Wikimedia / Flickr 外部图片发现已关闭；高德图片仍可用。")
            return
        for provider in self.providers:
            if provider.name == "flickr" and not network.settings.public_status()["flickr_configured"]:
                warnings.append("Flickr：未配置 API Key，本次跳过；可在服务端配置 FLICKR_API_KEY。")
                continue
            count = 0
            try:
                # One bounded provider budget for the whole plan, not a timeout per photo.
                async with asyncio.timeout(network.settings.discovery_photo_timeout):
                    for spot in spots[:3]:
                        photos = await provider.discover(spot, ledger, network)
                        known = {p.id for p in spot.photo_references}
                        spot.photo_references.extend(p for p in photos if p.id not in known)
                        count += len(photos)
                warnings.append(f"{provider.name}：本次发现 {count} 张附近参考图；不等于精确机位样片。")
            except Exception:
                warnings.append(f"{provider.name}：图片服务不可用或响应无效，已保留其他来源。")
