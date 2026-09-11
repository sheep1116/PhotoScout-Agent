import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .base import CommunityPost, CommunityUnavailable, clean, photographic_info


class BilibiliAdapter:
    name = "bilibili"

    async def request(self, client, path, params):
        # Anonymous public metadata only; no cookies, signature reverse engineering, proxies or CAPTCHA bypass.
        response = await client.get("https://api.bilibili.com" + path, params=params,
                                    headers={"Referer": "https://www.bilibili.com/"}, timeout=5)
        if response.status_code != 200:
            raise CommunityUnavailable("HTTP_" + str(response.status_code))
        data = response.json()
        if data.get("code") != 0:
            raise CommunityUnavailable("ACCESS_RESTRICTED")
        return data.get("data") or {}

    def post(self, data):
        bvid = str(data.get("bvid", ""))
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
            return None
        title = clean(data.get("title"), 250)
        description = clean(data.get("desc") or data.get("description"))
        published = None
        stamp = data.get("pubdate")
        if isinstance(stamp, (float, int)) and 0 < stamp < 4102444800:
            published = datetime.fromtimestamp(stamp, UTC)
        return CommunityPost(platform=self.name, url=f"https://www.bilibili.com/video/{bvid}",
            title=title, description=description, published_at=published,
            photographic_info=photographic_info(title + " " + description))

    async def discover(self, query, client):
        data = await self.request(client, "/x/web-interface/search/type",
            {"search_type": "video", "keyword": query, "page": 1, "page_size": 3})
        return [p for item in (data.get("result") or [])[:3] if (p := self.post(item))]

    async def read(self, url, client):
        parsed = urlsplit(url)
        if parsed.hostname not in ("www.bilibili.com", "bilibili.com"):
            return None
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10})/?", parsed.path)
        if not match:
            return None
        data = await self.request(client, "/x/web-interface/view", {"bvid": match[1]})
        return self.post(data)
