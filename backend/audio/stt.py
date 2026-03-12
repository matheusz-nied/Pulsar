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

try:
    from faster_whisper import WhisperModel
except ImportError as e:
    logger.error(
        "faster-whisper não encontrado. Instale com: "
        "pip install faster-whisper"
    )
    raise ImportError(
        "Dependência faltando: faster-whisper. "
        "Execute: pip install faster-whisper"
    ) from e


class WhisperSTT:
    """
    Classe para transcrição de áudio usando faster-whisper.
    
    Atributos:
        model: Instância do modelo WhisperModel carregado.
        model_size: Tamanho do modelo ("tiny", "base", "small", "medium", "large").
        device: Dispositivo usado ("cuda" ou "cpu").
    """
    
    def __init__(self, model_size: str = "medium") -> None:
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
        
        try:
            self.model = WhisperModel(
                model_size,
                device=self.device,
                compute_type=self.compute_type
            )
            logger.success(
                f"Modelo Whisper '{model_size}' carregado com sucesso "
                f"(device={self.device}, compute_type={self.compute_type})"
            )
        except ValueError as e:
            # Fallback para CPU se CUDA falhar
            if "float16" in str(e) and self.device == "cuda":
                logger.warning(
                    f"CUDA não suporta float16, usando CPU com int8: {e}"
                )
                self.device = "cpu"
                self.compute_type = "int8"
                self.model = WhisperModel(
                    model_size,
                    device=self.device,
                    compute_type=self.compute_type
                )
                logger.success(
                    f"Modelo Whisper '{model_size}' carregado com sucesso "
                    f"(fallback: device={self.device}, compute_type={self.compute_type})"
                )
            else:
                logger.error(f"Erro ao carregar modelo Whisper: {e}")
                raise
        except Exception as e:
            logger.error(f"Erro ao carregar modelo Whisper: {e}")
            raise
    
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
            texto = await loop.run_in_executor(
                None,
                self.transcrever_sync,
                audio_path
            )
            
            elapsed = time.time() - start_time
            logger.success(
                f"Transcrição concluída em {elapsed:.2f}s: "
                f"{len(texto)} caracteres"
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
            # Transcreve com language="pt" para forçar português
            segments, info = self.model.transcribe(
                audio_path,
                language="pt",
                beam_size=5,
                vad_filter=True,  # Voice Activity Detection para melhor performance
                vad_parameters=dict(min_silence_duration_ms=500)
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


def get_stt(model_size: str = "medium") -> WhisperSTT:
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
