"""
Testes para o módulo TTS (Text-to-Speech).
"""

import asyncio
from pathlib import Path

import pytest

from backend.audio.tts import EdgeTTS, get_tts


class TestEdgeTTS:
    """Testes para a classe EdgeTTS."""

    def test_init(self):
        """Testa inicialização e criação do diretório de cache."""
        tts_instance = EdgeTTS()
        assert tts_instance.cache_path.exists()
        assert tts_instance.VOICE_PT == "pt-BR-FranciscaNeural"
        assert tts_instance.VOICE_PT_MALE == "pt-BR-AntonioNeural"

    def test_gerar_hash(self):
        """Testa geração de hash MD5."""
        tts_instance = EdgeTTS()

        hash1 = tts_instance._gerar_hash("Olá", "pt-BR-FranciscaNeural")
        hash2 = tts_instance._gerar_hash("Olá", "pt-BR-FranciscaNeural")
        hash3 = tts_instance._gerar_hash("Olá", "pt-BR-AntonioNeural")
        hash4 = tts_instance._gerar_hash("Oi", "pt-BR-FranciscaNeural")

        # Mesmo texto e voz devem gerar mesmo hash
        assert hash1 == hash2

        # Voz diferente deve gerar hash diferente
        assert hash1 != hash3

        # Texto diferente deve gerar hash diferente
        assert hash1 != hash4

        # Hash deve ser MD5 válido (32 caracteres hexadecimais)
        assert len(hash1) == 32
        assert all(c in "0123456789abcdef" for c in hash1)

    @pytest.mark.asyncio
    async def test_sintetizar_texto_vazio(self):
        """Testa erro quando texto está vazio."""
        tts_instance = EdgeTTS()

        with pytest.raises(ValueError, match="Texto não pode estar vazio"):
            await tts_instance.sintetizar("")

        with pytest.raises(ValueError, match="Texto não pode estar vazio"):
            await tts_instance.sintetizar("   ")

        with pytest.raises(ValueError, match="Texto não pode estar vazio"):
            await tts_instance.sintetizar_frase("")

    @pytest.mark.asyncio
    async def test_sintetizar_gera_audio(self):
        """Testa geração de áudio MP3."""
        tts_instance = EdgeTTS()
        texto = "Olá, tudo bem?"

        # Primeira chamada deve gerar o arquivo
        audio_path = await tts_instance.sintetizar(texto)

        assert audio_path is not None
        assert Path(audio_path).exists()
        assert Path(audio_path).suffix == ".mp3"
        assert Path(audio_path).stat().st_size > 0

        print(f"\nÁudio gerado: {audio_path} ({Path(audio_path).stat().st_size} bytes)")

    @pytest.mark.asyncio
    async def test_sintetizar_usa_cache(self):
        """Testa que cache é utilizado para texto idêntico."""
        tts_instance = EdgeTTS()
        texto = "Este é um teste de cache"

        # Primeira chamada gera o arquivo
        audio_path1 = await tts_instance.sintetizar(texto)
        time1 = Path(audio_path1).stat().st_mtime

        # Aguarda um pouco para garantir que timestamps seriam diferentes
        await asyncio.sleep(0.1)

        # Segunda chamada deve usar o cache
        audio_path2 = await tts_instance.sintetizar(texto)
        time2 = Path(audio_path2).stat().st_mtime

        # Deve retornar o mesmo arquivo
        assert audio_path1 == audio_path2
        # Timestamp deve ser idêntico (não foi regenerado)
        assert time1 == time2

        print(f"\nCache funcionando: mesmo arquivo retornado ({audio_path1})")

    @pytest.mark.asyncio
    async def test_sintetizar_vozes_diferentes(self):
        """Testa que vozes diferentes geram arquivos diferentes."""
        tts_instance = EdgeTTS()
        texto = "Teste de vozes"

        # Voz feminina
        audio_path_fem = await tts_instance.sintetizar(
            texto, voice=tts_instance.VOICE_PT
        )

        # Voz masculina
        audio_path_masc = await tts_instance.sintetizar(
            texto, voice=tts_instance.VOICE_PT_MALE
        )

        # Devem ser arquivos diferentes
        assert audio_path_fem != audio_path_masc
        assert Path(audio_path_fem).exists()
        assert Path(audio_path_masc).exists()

        print(f"\nVoz feminina: {audio_path_fem}")
        print(f"Voz masculina: {audio_path_masc}")

    @pytest.mark.asyncio
    async def test_limpar_cache(self):
        """Testa limpeza de cache."""
        tts_instance = EdgeTTS()

        # Gera vários arquivos
        textos = [f"Teste número {i}" for i in range(5)]
        for texto in textos:
            await tts_instance.sintetizar(texto)

        # Verifica que arquivos foram criados
        stats_antes = tts_instance.obter_estatisticas_cache()
        assert stats_antes["total_arquivos"] >= 5

        # Limpa cache mantendo apenas 2 arquivos
        removidos = await tts_instance.limpar_cache(max_files=2)

        # Verifica que arquivos foram removidos
        stats_depois = tts_instance.obter_estatisticas_cache()
        assert stats_depois["total_arquivos"] <= 2
        assert removidos >= 3

        print(f"\nAntes: {stats_antes['total_arquivos']} arquivos")
        print(f"Depois: {stats_depois['total_arquivos']} arquivos")
        print(f"Removidos: {removidos} arquivos")

    @pytest.mark.asyncio
    async def test_limpar_cache_sem_excesso(self):
        """Testa que limpar_cache não remove nada se cache está dentro do limite."""
        tts_instance = EdgeTTS()

        # Limpa tudo primeiro
        await tts_instance.limpar_cache(max_files=0)

        # Gera apenas 2 arquivos
        await tts_instance.sintetizar("Teste 1")
        await tts_instance.sintetizar("Teste 2")

        # Tenta limpar com limite de 10
        removidos = await tts_instance.limpar_cache(max_files=10)

        # Nada deve ser removido
        assert removidos == 0

    def test_obter_estatisticas_cache(self):
        """Testa obtenção de estatísticas do cache."""
        tts_instance = EdgeTTS()

        stats = tts_instance.obter_estatisticas_cache()

        assert "total_arquivos" in stats
        assert "tamanho_total_bytes" in stats
        assert "tamanho_total_mb" in stats
        assert isinstance(stats["total_arquivos"], int)
        assert isinstance(stats["tamanho_total_bytes"], int)
        assert isinstance(stats["tamanho_total_mb"], float)

    def test_get_tts_singleton(self):
        """Testa que get_tts retorna sempre a mesma instância."""
        tts1 = get_tts()
        tts2 = get_tts()
        assert tts1 is tts2

    def test_normalizar_frase_curta_remove_markdown(self):
        """Garante que o TTS incremental não leia marcadores Markdown."""
        tts_instance = EdgeTTS()

        texto = "**Olá** _mundo_ com `código` e #titulo"

        assert (
            tts_instance._normalizar_frase_curta(texto)
            == "Olá mundo com código e titulo"
        )

    def test_suavizar_pausas_remove_virgula_textual(self):
        """Reduz pausas em vírgulas textuais sem afetar o conteúdo falado."""
        tts_instance = EdgeTTS()

        assert (
            tts_instance._suavizar_pausas("Olá, tudo bem, por aí?")
            == "Olá tudo bem por aí?"
        )

    def test_suavizar_pausas_preserva_virgula_decimal(self):
        """Mantém vírgulas decimais para números como 1,5."""
        tts_instance = EdgeTTS()

        assert tts_instance._suavizar_pausas("Use 1,5 litro de água.") == (
            "Use 1,5 litro de água."
        )
