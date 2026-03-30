"""
Módulo de Speech-to-Text usando faster-whisper.

Implementa transcrição de áudio em português usando o modelo Whisper
otimizado via faster-whisper (CTranslate2).
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from backend.core.logging_config import add_request_metric

try:
    from faster_whisper import WhisperModel
except ImportError as e:
    logger.error(
        "faster-whisper não encontrado. Instale com: pip install faster-whisper"
    )
    raise ImportError(
        "Dependência faltando: faster-whisper. Execute: pip install faster-whisper"
    ) from e


class WhisperSTT:
    """
    Classe para transcrição de áudio usando faster-whisper.

    Atributos:
        model: Instância do modelo WhisperModel carregado.
        model_size: Tamanho do modelo ("tiny", "base", "small", "medium", "large").
        device: Dispositivo usado ("cuda" ou "cpu").
    """

    def __init__(self, model_size: str = "small") -> None:
        """
        Inicializa o modelo Whisper.

        Args:
            model_size: Tamanho do modelo a ser carregado.
                       Opções: "tiny", "base", "small", "medium", "large".
        """
        self.model_size = model_size

        # Detecta se CUDA está disponível
        try:
            import torch

            has_cuda = torch.cuda.is_available()
        except ImportError:
            has_cuda = False

        # Define device e compute_type
        if has_cuda:
            self.device = "cuda"
            self.compute_type = "int8"
        else:
            self.device = "cpu"
            self.compute_type = "int8"

        logger.info(
            f"Carregando modelo Whisper '{model_size}' "
            f"(device={self.device}, compute_type={self.compute_type})..."
        )

        # Tenta carregar com diferentes configurações em ordem de preferência
        configs_to_try = [
            (self.device, self.compute_type),  # Configuração detectada
            ("cpu", "int8"),  # Fallback 1: CPU com int8
            ("cpu", "default"),  # Fallback 2: CPU com default
        ]

        last_error: Exception = RuntimeError("Falha ao carregar modelo Whisper")
        for idx, (device, compute_type) in enumerate(configs_to_try):
            try:
                self.device = device
                self.compute_type = compute_type

                self.model = WhisperModel(
                    model_size, device=self.device, compute_type=self.compute_type
                )

                if idx == 0:
                    logger.success(
                        f"Modelo Whisper '{model_size}' carregado com sucesso "
                        f"(device={self.device}, compute_type={self.compute_type})"
                    )
                else:
                    logger.warning(
                        f"Usando fallback {idx}: device={self.device}, "
                        f"compute_type={self.compute_type}"
                    )
                    logger.success(
                        f"Modelo Whisper '{model_size}' carregado com sucesso (fallback)"
                    )
                break  # Sucesso, sai do loop

            except ValueError as e:
                last_error = e
                if idx < len(configs_to_try) - 1:
                    logger.debug(
                        f"Falha com device={device}, compute_type={compute_type}: {e}"
                    )
                continue
            except Exception as e:
                last_error = e
                logger.error(f"Erro inesperado ao carregar modelo Whisper: {e}")
                raise
        else:
            # Se chegou aqui, todas as tentativas falharam
            logger.error(
                f"Falha ao carregar modelo após todas tentativas: {last_error}"
            )
            raise last_error

    async def transcrever(self, audio_path: str) -> str:
        """
        Transcreve arquivo de áudio para texto (versão assíncrona).

        Args:
            audio_path: Caminho para o arquivo de áudio (.wav, .mp3, etc).

        Returns:
            Texto transcrito concatenado.

        Raises:
            FileNotFoundError: Se o arquivo de áudio não existe.
            Exception: Erros durante a transcrição.
        """
        # Valida existência do arquivo
        if not Path(audio_path).exists():
            logger.error(f"Arquivo de áudio não encontrado: {audio_path}")
            raise FileNotFoundError(f"Arquivo não existe: {audio_path}")

        logger.info(f"Iniciando transcrição de: {audio_path}")
        start_time = time.time()

        try:
            # Executa transcrição em thread separada para não bloquear event loop
            loop = asyncio.get_event_loop()
            texto = await loop.run_in_executor(None, self.transcrever_sync, audio_path)

            elapsed = time.time() - start_time
            add_request_metric("stt_ms", elapsed * 1000)
            logger.success(
                f"Transcrição concluída em {elapsed:.2f}s: {len(texto)} caracteres"
            )

            return texto

        except Exception as e:
            logger.error(f"Erro na transcrição: {e}")
            raise

    def transcrever_sync(self, audio_path: str) -> str:
        """
        Transcreve arquivo de áudio para texto (versão síncrona).

        Args:
            audio_path: Caminho para o arquivo de áudio (.wav, .mp3, etc).

        Returns:
            Texto transcrito concatenado.

        Raises:
            FileNotFoundError: Se o arquivo de áudio não existe.
            Exception: Erros durante a transcrição.
        """
        # Valida existência do arquivo
        if not Path(audio_path).exists():
            logger.error(f"Arquivo de áudio não encontrado: {audio_path}")
            raise FileNotFoundError(f"Arquivo não existe: {audio_path}")

        logger.debug(f"Transcrevendo (sync): {audio_path}")

        try:
            # Greedy decoding + VAD tornam o caminho de voz curta mais rápido.
            segments, info = self.model.transcribe(
                audio_path,
                language="pt",
                beam_size=1,
                vad_filter=True,
            )

            logger.debug(
                f"Idioma detectado: {info.language} "
                f"(probabilidade: {info.language_probability:.2%})"
            )

            # Concatena todos os segmentos
            texto_completo = " ".join(segment.text.strip() for segment in segments)

            return texto_completo.strip()

        except Exception as e:
            logger.error(f"Erro ao transcrever {audio_path}: {e}")
            raise


# Instância global do STT
stt: Optional[WhisperSTT] = None


def get_stt(model_size: str = "small") -> WhisperSTT:
    """
    Retorna instância global do STT (lazy loading).

    Args:
        model_size: Tamanho do modelo Whisper.

    Returns:
        Instância do WhisperSTT.
    """
    global stt
    if stt is None:
        stt = WhisperSTT(model_size=model_size)
    return stt
