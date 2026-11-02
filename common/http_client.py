import xml.etree.ElementTree as _ET

import httpx

try:
    from lxml.etree import XMLSyntaxError as _XmlError
except ImportError:
    _XmlError = _ET.ParseError

# fetch + parse 묶음 재시도 대상 예외 타입 (law_detail.py에서 사용)
RETRYABLE = (httpx.RequestError, httpx.HTTPStatusError, _ET.ParseError, _XmlError)


_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/xml,application/xml,*/*;q=0.8',
}


def make_async_client(verify_ssl: bool = True, timeout: int = 30) -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    return httpx.AsyncClient(verify=verify_ssl, timeout=timeout, follow_redirects=True, headers=_HEADERS, limits=limits)


async def fetch_xml(client: httpx.AsyncClient, url: str) -> bytes:
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.content
