"""
calendar_tool.py — Tools de integração com Google Calendar.

Responsável por:
- Listar eventos do calendário
- Criar novos eventos
- Atualizar e deletar eventos
- Buscar próximos compromissos
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from loguru import logger

from backend.core.logging_config import log_tool_call


async def get_upcoming_events(max_results: int = 10) -> list[dict[str, Any]]:
    """
    Retorna os próximos eventos do Google Calendar.

    Args:
        max_results: Número máximo de eventos a retornar.

    Returns:
        Lista de eventos com data, hora e descrição.
    """
    try:
        credentials_path = os.getenv("GOOGLE_CALENDAR_CREDENTIALS_PATH")
        if not credentials_path:
            logger.warning("GOOGLE_CALENDAR_CREDENTIALS_PATH não configurado.")
            return []

        logger.info(f"Buscando próximos {max_results} eventos...")
        # TODO: Implementar integração com Google Calendar API
        return []
    except Exception as e:
        logger.error(f"Erro ao buscar eventos: {e}")
        raise


async def create_event(
    title: str,
    start_time: datetime,
    end_time: datetime,
    description: str = "",
) -> dict[str, Any]:
    """
    Cria um novo evento no Google Calendar.

    Args:
        title: Título do evento.
        start_time: Data/hora de início.
        end_time: Data/hora de término.
        description: Descrição opcional do evento.

    Returns:
        Dados do evento criado.
    """
    try:
        logger.info(f"Criando evento: {title}")
        # TODO: Implementar criação de evento via Google Calendar API
        return {"title": title, "status": "pendente"}
    except Exception as e:
        logger.error(f"Erro ao criar evento: {e}")
        raise


@log_tool_call
async def listar_eventos(max_resultados: int = 10) -> list[dict[str, Any]]:
    """Lista próximos eventos do calendário (alias em português da tool)."""
    return await get_upcoming_events(max_resultados)


@log_tool_call
async def criar_evento(
    titulo: str,
    inicio: datetime,
    fim: datetime,
    descricao: str = "",
) -> dict[str, Any]:
    """Cria um evento no calendário (alias em português da tool)."""
    return await create_event(
        title=titulo,
        start_time=inicio,
        end_time=fim,
        description=descricao,
    )
