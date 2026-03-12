"""
Testes para o endpoint WebSocket /ws/audio.
"""

import base64
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from backend.main import app


class TestWebSocketAudio:
    """Testes para o WebSocket /ws/audio."""

    def _get_audio_b64_chunks(self, chunk_size: int = 4096) -> list[str]:
        """Carrega o áudio de teste e retorna como lista de chunks base64."""
        audio_path = Path(__file__).parent / "fixtures" / "audio_test.wav"
        if not audio_path.exists():
            pytest.skip("Arquivo de teste não encontrado")

        audio_bytes = audio_path.read_bytes()
        chunks = []
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i : i + chunk_size]
            chunks.append(base64.b64encode(chunk).decode("utf-8"))
        return chunks

    def test_ws_full_pipeline(self):
        """Testa pipeline completo: audio_chunk → audio_end → resposta."""
        chunks = self._get_audio_b64_chunks()

        client = TestClient(app)
        session_id = "test-ws-session-001"

        with client.websocket_connect("/ws/audio") as ws:
            # Envia chunks de áudio
            for chunk in chunks:
                ws.send_text(json.dumps({
                    "type": "audio_chunk",
                    "data": chunk,
                    "session_id": session_id,
                }))

            # Sinaliza fim do áudio
            ws.send_text(json.dumps({
                "type": "audio_end",
                "session_id": session_id,
            }))

            # Coleta respostas do servidor
            mensagens = []
            tipos_esperados = {"transcricao", "resposta_chunk", "audio_ready"}
            tipos_recebidos = set()

            while tipos_esperados - tipos_recebidos:
                data = ws.receive_json()
                mensagens.append(data)
                tipos_recebidos.add(data["type"])

                if data["type"] == "erro":
                    pytest.fail(f"Erro recebido: {data['mensagem']}")

                # audio_ready é o último evento
                if data["type"] == "audio_ready":
                    break

            # Verifica que recebeu transcricao
            transcricoes = [m for m in mensagens if m["type"] == "transcricao"]
            assert len(transcricoes) == 1
            assert len(transcricoes[0]["texto"]) > 0
            print(f"\nTranscrição: {transcricoes[0]['texto']}")

            # Verifica que recebeu chunks de resposta
            resp_chunks = [m for m in mensagens if m["type"] == "resposta_chunk"]
            assert len(resp_chunks) > 0
            resposta_completa = "".join(c["texto"] for c in resp_chunks)
            assert len(resposta_completa) > 0
            print(f"Resposta: {resposta_completa}")

            # Verifica que recebeu audio_ready
            audio_ready = [m for m in mensagens if m["type"] == "audio_ready"]
            assert len(audio_ready) == 1
            assert audio_ready[0]["url"].startswith("/audio/")
            assert audio_ready[0]["url"].endswith(".mp3")
            print(f"Audio URL: {audio_ready[0]['url']}")

    def test_ws_audio_end_without_chunks(self):
        """Testa que audio_end sem chunks retorna erro."""
        client = TestClient(app)

        with client.websocket_connect("/ws/audio") as ws:
            ws.send_text(json.dumps({
                "type": "audio_end",
                "session_id": "test-empty",
            }))

            data = ws.receive_json()
            assert data["type"] == "erro"
            assert "Nenhum áudio" in data["mensagem"]
            print(f"\nErro esperado: {data['mensagem']}")

    def test_ws_invalid_json(self):
        """Testa que JSON inválido retorna erro."""
        client = TestClient(app)

        with client.websocket_connect("/ws/audio") as ws:
            ws.send_text("isto não é json")

            data = ws.receive_json()
            assert data["type"] == "erro"
            assert "JSON" in data["mensagem"]

    def test_ws_unknown_type(self):
        """Testa que tipo desconhecido retorna erro."""
        client = TestClient(app)

        with client.websocket_connect("/ws/audio") as ws:
            ws.send_text(json.dumps({"type": "desconhecido"}))

            data = ws.receive_json()
            assert data["type"] == "erro"
            assert "desconhecido" in data["mensagem"]

    def test_ws_invalid_base64(self):
        """Testa que base64 inválido retorna erro."""
        client = TestClient(app)

        with client.websocket_connect("/ws/audio") as ws:
            ws.send_text(json.dumps({
                "type": "audio_chunk",
                "data": "!!!not-base64!!!",
            }))

            data = ws.receive_json()
            assert data["type"] == "erro"
            assert "Base64" in data["mensagem"]

    def test_ws_empty_data_chunk(self):
        """Testa que audio_chunk com data vazio retorna erro."""
        client = TestClient(app)

        with client.websocket_connect("/ws/audio") as ws:
            ws.send_text(json.dumps({
                "type": "audio_chunk",
                "data": "",
            }))

            data = ws.receive_json()
            assert data["type"] == "erro"
            assert "vazio" in data["mensagem"].lower()
