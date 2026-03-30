"""
music.py — Controle de música via YouTube Music usando ytmusicapi + Brave.

Responsável por:
- Buscar músicas via API do YouTube Music
- Abrir músicas no Brave (já logado)
- Controlar reprodução via teclas do sistema
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

from backend.core.logging_config import log_tool_call


class YoutubeMusicController:
    """Controla o YouTube Music via API + Brave browser."""

    BASE_URL = "https://music.youtube.com"
    _yt = None

    def __init__(self) -> None:
        """Inicializa o controlador."""
        self._browser_aberto: bool = False

    def _get_yt(self):
        """Lazy init do cliente ytmusicapi."""
        if self._yt is None:
            from ytmusicapi import YTMusic

            # Usa headers extraídos do Brave
            headers_file = Path.home() / ".config" / "pulsar-ytmusic" / "headers.json"

            if headers_file.exists():
                self._yt = YTMusic(str(headers_file))
                logger.info("ytmusicapi autenticado via headers do Brave")
            else:
                # Modo sem autenticação (busca limitada)
                self._yt = YTMusic()
                logger.warning(
                    "ytmusicapi sem autenticação. Execute scripts/setup_ytmusic_cookies.py"
                )

        return self._yt

    async def _run_exec(self, *args: str) -> None:
        """Executa um comando sem bloquear o event loop."""
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.communicate()

    async def _abrir_brave(self, url: str) -> None:
        """Abre URL no Brave."""
        await self._run_exec("brave-browser", url)
        self._browser_aberto = True

    async def tocar(self, query: str) -> str:
        """
        Busca e toca uma música via API.

        Args:
            query: Nome da música ou artista.

        Returns:
            Mensagem de status.
        """
        try:
            yt = self._get_yt()

            # Busca música
            results = await asyncio.to_thread(yt.search, query, filter="songs")

            if not results:
                return f"Nenhuma música encontrada para '{query}'."

            # Pega primeiro resultado
            song = results[0]
            video_id = song.get("videoId")
            title = song.get("title", query)

            if not video_id:
                return f"Não foi possível obter ID do vídeo para '{query}'."

            # Abre no Brave
            url = f"{self.BASE_URL}/watch?v={video_id}"
            await self._abrir_brave(url)

            logger.info(f"Tocando: {title}")
            return f"Tocando: {title}"

        except Exception as e:
            logger.error(f"Erro ao tocar '{query}': {e}")
            return f"Não foi possível tocar '{query}': {str(e)}"

    async def pausar(self) -> str:
        """Pausa/retoma via tecla Espaço."""
        try:
            await self._run_exec("xdotool", "key", "space")
            return "Play/Pause acionado."
        except Exception as e:
            return f"Erro: {e}. Instale xdotool: sudo apt install xdotool"

    async def proximo(self) -> str:
        """Próxima música via Shift+N."""
        try:
            await self._run_exec("xdotool", "key", "Shift+N")
            return "Próxima música."
        except Exception as e:
            return f"Erro: {e}"

    async def volume(self, nivel: int) -> str:
        """Ajusta volume do sistema."""
        try:
            nivel = max(0, min(100, nivel))
            await self._run_exec(
                "pactl",
                "set-sink-volume",
                "@DEFAULT_SINK@",
                f"{nivel}%",
            )
            return f"Volume ajustado para {nivel}%."
        except Exception as e:
            return f"Erro: {e}"


youtube_controller = YoutubeMusicController()


@log_tool_call
async def controlar_musica(acao: str, query: str = "") -> str:
    """Controla reprodução de música via YouTube Music.

    Args:
        acao: Uma de: tocar, pausar, proximo, volume
        query: Nome da música/artista (para acao=tocar) ou nível 0-100 (para acao=volume)

    Returns:
        Mensagem de status da ação
    """
    try:
        if acao == "tocar":
            if not query:
                return "Por favor, diga o nome da música ou artista."
            return await youtube_controller.tocar(query)
        elif acao == "pausar":
            return await youtube_controller.pausar()
        elif acao == "proximo":
            return await youtube_controller.proximo()
        elif acao == "volume":
            nivel = int(query) if query.isdigit() else 50
            return await youtube_controller.volume(nivel)
        else:
            return f"Ação '{acao}' não reconhecida. Use: tocar, pausar, proximo, volume"
    except Exception as e:
        logger.error(f"Erro ao controlar música: {e}")
        return f"Não foi possível controlar a música: {str(e)}"


async def setup_ytmusic() -> str:
    """
    Configura autenticação do YouTube Music.

    Execute uma vez para autorizar o acesso à sua conta.

    Returns:
        Instruções de setup.
    """
    try:
        config_dir = Path.home() / ".config" / "pulsar-ytmusic"
        config_dir.mkdir(parents=True, exist_ok=True)

        # Abre browser para autorização
        process = await asyncio.create_subprocess_exec(
            "brave-browser",
            "https://music.youtube.com",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.communicate()

        return (
            "Setup iniciado. Siga as instruções no terminal para autorizar "
            "o acesso ao YouTube Music. Você precisará fazer login no browser "
            "e colar os headers de autenticação."
        )
    except Exception as e:
        return f"Erro no setup: {e}"
