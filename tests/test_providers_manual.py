"""
test_providers_manual.py — Teste manual dos providers de busca.

Execute para testar:
1. DuckDuckGoProvider (sem necessidade de API key)
2. BraveSearchProvider (requer BRAVE_SEARCH_API_KEY no .env)
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from backend.tools.web import BraveSearchProvider, DuckDuckGoProvider
from loguru import logger


async def testar_duckduckgo():
    """Testa o DuckDuckGoProvider."""
    logger.info("\n" + "=" * 80)
    logger.info("TESTANDO DUCKDUCKGO PROVIDER (Gratuito)")
    logger.info("=" * 80)
    
    provider = DuckDuckGoProvider()
    
    queries = [
        "Python programming language",
        "capital do Brasil",
        "weather today",
    ]
    
    for query in queries:
        logger.info(f"\n🔍 Query: '{query}'")
        try:
            resultados = await provider.buscar(query, max_resultados=3)
            
            if resultados:
                logger.success(f"✓ {len(resultados)} resultados encontrados:")
                for i, r in enumerate(resultados, 1):
                    logger.info(f"\n  [{i}] {r['title'][:80]}")
                    logger.info(f"      URL: {r['url']}")
                    logger.info(f"      Desc: {r['description'][:100]}...")
            else:
                logger.warning("⚠ Nenhum resultado retornado (normal para algumas queries no DuckDuckGo)")
                
        except Exception as e:
            logger.error(f"✗ Erro: {e}")


async def testar_brave():
    """Testa o BraveSearchProvider."""
    logger.info("\n" + "=" * 80)
    logger.info("TESTANDO BRAVE SEARCH PROVIDER (Requer API Key)")
    logger.info("=" * 80)
    
    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    
    if not api_key:
        logger.warning("\n⚠ BRAVE_SEARCH_API_KEY não encontrada no .env")
        logger.info("Para testar o Brave Search:")
        logger.info("1. Obtenha uma API key em: https://brave.com/search/api/")
        logger.info("2. Adicione no .env: BRAVE_SEARCH_API_KEY=sua_chave_aqui")
        logger.info("3. Execute este script novamente")
        return
    
    logger.info(f"✓ API Key encontrada: {api_key[:10]}...{api_key[-4:]}")
    
    provider = BraveSearchProvider(api_key)
    
    queries = [
        "Python programming language",
        "capital do Brasil",
        "weather today",
    ]
    
    for query in queries:
        logger.info(f"\n🔍 Query: '{query}'")
        try:
            resultados = await provider.buscar(query, max_resultados=3)
            
            if resultados:
                logger.success(f"✓ {len(resultados)} resultados encontrados:")
                for i, r in enumerate(resultados, 1):
                    logger.info(f"\n  [{i}] {r['title']}")
                    logger.info(f"      URL: {r['url']}")
                    logger.info(f"      Desc: {r['description'][:100]}...")
            else:
                logger.warning("⚠ Nenhum resultado retornado")
                
        except Exception as e:
            logger.error(f"✗ Erro: {e}")
            if "401" in str(e) or "403" in str(e):
                logger.error("   → API key inválida ou sem permissão")
            elif "429" in str(e):
                logger.error("   → Limite de requisições excedido")


async def main():
    """Executa testes de ambos os providers."""
    logger.info("\n🧪 TESTE MANUAL DOS PROVIDERS DE BUSCA WEB\n")
    
    # Testar DuckDuckGo (sempre disponível)
    await testar_duckduckgo()
    
    # Testar Brave (se API key disponível)
    await testar_brave()
    
    logger.info("\n" + "=" * 80)
    logger.info("TESTES CONCLUÍDOS")
    logger.info("=" * 80)
    logger.info("\n📝 Resumo:")
    logger.info("  • DuckDuckGo: Gratuito, sem necessidade de configuração")
    logger.info("  • Brave Search: Requer BRAVE_SEARCH_API_KEY no .env")
    logger.info("\n💡 Dica: O SearchService escolhe automaticamente o melhor provider disponível")


if __name__ == "__main__":
    asyncio.run(main())
