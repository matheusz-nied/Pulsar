"""Script para iniciar o bot do Telegram em processo separado."""

from __future__ import annotations

import asyncio

from telegram_bot.bot import start_bot


if __name__ == "__main__":
    asyncio.run(start_bot())
