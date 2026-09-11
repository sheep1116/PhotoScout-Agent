"""Later platforms are intentionally index-only until a stable authorized adapter exists."""


class IndexedAdapter:
    def __init__(self, name):
        self.name = name

    async def discover(self, query, client):
        return []

    async def read(self, url, client):
        return None
