"""
agent.py — Orquestrador principal do agente com LangGraph.

Responsável por:
- Definir o grafo de estados do agente (LangGraph)
- Rotear mensagens do usuário para as tools corretas
- Gerenciar o loop de conversação com o Claude API
- Integrar memória de curto e longo prazo
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger


async def process_message(user_input: str) -> str:
    """
    Processa uma mensagem do usuário e retorna a resposta do agente.

    Args:
        user_input: Texto enviado pelo usuário.

    Returns:
        Resposta gerada pelo agente.
    """
    try:
        logger.info(f"Processando mensagem: {user_input[:50]}...")
        # TODO: Implementar integração com LangGraph + Claude API
        return f"Echo: {user_input}"
    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}")
        raise
