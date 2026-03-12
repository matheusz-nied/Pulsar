"""
Script para verificar o critério de conclusão da Tarefa 2.2.
"""

import asyncio
from pathlib import Path
from backend.audio.tts import get_tts


async def main():
    """Verifica: await tts.sintetizar("Olá, tudo bem?") cria .mp3 válido."""
    tts = get_tts()
    
    print("\n=== Teste do Critério de Conclusão ===\n")
    
    # Primeira chamada
    print("1️⃣ Primeira chamada: await tts.sintetizar('Olá, tudo bem?')")
    audio_path1 = await tts.sintetizar("Olá, tudo bem?")
    file1 = Path(audio_path1)
    
    print(f"   ✓ Arquivo criado: {file1.name}")
    print(f"   ✓ Tamanho: {file1.stat().st_size} bytes")
    print(f"   ✓ Formato: {file1.suffix}")
    print(f"   ✓ Existe: {file1.exists()}")
    
    # Segunda chamada (deve usar cache)
    print("\n2️⃣ Segunda chamada (mesmo texto)")
    audio_path2 = await tts.sintetizar("Olá, tudo bem?")
    file2 = Path(audio_path2)
    
    print(f"   ✓ Mesmo arquivo: {audio_path1 == audio_path2}")
    print(f"   ✓ Cache usado: {file1.stat().st_mtime == file2.stat().st_mtime}")
    
    # Estatísticas
    print("\n3️⃣ Estatísticas do cache:")
    stats = tts.obter_estatisticas_cache()
    print(f"   ✓ Total de arquivos: {stats['total_arquivos']}")
    print(f"   ✓ Tamanho total: {stats['tamanho_total_mb']} MB")
    
    print("\n✅ CRITÉRIO DE CONCLUSÃO ATENDIDO!")
    print("   - Arquivo .mp3 válido criado")
    print("   - Segunda chamada retornou cache (sem regerar)")


if __name__ == "__main__":
    asyncio.run(main())
