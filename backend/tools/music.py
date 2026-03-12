"""
music.py — Tools de controle de música.

Responsável por:
- Integração com Spotify API
- Controle de reprodução (play, pause, skip)
- Busca de músicas e playlists
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger


async def play_music(query: str) -> dict[str, Any]:
    """
    Busca e reproduz uma música via Spotify.

    Args:
        query: Nome da música, artista ou playlist.

    Returns:
        Informações sobre a música sendo reproduzida.
    """
    try:
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

        if not client_id or not client_secret:
            logger.warning("Credenciais do Spotify não configuradas.")
            return {"error": "Spotify não configurado"}

        logger.info(f"Buscando música: {query}")
        # TODO: Implementar integração com Spotify API
        return {"query": query, "status": "pendente"}
    except Exception as e:
        logger.error(f"Erro ao reproduzir música: {e}")
        raise


async def get_current_track() -> dict[str, Any] | None:
    """
    Retorna informações sobre a música atualmente em reprodução.

    Returns:
        Dados da música atual ou None se nada estiver tocando.
    """
    try:
        # TODO: Implementar via Spotify API
        return None
    except Exception as e:
        logger.error(f"Erro ao obter música atual: {e}")
        raise
