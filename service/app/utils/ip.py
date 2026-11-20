"""客户端真实 IP 提取。

部署链路：客户端 -> 宝塔 nginx(443) -> 容器 nginx(80) -> uvicorn(8000)。
宝塔以覆盖式 ``proxy_set_header X-Real-IP $remote_addr`` 注入真实客户端 IP
（客户端伪造的同名头会被覆盖），容器 nginx 透传该头（见 web/nginx.conf 的 map）。
因此 ``X-Real-IP`` 是唯一不可伪造的来源，缺失时（本地直连开发环境）回退
对端地址。

``get_client_ip_from_scope`` 是同一套规则在 ASGI 层的入口，供中间件
（``app.core.guard`` 的按 IP 限流）复用——**口径只在这里维护一份**。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request


def get_client_ip_from_scope(scope: Mapping[str, Any]) -> str:
    """从 ASGI scope 取真实客户端 IP（与 ``get_client_ip`` 同一口径）。

    这是每个请求都要走的热路径，所以**命中即返回**，不把整个 header 列表
    解码成 dict（那会白白解码一堆请求头）。
    """
    for key, value in scope.get("headers") or []:
        if key.lower() == b"x-real-ip":
            xrip = value.decode("latin-1").strip()
            if xrip:
                return xrip
            break
    client = scope.get("client")
    return client[0] if client else "unknown"


def get_client_ip(request: Request) -> str:
    return get_client_ip_from_scope(request.scope)
