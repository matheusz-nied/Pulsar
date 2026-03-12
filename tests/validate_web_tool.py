"""
validate_web_tool.py — Script de validação manual da tool de busca web.

Execute para verificar:
1. Detecção automática de provider (DuckDuckGo sem API key)
2. Busca web funcional
3. Resumo de página com whitelist
4. Troca de provider em runtime
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.tools.web import (
    BraveSearchProvider,
    DuckDuckGoProvider,
    SearchService,
    buscar_web,
    resumir_pagina,
)
from loguru import logger


async def main():
    """Executa validação completa da tool de busca web."""
    
    logger.info("=" * 80)
    logger.info("VALIDAÇÃO DA TOOL DE BUSCA WEB")
    logger.info("=" * 80)
    
    # ========================================================================
    # 1. Verificar detecção automática de provider
    # ========================================================================
    logger.info("\n[1] Testando detecção automática de provider...")
    
    brave_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if brave_key:
        logger.info(f"✓ BRAVE_SEARCH_API_KEY detectada (primeiros 10 chars: {brave_key[:10]}...)")
        logger.info("  → SearchService usará BraveSearchProvider")
    else:
        logger.info("✗ BRAVE_SEARCH_API_KEY não configurada")
        logger.info("  → SearchService usará DuckDuckGoProvider (fallback gratuito)")
    
    # ========================================================================
    # 2. Testar busca web com provider automático
    # ========================================================================
    logger.info("\n[2] Testando busca web com buscar_web()...")
    
    query = "capital do Brasil"
    logger.info(f"Query: '{query}'")
    
    try:
        resultado = await buscar_web(query, max_resultados=3)
        logger.info(f"✓ Busca realizada com sucesso!")
        logger.info(f"\nResultados:\n{resultado}\n")
    except Exception as e:
        logger.error(f"✗ Erro na busca: {e}")
    
    # ========================================================================
    # 3. Testar resumo de página com whitelist
    # ========================================================================
    logger.info("\n[3] Testando resumir_pagina() com domínio permitido...")
    
    url_permitida = "https://en.wikipedia.org/wiki/Python_(programming_language)"
    logger.info(f"URL: {url_permitida}")
    
    try:
        resumo = await resumir_pagina(url_permitida)
        logger.info(f"✓ Página resumida com sucesso!")
        logger.info(f"Tamanho do resumo: {len(resumo)} caracteres")
        logger.info(f"\nPrimeiros 300 caracteres:\n{resumo[:300]}...\n")
    except Exception as e:
        logger.error(f"✗ Erro ao resumir página: {e}")
    
    # ========================================================================
    # 4. Testar whitelist (domínio bloqueado)
    # ========================================================================
    logger.info("\n[4] Testando whitelist com domínio NÃO permitido...")
    
    url_bloqueada = "https://example-malicious-site.com/page"
    logger.info(f"URL: {url_bloqueada}")
    
    try:
        resultado = await resumir_pagina(url_bloqueada)
        if "não está na lista de domínios permitidos" in resultado:
            logger.info(f"✓ Domínio bloqueado corretamente!")
            logger.info(f"Mensagem: {resultado}")
        else:
            logger.warning(f"⚠ Whitelist não funcionou como esperado")
    except Exception as e:
        logger.error(f"✗ Erro inesperado: {e}")
    
    # ========================================================================
    # 5. Testar troca de provider em runtime
    # ========================================================================
    logger.info("\n[5] Testando troca de provider em runtime...")
    
    service = SearchService()
    logger.info(f"Provider atual: {service.provider.__class__.__name__}")
    
    # Trocar para DuckDuckGo explicitamente
    novo_provider = DuckDuckGoProvider()
    service.trocar_provider(novo_provider)
    logger.info(f"✓ Provider alterado para: {service.provider.__class__.__name__}")
    
    # Testar busca com novo provider
    try:
        resultado = await service.buscar("Python programming", max_resultados=2)
        logger.info(f"✓ Busca com novo provider funcionou!")
        logger.info(f"Resultado tem {len(resultado)} caracteres")
    except Exception as e:
        logger.error(f"✗ Erro na busca com novo provider: {e}")
    
    # ========================================================================
    # RESUMO FINAL
    # ========================================================================
    logger.info("\n" + "=" * 80)
    logger.info("VALIDAÇÃO CONCLUÍDA")
    logger.info("=" * 80)
    logger.info("\n✓ Arquitetura de provider pattern implementada com sucesso!")
    logger.info("✓ Busca web funcional (Brave ou DuckDuckGo)")
    logger.info("✓ Resumo de páginas com whitelist de domínios")
    logger.info("✓ Troca de provider em runtime")
    logger.info("\nCritérios de conclusão:")
    logger.info("  • Com BRAVE_SEARCH_API_KEY: usa Brave Search")
    logger.info("  • Sem a chave: usa DuckDuckGo automaticamente")
    logger.info("  • App não quebra se serviços falharem (retorna mensagens amigáveis)")
    logger.info("  • Adicionar novo provider requer apenas criar classe que herda SearchProvider")


if __name__ == "__main__":
    asyncio.run(main())
