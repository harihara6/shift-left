"""One place that opens outbound HTTP clients, so tests can stand a fake system in for a real one.

Every live reader and writer calls `client()`. A test sets `transport` to an `httpx.MockTransport`
and the whole flow runs against it; nothing else in the code knows it happened.
"""

import httpx

# Set only by tests. Production code never assigns it.
transport: httpx.AsyncBaseTransport | None = None


def client(timeout: float = 20.0, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=transport, **kwargs)
