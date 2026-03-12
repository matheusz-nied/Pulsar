"""
Script para gerar arquivo de áudio de teste em português.
"""

import asyncio
from pathlib import Path

try:
    import edge_tts
except ImportError:
    print("edge-tts não instalado. Execute: pip install edge-tts")
    exit(1)


async def gerar_audio_teste():
    """Gera arquivo de áudio de teste em português."""
    texto = "Olá, este é um teste de transcrição em português. O assistente virtual está funcionando corretamente."
    output_path = Path(__file__).parent / "audio_test.wav"
    
    print(f"Gerando áudio de teste: {output_path}")
    
    # Usa voz em português do Brasil
    communicate = edge_tts.Communicate(texto, voice="pt-BR-FranciscaNeural")
    await communicate.save(str(output_path))
    
    print(f"✓ Áudio de teste criado: {output_path}")


if __name__ == "__main__":
    asyncio.run(gerar_audio_teste())
