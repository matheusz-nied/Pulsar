"""
Módulo de Text-to-Speech usando edge-tts.

Implementa síntese de voz em português usando edge-tts (Microsoft Azure TTS)
com sistema de cache baseado em hash MD5 para evitar regerar áudios idênticos.
"""

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from backend.core.logging_config import add_request_metric

try:
    import edge_tts
except ImportError as e:
    logger.error("edge-tts não encontrado. Instale com: pip install edge-tts")
    raise ImportError(
        "Dependência faltando: edge-tts. Execute: pip install edge-tts"
    ) from e


class EdgeTTS:
    """
    Classe para síntese de voz usando edge-tts com cache inteligente.

    Atributos:
        VOICE_PT: Voz feminina padrão em português do Brasil.
        VOICE_PT_MALE: Voz masculina em português do Brasil.
        CACHE_DIR: Diretório onde os arquivos de áudio são armazenados.
    """

    VOICE_PT: str = "pt-BR-FranciscaNeural"
    VOICE_PT_MALE: str = "pt-BR-AntonioNeural"
    CACHE_DIR: str = "backend/audio_cache/"

    def __init__(self) -> None:
        """Inicializa o sistema TTS e garante que o diretório de cache existe."""
        self.cache_path = Path(self.CACHE_DIR)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"EdgeTTS inicializado. Cache: {self.cache_path.absolute()}")

    def _gerar_hash(self, texto: str, voice: str) -> str:
        """
        Gera hash MD5 único para combinação texto+voz.

        Args:
            texto: Texto a ser sintetizado.
            voice: ID da voz a ser usada.

        Returns:
            Hash MD5 hexadecimal.
        """
        conteudo = f"{texto}:{voice}"
        return hashlib.md5(conteudo.encode("utf-8")).hexdigest()

    def _limpar_markdown(self, texto: str) -> str:
        """Remove formatações Markdown (asteriscos, crases, etc) para o TTS não ler os caracteres."""
        # Limpar blocos de código
        texto = re.sub(r"```.*?```", "", texto, flags=re.DOTALL)
        # Limpar caracteres de formatação Markdown
        texto = re.sub(r"[*_~`#]", "", texto)
        return texto.strip()

    def _suavizar_pausas(self, texto: str) -> str:
        """
        Reduz pausas excessivas do TTS em pontuações leves.

        Preserva vírgulas decimais como `1,5`, mas remove vírgulas usadas só
        para cadência textual, que no edge-tts tendem a produzir pausas longas.

        Args:
            texto: Texto já limpo para síntese.

        Returns:
            Texto com pausas leves suavizadas.
        """
        texto = re.sub(r"(?<!\d),|,(?!\d)", " ", texto)
        return re.sub(r"\s+", " ", texto).strip()

    def _normalizar_frase_curta(self, texto: str) -> str:
        """
        Normaliza frases curtas para o TTS incremental.

        Args:
            texto: Texto bruto da frase.

        Returns:
            Texto limpo com espaços colapsados.
        """
        texto_sem_markdown = self._limpar_markdown(texto)
        return self._suavizar_pausas(texto_sem_markdown)

    async def _sintetizar_texto(
        self,
        texto: str,
        voice: Optional[str] = None,
        *,
        preprocess: str = "markdown",
    ) -> str:
        """
        Implementação comum da síntese com suporte a preprocessamento leve.

        Args:
            texto: Texto a ser convertido em áudio.
            voice: Voz opcional.
            preprocess: Estratégia de limpeza (`markdown` ou `frase`).

        Returns:
            Caminho absoluto do arquivo MP3 gerado ou recuperado do cache.
        """
        if not texto or not texto.strip():
            raise ValueError("Texto não pode estar vazio")

        started_at = time.perf_counter()

        voice = voice or self.VOICE_PT
        if preprocess == "frase":
            texto_limpo = self._normalizar_frase_curta(texto)
        else:
            texto_limpo = self._suavizar_pausas(self._limpar_markdown(texto))

        if not texto_limpo:
            raise ValueError("Texto ficou vazio após preprocessamento do TTS")

        file_hash = self._gerar_hash(texto_limpo, voice)
        output_path = self.cache_path / f"{file_hash}.mp3"

        if output_path.exists():
            add_request_metric("tts_ms", (time.perf_counter() - started_at) * 1000)
            logger.info(
                f"Áudio encontrado no cache: {output_path.name} "
                f"({len(texto_limpo)} caracteres)"
            )
            return str(output_path.absolute())

        logger.info(
            f"Sintetizando áudio: {len(texto_limpo)} caracteres "
            f"(voz={voice}, hash={file_hash})"
        )

        try:
            communicate = edge_tts.Communicate(texto_limpo, voice=voice, rate="+35%")
            await communicate.save(str(output_path))
            add_request_metric("tts_ms", (time.perf_counter() - started_at) * 1000)

            logger.success(
                f"Áudio gerado: {output_path.name} ({output_path.stat().st_size} bytes)"
            )
            return str(output_path.absolute())
        except Exception as e:
            logger.error(f"Erro ao sintetizar áudio: {e}")
            if output_path.exists():
                output_path.unlink()
            raise

    async def sintetizar(self, texto: str, voice: Optional[str] = None) -> str:
        """
        Sintetiza texto em áudio MP3 usando edge-tts.

        Utiliza sistema de cache baseado em hash MD5. Se o mesmo texto
        com a mesma voz já foi sintetizado, retorna o arquivo existente
        sem regerar.

        Args:
            texto: Texto a ser convertido em áudio.
            voice: ID da voz (opcional, usa VOICE_PT por padrão).

        Returns:
            Caminho absoluto do arquivo MP3 gerado ou em cache.

        Raises:
            ValueError: Se o texto estiver vazio.
            Exception: Erros durante a síntese de voz.
        """
        return await self._sintetizar_texto(
            texto,
            voice,
            preprocess="markdown",
        )

    async def sintetizar_frase(self, texto: str, voice: Optional[str] = None) -> str:
        """
        Sintetiza uma frase curta para o pipeline de TTS incremental.

        Args:
            texto: Frase curta a ser sintetizada.
            voice: Voz opcional.

        Returns:
            Caminho absoluto do arquivo MP3 gerado ou em cache.
        """
        return await self._sintetizar_texto(
            texto,
            voice,
            preprocess="frase",
        )

    async def limpar_cache(self, max_files: int = 100) -> int:
        """
        Remove arquivos de áudio mais antigos do cache.

        Mantém apenas os max_files arquivos mais recentes,
        removendo os demais ordenados por data de modificação.

        Args:
            max_files: Número máximo de arquivos a manter no cache.

        Returns:
            Quantidade de arquivos removidos.
        """
        # Lista todos os arquivos .mp3 no cache
        arquivos = list(self.cache_path.glob("*.mp3"))

        if len(arquivos) <= max_files:
            logger.debug(
                f"Cache dentro do limite: {len(arquivos)}/{max_files} arquivos"
            )
            return 0

        # Ordena por data de modificação (mais antigos primeiro)
        arquivos.sort(key=lambda f: f.stat().st_mtime)

        # Calcula quantos arquivos remover
        qtd_remover = len(arquivos) - max_files
        arquivos_remover = arquivos[:qtd_remover]

        logger.info(
            f"Limpando cache: removendo {qtd_remover} arquivos (total: {len(arquivos)})"
        )

        # Remove arquivos
        removidos = 0
        for arquivo in arquivos_remover:
            try:
                arquivo.unlink()
                removidos += 1
            except Exception as e:
                logger.error(f"Erro ao remover {arquivo.name}: {e}")

        logger.success(
            f"Cache limpo: {removidos} arquivos removidos, "
            f"{len(arquivos) - removidos} mantidos"
        )

        return removidos

    def obter_estatisticas_cache(self) -> dict:
        """
        Retorna estatísticas do cache de áudio.

        Returns:
            Dicionário com total_arquivos, tamanho_total_bytes, tamanho_total_mb.
        """
        arquivos = list(self.cache_path.glob("*.mp3"))
        tamanho_total = sum(f.stat().st_size for f in arquivos)

        return {
            "total_arquivos": len(arquivos),
            "tamanho_total_bytes": tamanho_total,
            "tamanho_total_mb": round(tamanho_total / (1024 * 1024), 2),
        }


# Instância global do TTS
tts: Optional[EdgeTTS] = None


def get_tts() -> EdgeTTS:
    """
    Retorna instância global do TTS (lazy loading).

    Returns:
        Instância do EdgeTTS.
    """
    global tts
    if tts is None:
        tts = EdgeTTS()
    return tts
