import asyncio
import hashlib

from ..models import Evidence, TruthLabel, WebSource
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

    def sources(self):
        return [{"index": 1001+i, "url": post.url, "title": post.title,
                 "published_at": post.published_at.isoformat() if post.published_at else None,
                 "description": post.description, "photographic_info": post.photographic_info}
                for i, post in enumerate(self.posts.values())]
