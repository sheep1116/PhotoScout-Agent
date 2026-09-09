"""Conservative claim verification: quality is not permission, retrieval is not publication."""
from datetime import datetime

from .models import SourceClaim, TruthLabel, WebSource


def resolve_access(claims: list[SourceClaim], sources: list[WebSource], at: datetime):
    indexed = {s.id: s for s in sources}
    fresh = [c for c in claims if c.kind in ("access", "safety") and c.source_id in indexed
             and indexed[c.source_id].kind == "official" and c.valid_until and c.valid_until >= at
             and c.label == TruthLabel.VERIFIED]
    closed = any("CLOSED" in c.statement for c in fresh)
    opened = any("OPEN" in c.statement for c in fresh)
    if closed and opened:
        return "CONFLICT"
    if closed:
        return "CLOSED"
    if opened:
        return "OPEN"
    return "UNKNOWN"


def popularity(claims, sources, at):
    from urllib.parse import urlsplit
    indexed = {s.id: s for s in sources}
    independent = set()
    community = set()
    for claim in claims:
        source = indexed.get(claim.source_id)
        if not source or not source.url or not source.published_at:
            continue
        if not 0 <= (at - source.published_at).days <= 90:
            continue
        if claim.label not in (TruthLabel.REPORTED, TruthLabel.VERIFIED):
            continue
        host = urlsplit(str(source.url)).hostname or ""
        # Conservative publisher identifier; same publisher counts once.
        identity = source.publisher or host
        independent.add(identity)
        if source.kind == "community":
            community.add(identity)
    if len(community) >= 2:
        return "COMMUNITY_POPULAR"
    if len(independent) >= 2:
        return "MULTI_SOURCE_POPULAR"
    if independent:
        return "SINGLE_SOURCE_MENTION"
    return "UNVERIFIED"
