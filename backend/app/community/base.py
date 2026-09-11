import html
import re
from datetime import datetime
from typing import Protocol

from pydantic import Field

from ..models import Model


class CommunityPost(Model):
    platform: str
    url: str
    title: str
    description: str = ""
    published_at: datetime | None = None
    photographic_info: dict[str, list[str]] = Field(default_factory=dict)
    retrieval: str = "public_metadata"


class CommunityAdapter(Protocol):
    name: str
    async def discover(self, query: str, client) -> list[CommunityPost]: ...
    async def read(self, url: str, client) -> CommunityPost | None: ...


class CommunityUnavailable(Exception):
    pass


def clean(value, limit=1800):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))[:limit]


def photographic_info(text):
    """Only retain literal terms present in public metadata; no made-up camera settings."""
    patterns = {
        "focal_lengths": r"\b\d{1,3}(?:[-–]\d{1,3})?\s?mm\b",
        "time_light": r"日出|日落|蓝调|黄金时刻|逆光|侧光|顺光|夜景|清晨|傍晚",
        "composition": r"倒影|引导线|对称|框架构图|前景|长焦压缩|广角|剪影",
    }
    return {key: list(dict.fromkeys(re.findall(pattern, text, re.I)))[:8] for key, pattern in patterns.items()}
