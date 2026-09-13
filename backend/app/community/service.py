import asyncio
import hashlib
from urllib.parse import urlsplit, urlunsplit

from ..discovery import image_url
from ..models import Evidence, PhotoReference, TruthLabel, WebSource
from .bilibili import BilibiliAdapter
from .indexed import IndexedAdapter


class CommunityService:
    def __init__(self):
        self.adapters = (BilibiliAdapter(), IndexedAdapter("xiaohongshu"), IndexedAdapter("douyin"))
        self.posts = {}
        self.status = {}

    async def discover(self, brief, network):
        if not network.settings.enable_community:
            self.status = {"bilibili": "disabled", "xiaohongshu": "index_only", "douyin": "index_only"}
            return []
        for adapter in self.adapters:
            if isinstance(adapter, IndexedAdapter):
                self.status[adapter.name] = "index_only"
                continue
            key = "community:v1:" + hashlib.sha256((adapter.name + brief.destination).encode()).hexdigest()
            cached = await network.cache.get(key)
            if cached:
                from .base import CommunityPost
                for item in cached["posts"]:
                    post = CommunityPost.model_validate(item)
                    self.posts[post.url] = post
                self.status[adapter.name] = cached["status"] + "_cached"
                continue
            found = []
            try:
                async with asyncio.timeout(6):
                    network.calls += 1
                    found = await adapter.discover(brief.destination + " 摄影机位 构图", network.client)
                self.status[adapter.name] = "ok" if found else "empty"
            except Exception:
                self.status[adapter.name] = "restricted_or_unavailable"
            for post in found:
                self.posts[post.url] = post
            await network.cache.put(key, {"posts": [p.model_dump(mode="json") for p in found],
                                        "status": self.status[adapter.name]}, 1800)
        return list(self.posts.values())

    async def enrich_indexed(self, batches, network, ledger, warnings):
        """At most three Bilibili videos discovered through the existing search index."""
        adapter = self.adapters[0]
        urls = list(dict.fromkeys(str(s.get("url", "")) for b in batches for s in b["sources"]
                                 if "bilibili.com/video/BV" in str(s.get("url", ""))))[:3]
        if network.settings.enable_community:
            for url in urls:
                try:
                    async with asyncio.timeout(6):
                        network.calls += 1
                        post = await adapter.read(url, network.client)
                    if post:
                        self.posts[post.url] = post
                        self.status["bilibili"] = "public_metadata_ok"
                except Exception:
                    # Keep source-indexed search evidence even if direct metadata is unavailable.
                    self.status.setdefault("bilibili", "index_fallback")
                    break
        for post in self.posts.values():
            sid = "community-" + hashlib.sha256(post.url.encode()).hexdigest()[:16]
            if any(s.id == sid for s in ledger.sources):
                continue
            ledger.sources.append(WebSource(id=sid, url=post.url, title=post.title, publisher=post.platform,
                platform=post.platform, kind="community", published_at=post.published_at,
                note="公开标题与简介，不含视频转录；摄影经验是待核验线索，不证明开放或安全。"))
            ledger.evidence.append(Evidence(id="ev-" + sid, source_id=sid, label=TruthLabel.REPORTED,
                statement=(post.title + "：" + post.description)[:2000],
                values={"platform": post.platform, "photographic_info": post.photographic_info,
                        "published_at": post.published_at.isoformat() if post.published_at else None,
                        "retrieval": post.retrieval}))
        for platform, status in self.status.items():
            warnings.append(f"社区 {platform}：{status}；仅作摄影线索，平台不可用不阻断其他来源。")

    def photo_references(self, urls, ledger):
        """Turn trusted public post covers into attributed reference samples.

        Only posts already linked to the retained camera candidate are eligible;
        the image remains a source preview, never proof of an exact viewpoint.
        """
        normalized = {self._normalized_url(url) for url in urls}
        result = []
        for post in self.posts.values():
            if self._normalized_url(post.url) not in normalized:
                continue
            safe_image = image_url(post.cover_image_url)
            if not safe_image:
                continue
            source = next((source for source in ledger.sources
                           if source.url and self._normalized_url(str(source.url)) == self._normalized_url(post.url)), None)
            if not source:
                continue
            identity = "photo-community-" + hashlib.sha256((post.url + safe_image).encode()).hexdigest()[:16]
            evidence_id = "ev-" + identity
            if not any(evidence.id == evidence_id for evidence in ledger.evidence):
                ledger.evidence.append(Evidence(id=evidence_id, source_id=source.id, label=TruthLabel.REPORTED,
                    statement="来源页面的公开封面/预览图；可作为构图参考，但不证明精确站位、拍摄参数或当前现场条件。",
                    values={"platform": post.platform, "relation": "source", "author": post.author or None}))
            result.append(PhotoReference(id=identity, provider="community", image_url=safe_image,
                source_url=post.url, source_id=source.id, title=post.title,
                author=post.author or "未提供",
                license="来源平台公开预览图；版权归原作者，使用与转载请查看原文",
                captured_at=post.published_at.isoformat() if post.published_at else None,
                relation="source", evidence_ids=[evidence_id]))
            if len(result) >= 3:
                break
        return result

    @staticmethod
    def _normalized_url(value):
        parsed = urlsplit(str(value))
        return urlunsplit(("https", (parsed.hostname or "").lower(), parsed.path.rstrip("/"), "", ""))

    def sources(self):
        return [{"index": 1001+i, "url": post.url, "title": post.title,
                 "published_at": post.published_at.isoformat() if post.published_at else None,
                 "description": post.description, "photographic_info": post.photographic_info}
                for i, post in enumerate(self.posts.values())]
