import json
from typing import cast

from aiohttp import ClientResponse
from requests import Response


class AsyncResponse:
    @staticmethod
    async def build(response: ClientResponse | None):
        if response is None:
            return None
        return AsyncResponse(status=response.status, text=await response.text(), headers=response.headers,
                             url=str(response.url))

    def __init__(self, *, status: int, text: str, headers: dict, url: str):
        self.status = status
        self._text = text
        self.headers = headers
        self.url = url

    def text(self):
        return self._text

    def json(self):
        return json.loads(self._text)

    def __repr__(self):
        return f'AsyncResponse(status={self.status}, text={self._text})'


class SyncResponse:
    @staticmethod
    def build(response: Response | None):
        if response is None:
            return None
        return SyncResponse(status=response.status_code, text=response.text, headers=cast(dict, response.headers),
                            url=response.url)

    def __init__(self, *, status: int, text: str, headers: dict, url: str):
        self.status = status
        self._text = text
        self.headers = headers
        self.url = url

    def text(self):
        return self._text

    def json(self):
        return json.loads(self._text)

    def __repr__(self):
        return f'SyncResponse(status={self.status}, text={self._text})'
