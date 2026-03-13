"""
music.py — Controle de música via YouTube Music usando Playwright.

Responsável por:
- Abrir YouTube Music no browser via Playwright
- Buscar e tocar músicas/artistas
- Pausar/retomar reprodução
- Pular para próxima faixa
- Ajustar volume
"""

from __future__ import annotations

from urllib.parse import quote_plus

from loguru import logger

from backend.core.logging_config import log_tool_call

_JS_EXTRAIR_WATCH_LINK = """() => {
    const items = document.querySelectorAll('ytmusic-responsive-list-item-renderer');
    for (const item of items) {
        const a = item.querySelector('a[href*="watch"]');
        if (a) return a.href;
    }
    const links = document.querySelectorAll('a[href*="/watch"]');
    return links.length > 0 ? links[0].href : null;
}"""

_JS_EXTRAIR_TITULO = """() => {
    const bar = document.querySelector('ytmusic-player-bar');
    if (bar) {
        const t = bar.querySelector('yt-formatted-string.title');
        if (t && t.textContent) return t.textContent;
    }
    const el = document.querySelector(
        '.content-info-wrapper yt-formatted-string.title, .middle-controls .title'
    );
    if (el && el.textContent) return el.textContent;
    const upnext = document.querySelector(
        'ytmusic-player-queue-item[selected] .song-title'
    );
    if (upnext && upnext.textContent) return upnext.textContent;
    return '';
}"""


class YoutubeMusicController:
    """Controla o YouTube Music via Playwright (browser headed)."""

    BASE_URL = "https://music.youtube.com"
    SEARCH_URL = f"{BASE_URL}/search?q="

    def __init__(self) -> None:
        """Inicializa o controlador sem abrir o browser ainda (lazy start)."""
        self._playwright: object | None = None
        self._browser: object | None = None
        self._page: object | None = None

    @property
    def _ativo(self) -> bool:
        return self._page is not None

    async def iniciar_browser(self) -> None:
        """
        Inicia Playwright em modo headed e abre o YouTube Music.

        Raises:
            RuntimeError: Se Playwright ou os browsers não estiverem instalados.
        """
        if self._ativo:
            logger.debug("Browser já está ativo, reutilizando")
            return

        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(  # type: ignore[union-attr]
                headless=False,
                channel="chrome",
                args=["--autoplay-policy=no-user-gesture-required"],
            )
            self._page = await self._browser.new_page()  # type: ignore[union-attr]
            await self._page.goto(  # type: ignore[union-attr]
                self.BASE_URL, wait_until="domcontentloaded", timeout=30_000
            )
            await self._page.wait_for_timeout(3000)  # type: ignore[union-attr]

            await self._aceitar_cookies()
            logger.info("YouTube Music aberto com sucesso")

        except ImportError:
            raise RuntimeError(
                "Playwright não está instalado. "
                "Execute: pip install playwright && playwright install chromium"
            )
        except Exception as e:
            await self._fechar()
            raise RuntimeError(f"Erro ao iniciar YouTube Music: {e}") from e

    async def _aceitar_cookies(self) -> None:
        """Tenta aceitar diálogos de consentimento/cookies se aparecerem."""
        try:
            page = self._page  # type: ignore[assignment]
            consent_btn = page.locator(  # type: ignore[union-attr]
                'button[aria-label*="Accept"], '
                'button[aria-label*="Aceitar"], '
                'button:has-text("Accept all"), '
                'button:has-text("Aceitar tudo"), '
                'form[action*="consent"] button'
            ).first
            if await consent_btn.is_visible(timeout=2000):
                await consent_btn.click()
                await page.wait_for_timeout(1000)  # type: ignore[union-attr]
                logger.debug("Cookie consent aceito")
        except Exception:
            pass

    async def _fechar(self) -> None:
        """Fecha browser e limpa referências."""
        try:
            if self._browser is not None:
                await self._browser.close()  # type: ignore[union-attr]
            if self._playwright is not None:
                await self._playwright.stop()  # type: ignore[union-attr]
        except Exception as e:
            logger.warning(f"Erro ao fechar browser: {e}")
        finally:
            self._page = None
            self._browser = None
            self._playwright = None

    async def _garantir_browser(self) -> None:
        """Garante que o browser está aberto antes de qualquer operação."""
        if not self._ativo:
            await self.iniciar_browser()

    async def tocar(self, query: str) -> str:
        """
        Busca e toca uma música/artista no YouTube Music.

        Navega para a URL de busca, extrai o link /watch do primeiro resultado
        via JS e navega diretamente para ele, evitando problemas com shadow DOM.

        Args:
            query: Nome da música ou artista a buscar.

        Returns:
            Mensagem de status com o que está tocando.
        """
        try:
            await self._garantir_browser()
            page = self._page  # type: ignore[assignment]

            search_url = f"{self.SEARCH_URL}{quote_plus(query)}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15_000)  # type: ignore[union-attr]
            await page.wait_for_timeout(4000)  # type: ignore[union-attr]

            watch_link: str | None = await page.evaluate(_JS_EXTRAIR_WATCH_LINK)  # type: ignore[union-attr]

            if not watch_link:
                return f"Nenhum resultado encontrado para '{query}'."

            await page.goto(watch_link, wait_until="domcontentloaded", timeout=15_000)  # type: ignore[union-attr]
            await page.wait_for_timeout(5000)  # type: ignore[union-attr]

            titulo = await self._obter_titulo()
            msg = f"Tocando: {titulo}" if titulo else f"Tocando resultado para: {query}"
            logger.info(msg)
            return msg

        except Exception as e:
            logger.error(f"Erro ao tocar '{query}': {e}")
            return f"Não foi possível tocar '{query}': {str(e)}"

    async def pausar(self) -> str:
        """
        Pausa ou retoma a reprodução atual.

        Returns:
            Mensagem de status.
        """
        try:
            await self._garantir_browser()
            page = self._page  # type: ignore[assignment]

            play_pause = page.locator(  # type: ignore[union-attr]
                '#play-pause-button, '
                'tp-yt-paper-icon-button.play-pause-button'
            ).first
            await play_pause.click(timeout=5000)

            logger.info("Play/Pause acionado")
            return "Reprodução pausada/retomada."

        except Exception as e:
            logger.error(f"Erro ao pausar/retomar: {e}")
            return f"Não foi possível pausar/retomar: {str(e)}"

    async def proximo(self) -> str:
        """
        Pula para a próxima faixa.

        Returns:
            Mensagem de status.
        """
        try:
            await self._garantir_browser()
            page = self._page  # type: ignore[assignment]

            next_btn = page.locator(  # type: ignore[union-attr]
                '.next-button, '
                'tp-yt-paper-icon-button.next-button'
            ).first
            await next_btn.click(timeout=5000)
            await page.wait_for_timeout(3000)  # type: ignore[union-attr]

            titulo = await self._obter_titulo()
            msg = f"Próxima faixa: {titulo}" if titulo else "Pulou para a próxima faixa."
            logger.info(msg)
            return msg

        except Exception as e:
            logger.error(f"Erro ao pular faixa: {e}")
            return f"Não foi possível pular faixa: {str(e)}"

    async def volume(self, nivel: int) -> str:
        """
        Ajusta o volume do player.

        Args:
            nivel: Nível de volume de 0 a 100.

        Returns:
            Mensagem de status.
        """
        try:
            nivel = max(0, min(100, nivel))
            await self._garantir_browser()
            page = self._page  # type: ignore[assignment]

            volume_slider = page.locator(  # type: ignore[union-attr]
                '#volume-slider, '
                'tp-yt-paper-slider#volume-slider'
            ).first
            bbox = await volume_slider.bounding_box(timeout=5000)

            if bbox:
                x = bbox["x"] + (bbox["width"] * nivel / 100)
                y = bbox["y"] + bbox["height"] / 2
                await page.mouse.click(x, y)  # type: ignore[union-attr]
                logger.info(f"Volume ajustado para {nivel}%")
                return f"Volume ajustado para {nivel}%."

            return "Não foi possível localizar o controle de volume."

        except Exception as e:
            logger.error(f"Erro ao ajustar volume: {e}")
            return f"Não foi possível ajustar o volume: {str(e)}"

    async def _obter_titulo(self) -> str:
        """Tenta extrair o título da música atualmente tocando via JS."""
        try:
            page = self._page  # type: ignore[assignment]
            return await page.evaluate(_JS_EXTRAIR_TITULO) or ""  # type: ignore[union-attr]
        except Exception:
            return ""


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
                return "Por favor, diga o nome da música ou artista que deseja ouvir."
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
