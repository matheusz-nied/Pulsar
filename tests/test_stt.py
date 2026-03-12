"""
Testes para o módulo STT (Speech-to-Text).
"""

import asyncio
import os
from pathlib import Path

import pytest

from backend.audio.stt import WhisperSTT, get_stt


class TestWhisperSTT:
    """Testes para a classe WhisperSTT."""
    
    def test_init_default(self):
        """Testa inicialização com configurações padrão."""
        stt_instance = WhisperSTT()
        assert stt_instance.model_size == "medium"
        assert stt_instance.device in ["cuda", "cpu"]
        assert stt_instance.model is not None
    
    def test_init_custom_size(self):
        """Testa inicialização com tamanho customizado."""
        stt_instance = WhisperSTT(model_size="base")
        assert stt_instance.model_size == "base"
        assert stt_instance.model is not None
    
    def test_transcrever_sync_file_not_found(self):
        """Testa erro quando arquivo não existe."""
        stt_instance = WhisperSTT(model_size="base")
        
        with pytest.raises(FileNotFoundError):
            stt_instance.transcrever_sync("/caminho/inexistente/audio.wav")
    
    @pytest.mark.asyncio
    async def test_transcrever_async_file_not_found(self):
        """Testa erro assíncrono quando arquivo não existe."""
        stt_instance = WhisperSTT(model_size="base")
        
        with pytest.raises(FileNotFoundError):
            await stt_instance.transcrever("/caminho/inexistente/audio.wav")
    
    def test_get_stt_singleton(self):
        """Testa que get_stt retorna sempre a mesma instância."""
        stt1 = get_stt(model_size="base")
        stt2 = get_stt(model_size="base")
        assert stt1 is stt2


@pytest.mark.skipif(
    not Path("/home/kaizen/Documents/Dev/Projetos/Jarvis/assistente_local/tests/fixtures/audio_test.wav").exists(),
    reason="Arquivo de teste de áudio não encontrado"
)
class TestWhisperSTTWithAudio:
    """Testes que requerem arquivo de áudio real."""
    
    def test_transcrever_sync_portugues(self):
        """Testa transcrição síncrona de áudio em português."""
        stt_instance = WhisperSTT(model_size="base")
        audio_path = "/home/kaizen/Documents/Dev/Projetos/Jarvis/assistente_local/tests/fixtures/audio_test.wav"
        
        texto = stt_instance.transcrever_sync(audio_path)
        
        assert isinstance(texto, str)
        assert len(texto) > 0
        print(f"\nTexto transcrito: {texto}")
    
    @pytest.mark.asyncio
    async def test_transcrever_async_portugues(self):
        """Testa transcrição assíncrona de áudio em português."""
        stt_instance = WhisperSTT(model_size="base")
        audio_path = "/home/kaizen/Documents/Dev/Projetos/Jarvis/assistente_local/tests/fixtures/audio_test.wav"
        
        texto = await stt_instance.transcrever(audio_path)
        
        assert isinstance(texto, str)
        assert len(texto) > 0
        print(f"\nTexto transcrito (async): {texto}")
