"""Clientes HTTP compartilhados para reduzir overhead de conexão."""

from __future__ import annotations

import asyncio

import httpx
from loguru import logger

_CLIENTS: dict[str, httpx.AsyncClient] = {}
_CLIENTS_LOCK = asyncio.Lock()
_DEFAULT_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=100,
)


async def get_shared_http_client(
    name: str,
    *,
    timeout: float = 30.0,
) -> httpx.AsyncClient:
    """
    Retorna um AsyncClient compartilhado por nome.

    Args:
        name: Identificador lógico do cliente.
        timeout: Timeout padrão do cliente.

    Returns:
        Instância compartilhada de httpx.AsyncClient.
    """
    async with _CLIENTS_LOCK:
        client = _CLIENTS.get(name)
        if client is not None and not client.is_closed:
            return client

        client = httpx.AsyncClient(timeout=timeout, limits=_DEFAULT_LIMITS)
        _CLIENTS[name] = client
        return client


async def close_shared_http_clients() -> None:
    """Fecha todos os clients HTTP compartilhados do processo atual."""
    async with _CLIENTS_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()

    for client in clients:
        try:
            await client.aclose()
        except Exception as exc:
            logger.warning("Erro ao fechar http client compartilhado: {}", exc)
