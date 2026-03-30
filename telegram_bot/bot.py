"""bot.py - Bot Telegram assíncrono integrado ao backend FastAPI.

Responsável por:
- Expor comandos de suporte (/start, /status, /alarmes)
- Encaminhar texto para /conversar
- Encaminhar voz/áudio/documento para /voice
- Enviar notificações para o dono via send_notification
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from telegram import Bot, Message, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend.core.http_client import close_shared_http_clients, get_shared_http_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_ID")


def _bot_token() -> str:
    """Retorna o token do bot validado."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não encontrado no ambiente.")
    return token


async def _backend_get(endpoint: str) -> dict[str, Any]:
    """Executa um GET no backend e retorna JSON."""
    url = f"{BACKEND_BASE_URL}{endpoint}"
    client = await get_shared_http_client("telegram-backend-get", timeout=20.0)
    response = await client.get(url, timeout=20.0)
    response.raise_for_status()
    return response.json()


async def _backend_post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Executa um POST no backend e retorna JSON."""
    url = f"{BACKEND_BASE_URL}{endpoint}"
    client = await get_shared_http_client("telegram-backend-post", timeout=60.0)
    response = await client.post(url, json=payload, timeout=60.0)
    response.raise_for_status()
    return response.json()


async def send_notification(mensagem: str) -> bool:
    """Envia uma notificação para o chat do dono configurado.

    Args:
        mensagem: Texto da notificação.

    Returns:
        True se enviado com sucesso, False caso contrário.
    """
    owner_chat_id = os.getenv("TELEGRAM_OWNER_ID", OWNER_CHAT_ID or "").strip()
    if not owner_chat_id:
        owner_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not owner_chat_id:
        logger.warning(
            "TELEGRAM_OWNER_ID/TELEGRAM_CHAT_ID não configurado; notificação ignorada."
        )
        return False

    try:
        bot = Bot(token=_bot_token())
        await bot.send_message(chat_id=owner_chat_id, text=mensagem)
        return True
    except Exception as exc:
        logger.error("Erro ao enviar notificação no Telegram: {}", exc)
        return False


async def _handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler do comando /start."""
    if not update.message:
        return

    await update.message.reply_text(
        "Olá. Eu sou o Jarvis no Telegram.\n\n"
        "Comandos disponíveis:\n"
        "/status - verifica o backend\n"
        "/alarmes - lista alarmes ativos\n\n"
        "Também posso receber texto e áudio para conversar."
    )


async def _handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler do comando /status."""
    if not update.message:
        return

    try:
        data = await _backend_get("/health")
        components = data.get("components", {})
        linhas = [
            f"Status: {data.get('status', 'desconhecido')}",
            f"Versão: {data.get('version', '-')}",
            "",
            "Componentes:",
        ]
        for name, value in components.items():
            linhas.append(f"- {name}: {value}")
        await update.message.reply_text("\n".join(linhas))
    except Exception as exc:
        logger.error("Falha no /status: {}", exc)
        await update.message.reply_text(
            "Não foi possível consultar /health no backend."
        )


async def _handle_alarmes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler do comando /alarmes."""
    if not update.message:
        return

    try:
        data = await _backend_get("/agendamentos")
        alarmes = data.get("alarmes", [])
        if not alarmes:
            await update.message.reply_text("Nenhum alarme ativo no momento.")
            return

        linhas = ["Alarmes ativos:"]
        for alarme in alarmes:
            linhas.append(
                f"- ID: {alarme.get('id', '-')}, Horário: {alarme.get('horario', '-')}, "
                f"Mensagem: {alarme.get('mensagem', '-')}"
            )
        await update.message.reply_text("\n".join(linhas))
    except Exception as exc:
        logger.error("Falha no /alarmes: {}", exc)
        await update.message.reply_text(
            "Não foi possível consultar os alarmes no backend."
        )


async def _handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Encaminha mensagens de texto para /conversar."""
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()
    if not user_text:
        await update.message.reply_text("Envie uma mensagem de texto para conversar.")
        return

    session_id = f"telegram-{update.effective_chat.id}"  # type: ignore

    try:
        await update.message.chat.send_action(ChatAction.TYPING)
        data = await _backend_post(
            "/conversar",
            {"mensagem": user_text, "session_id": session_id},
        )
        resposta = data.get("resposta", "Sem resposta do assistente.")
        await update.message.reply_text(resposta)
    except Exception as exc:
        logger.error("Falha ao encaminhar texto para /conversar: {}", exc)
        await update.message.reply_text("Não consegui processar sua mensagem agora.")


async def _download_media_to_temp(message: Message) -> tuple[str | None, str | None]:
    """Baixa mídia da mensagem para arquivo temporário.

    Returns:
        Tupla (caminho, nome_original). Ambos podem ser None em caso de falha.
    """
    telegram_file = None
    original_name = "input_audio"

    if message.voice:
        telegram_file = await message.voice.get_file()
        original_name = "voice.ogg"
    elif message.audio:
        telegram_file = await message.audio.get_file()
        original_name = message.audio.file_name or "audio.mp3"
    elif message.document:
        telegram_file = await message.document.get_file()
        original_name = message.document.file_name or "document.bin"

    if not telegram_file:
        return None, None

    suffix = Path(original_name).suffix or ".bin"
    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = temp_file.name

    await telegram_file.download_to_drive(custom_path=temp_path)
    return temp_path, original_name


async def _handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Encaminha voz/áudio/documento para /voice."""
    if not update.message:
        return

    temp_path: str | None = None
    session_id = f"telegram-{update.effective_chat.id}"  # type: ignore

    try:
        temp_path, original_name = await _download_media_to_temp(update.message)
        if not temp_path:
            await update.message.reply_text("Não consegui ler o arquivo enviado.")
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        with open(temp_path, "rb") as file_obj:
            files = {
                "audio": (
                    original_name or "audio.bin",
                    file_obj,
                    "application/octet-stream",
                )
            }
            form_data = {"session_id": session_id}
            client = await get_shared_http_client(
                "telegram-backend-upload",
                timeout=180.0,
            )
            response = await client.post(
                f"{BACKEND_BASE_URL}/voice",
                files=files,
                data=form_data,
                timeout=180.0,
            )
            response.raise_for_status()
            data = response.json()

        resposta = data.get("resposta", "Sem resposta do assistente.")
        transcricao = data.get("transcricao", "")
        await update.message.reply_text(
            f"Transcrição: {transcricao}\n\nResposta: {resposta}"
        )
    except Exception as exc:
        logger.error("Falha ao encaminhar mídia para /voice: {}", exc)
        await update.message.reply_text("Não consegui processar esse arquivo de áudio.")
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Erro ao remover arquivo temporário: {}", exc)


def build_application() -> Application:
    """Constrói a aplicação do Telegram com todos os handlers."""
    application = Application.builder().token(_bot_token()).build()

    application.add_handler(CommandHandler("start", _handle_start))
    application.add_handler(CommandHandler("status", _handle_status))
    application.add_handler(CommandHandler("alarmes", _handle_alarmes))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text)
    )
    application.add_handler(
        MessageHandler(
            filters.VOICE | filters.AUDIO | filters.Document.ALL, _handle_media
        )
    )

    return application


async def start_bot() -> None:
    """Inicializa e executa o bot em polling assíncrono."""
    try:
        application = build_application()
    except Exception as exc:
        logger.error("Falha ao construir bot do Telegram: {}", exc)
        return

    logger.info("Bot do Telegram iniciando em polling")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)  # type: ignore

    try:
        await asyncio.Event().wait()
    finally:
        await application.updater.stop()  # type: ignore
        await application.stop()
        await application.shutdown()
        await close_shared_http_clients()


if __name__ == "__main__":
    asyncio.run(start_bot())
