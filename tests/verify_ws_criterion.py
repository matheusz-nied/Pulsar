#!/usr/bin/env python3
"""
Script de verificação do critério de conclusão da Tarefa 2.4.

Critério:
- Conexão WebSocket estabelece
- Envio de audio_end dispara pipeline completo
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import websockets


async def verify_websocket_criterion():
    """Verifica o critério de conclusão do WebSocket /ws/audio."""
    print("=== Verificação do Critério de Conclusão - Tarefa 2.4 ===\n")

    # 1. Carregar arquivo de áudio de teste
    audio_path = Path(__file__).parent / "fixtures" / "audio_test.wav"
    if not audio_path.exists():
        print(f"❌ Arquivo de teste não encontrado: {audio_path}")
        return False

    audio_bytes = audio_path.read_bytes()
    print(f"📁 Arquivo de áudio: {audio_path.name} ({len(audio_bytes)} bytes)")

    # 2. Dividir em chunks e codificar em base64
    chunk_size = 4096
    chunks = []
    for i in range(0, len(audio_bytes), chunk_size):
        chunk = audio_bytes[i : i + chunk_size]
        chunks.append(base64.b64encode(chunk).decode("utf-8"))

    print(f"📦 Áudio dividido em {len(chunks)} chunks de ~{chunk_size} bytes\n")

    # 3. Conectar ao WebSocket
    ws_url = "ws://localhost:8000/ws/audio"
    print(f"🔌 Conectando ao WebSocket: {ws_url}...")

    try:
        async with websockets.connect(ws_url) as ws:
            print("✅ Conexão WebSocket estabelecida\n")

            session_id = "criterion-verification-session"

            # 4. Enviar chunks de áudio
            print(f"📤 Enviando {len(chunks)} chunks de áudio...")
            for i, chunk in enumerate(chunks, 1):
                await ws.send(
                    json.dumps({
                        "type": "audio_chunk",
                        "data": chunk,
                        "session_id": session_id,
                    })
                )
                print(f"   ✓ Chunk {i}/{len(chunks)} enviado")

            # 5. Sinalizar fim do áudio
            print("\n🔚 Enviando audio_end...\n")
            await ws.send(
                json.dumps({
                    "type": "audio_end",
                    "session_id": session_id,
                })
            )

            # 6. Coletar respostas do pipeline
            print("📥 Aguardando respostas do pipeline...\n")

            eventos = {
                "transcricao": False,
                "resposta_chunk": False,
                "audio_ready": False,
            }

            transcricao_texto = ""
            resposta_completa = ""
            audio_url = ""

            while not all(eventos.values()):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(raw)
                    msg_type = data.get("type")

                    if msg_type == "erro":
                        print(f"❌ Erro recebido: {data['mensagem']}")
                        return False

                    elif msg_type == "transcricao":
                        eventos["transcricao"] = True
                        transcricao_texto = data["texto"]
                        print(f"✅ TRANSCRIÇÃO recebida:")
                        print(f"   \"{transcricao_texto}\"\n")

                    elif msg_type == "resposta_chunk":
                        eventos["resposta_chunk"] = True
                        chunk_texto = data["texto"]
                        resposta_completa += chunk_texto
                        print(f"   📝 Chunk de resposta: \"{chunk_texto}\"")

                    elif msg_type == "audio_ready":
                        eventos["audio_ready"] = True
                        audio_url = data["url"]
                        print(f"\n✅ AUDIO_READY recebido:")
                        print(f"   URL: {audio_url}")
                        break  # Último evento do pipeline

                except asyncio.TimeoutError:
                    print("❌ Timeout aguardando resposta do servidor")
                    return False

            # 7. Validar resultados
            print("\n" + "=" * 60)
            print("📊 RESUMO DO PIPELINE")
            print("=" * 60)

            success = True

            # Validar transcrição
            if eventos["transcricao"] and len(transcricao_texto) > 0:
                print("✅ Transcrição: OK")
                print(f"   Texto: \"{transcricao_texto[:100]}...\"")
            else:
                print("❌ Transcrição: FALHOU")
                success = False

            # Validar resposta
            if eventos["resposta_chunk"] and len(resposta_completa) > 0:
                print("✅ Resposta (streaming): OK")
                print(f"   Texto: \"{resposta_completa[:100]}...\"")
            else:
                print("❌ Resposta: FALHOU")
                success = False

            # Validar audio_ready
            if eventos["audio_ready"] and audio_url.startswith("/audio/"):
                print("✅ Audio Ready: OK")
                print(f"   URL: {audio_url}")
            else:
                print("❌ Audio Ready: FALHOU")
                success = False

            print("=" * 60)

            if success:
                print("\n🎉 CRITÉRIO DE CONCLUSÃO ATENDIDO!")
                print("\nFluxo completo verificado:")
                print("  1. ✅ Conexão WebSocket estabelecida")
                print("  2. ✅ audio_chunk enviado e acumulado")
                print("  3. ✅ audio_end disparou pipeline completo:")
                print("     - Transcrição (STT)")
                print("     - Processamento com agente (streaming)")
                print("     - Síntese de áudio (TTS)")
                print("     - URL do áudio retornada")
                return True
            else:
                print("\n❌ Critério não atendido completamente")
                return False

    except ConnectionRefusedError:
        print("❌ Erro: Não foi possível conectar ao servidor")
        print("   Certifique-se de que o servidor está rodando em http://localhost:8000")
        return False
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Entry point do script."""
    print("\n" + "=" * 60)
    print("VERIFICAÇÃO DE CRITÉRIO - WebSocket /ws/audio")
    print("=" * 60 + "\n")

    print("⚠️  IMPORTANTE: Certifique-se de que o servidor está rodando:")
    print("   python backend/main.py\n")

    input("Pressione ENTER para continuar...")
    print()

    success = asyncio.run(verify_websocket_criterion())

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
