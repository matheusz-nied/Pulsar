"""
Testes para os endpoints de voz (/voice e /audio).
"""

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.mark.asyncio
async def test_voice_endpoint_with_valid_audio():
    """Testa o endpoint /voice com arquivo de áudio válido."""
    # Gera arquivo de teste se não existir
    audio_test_path = Path(__file__).parent / "fixtures" / "audio_test.wav"
    
    if not audio_test_path.exists():
        pytest.skip("Arquivo de teste não encontrado")
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Abre e envia arquivo de áudio
        with open(audio_test_path, "rb") as f:
            files = {"audio": ("test.wav", f, "audio/wav")}
            response = await client.post("/voice", files=files)
        
        # Verifica resposta
        assert response.status_code == 200
        data = response.json()
        
        # Verifica campos obrigatórios
        assert "transcricao" in data
        assert "resposta" in data
        assert "audio_url" in data
        assert "session_id" in data
        
        # Verifica que campos não estão vazios
        assert len(data["transcricao"]) > 0
        assert len(data["resposta"]) > 0
        assert data["audio_url"].startswith("/audio/")
        assert data["audio_url"].endswith(".mp3")
        
        print(f"\nTranscrição: {data['transcricao']}")
        print(f"Resposta: {data['resposta']}")
        print(f"Audio URL: {data['audio_url']}")
        print(f"Session ID: {data['session_id']}")


@pytest.mark.asyncio
async def test_voice_endpoint_with_session_id():
    """Testa o endpoint /voice mantendo a mesma sessão."""
    audio_test_path = Path(__file__).parent / "fixtures" / "audio_test.wav"
    
    if not audio_test_path.exists():
        pytest.skip("Arquivo de teste não encontrado")
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Primeira chamada
        with open(audio_test_path, "rb") as f:
            files = {"audio": ("test.wav", f, "audio/wav")}
            response1 = await client.post("/voice", files=files)
        
        assert response1.status_code == 200
        data1 = response1.json()
        session_id = data1["session_id"]
        
        # Segunda chamada com mesmo session_id
        with open(audio_test_path, "rb") as f:
            files = {"audio": ("test.wav", f, "audio/wav")}
            data = {"session_id": session_id}
            response2 = await client.post("/voice", files=files, data=data)
        
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Deve manter mesmo session_id
        assert data2["session_id"] == session_id
        
        print(f"\nSessão mantida: {session_id}")


@pytest.mark.asyncio
async def test_voice_endpoint_empty_file():
    """Testa erro com arquivo vazio."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        files = {"audio": ("empty.wav", b"", "audio/wav")}
        response = await client.post("/voice", files=files)
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "vazio" in data["detail"].lower()


@pytest.mark.asyncio
async def test_audio_endpoint_valid_file():
    """Testa o endpoint /audio/{filename} com arquivo válido."""
    # Primeiro gera um áudio via TTS
    from backend.audio.tts import get_tts
    
    tts = get_tts()
    audio_path = await tts.sintetizar("Teste de endpoint de áudio")
    filename = Path(audio_path).name
    
    # Tenta acessar o arquivo
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/audio/{filename}")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert len(response.content) > 0
        
        print(f"\nÁudio servido: {filename} ({len(response.content)} bytes)")


@pytest.mark.asyncio
async def test_audio_endpoint_file_not_found():
    """Testa erro 404 quando arquivo não existe."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/audio/naoexiste.mp3")
        
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data


@pytest.mark.asyncio
async def test_audio_endpoint_invalid_filename():
    """Testa validação de nome de arquivo inválido."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Tenta path traversal - FastAPI normaliza o path antes, então retorna 404
        response = await client.get("/audio/../etc/passwd")
        assert response.status_code == 404
        
        # Tenta arquivo sem .mp3
        response = await client.get("/audio/arquivo.txt")
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_health_endpoint():
    """Testa que o endpoint /health ainda funciona."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
