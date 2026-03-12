"""
bot.py — Bot do Telegram para o Assistente Virtual.

Responsável por:
- Receber mensagens do Telegram
- Encaminhar para o agente e retornar respostas
- Gerenciar comandos especiais (/start, /help, etc.)
"""

from __future__ import annotations

import os

from loguru import logger


async def start_bot() -> None:
    """
    Inicializa e executa o bot do Telegram.

    Requer TELEGRAM_BOT_TOKEN no .env.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN não encontrado no .env")
        return

    logger.info("🤖 Bot do Telegram iniciando...")
    # TODO: Implementar bot com python-telegram-bot ou aiogram
