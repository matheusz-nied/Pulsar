"""
web.py — Tools de busca e navegação web com arquitetura de provider pattern.

Responsável por:
- Busca na web via API (Brave Search ou DuckDuckGo como fallback)
- Scraping de páginas com whitelist de domínios
- Resumo de conteúdo web
- Arquitetura trocável de providers de busca
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from backend.core.logging_config import log_api_call, log_tool_call


# ============================================================================
# WHITELIST DE DOMÍNIOS SEGUROS
# ============================================================================

WHITELIST_DOMINIOS = [
    "wikipedia.org",
    "g1.globo.com",
    "bbc.com",
    "reuters.com",
    "weather.com",
    "openweathermap.org",
    "google.com",
]


# ============================================================================
# INTERFACE BASE: SearchProvider
# ============================================================================

class SearchProvider(ABC):
    """Interface abstrata para providers de busca web."""

    @abstractmethod
    async def buscar(self, query: str, max_resultados: int) -> list[dict[str, str]]:
        """
        Realiza busca e retorna lista de resultados padronizados.

        Args:
            query: Termo de busca.
            max_resultados: Número máximo de resultados a retornar.

        Returns:
            Lista de dicts com campos: title, url, description.
        """
        pass


# ============================================================================
# IMPLEMENTAÇÃO: BraveSearchProvider
# ============================================================================

class BraveSearchProvider(SearchProvider):
    """Provider de busca usando Brave Search API."""

    def __init__(self, api_key: str):
        """
        Inicializa o provider do Brave Search.

        Args:
            api_key: Chave de API do Brave Search.
        """
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    @log_api_call
    async def buscar(self, query: str, max_resultados: int) -> list[dict[str, str]]:
        """Realiza busca usando Brave Search API."""
        try:
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            }
            params = {
                "q": query,
                "count": max_resultados,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    self.base_url,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

            resultados = []
            for item in data.get("web", {}).get("results", []):
                resultados.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                })

            logger.info(f"BraveSearch: {len(resultados)} resultados para '{query}'")
            return resultados

        except Exception as e:
            logger.error(f"Erro no BraveSearchProvider: {e}")
            return []


# ============================================================================
# IMPLEMENTAÇÃO: DuckDuckGoProvider (Fallback Gratuito)
# ============================================================================

class DuckDuckGoProvider(SearchProvider):
    """Provider de busca usando DuckDuckGo (sem necessidade de API key)."""

    def __init__(self):
        """Inicializa o provider do DuckDuckGo."""
        self.base_url = "https://api.duckduckgo.com/"

    @log_api_call
    async def buscar(self, query: str, max_resultados: int) -> list[dict[str, str]]:
        """Realiza busca usando DuckDuckGo API."""
        try:
            params = {
                "q": query,
                "format": "json",
                "no_html": "1",
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()

            resultados = []

            # DuckDuckGo retorna Related Topics
            for topic in data.get("RelatedTopics", [])[:max_resultados]:
                if isinstance(topic, dict) and "Text" in topic:
                    resultados.append({
                        "title": topic.get("Text", "")[:100],
                        "url": topic.get("FirstURL", ""),
                        "description": topic.get("Text", ""),
                    })

            # Se não houver Related Topics, tenta Abstract
            if not resultados and data.get("Abstract"):
                resultados.append({
                    "title": data.get("Heading", query),
                    "url": data.get("AbstractURL", ""),
                    "description": data.get("Abstract", ""),
                })

            logger.info(f"DuckDuckGo: {len(resultados)} resultados para '{query}'")
            return resultados

        except Exception as e:
            logger.error(f"Erro no DuckDuckGoProvider: {e}")
            return []


# ============================================================================
# SERVIÇO DE BUSCA COM DETECÇÃO AUTOMÁTICA
# ============================================================================

class SearchService:
    """
    Serviço de busca que detecta automaticamente qual provider usar.
    Permite trocar providers em runtime.
    """

    def __init__(self):
        """Inicializa o serviço com detecção automática de provider."""
        brave_key = os.getenv("BRAVE_SEARCH_API_KEY")
        
        if brave_key:
            self.provider = BraveSearchProvider(brave_key)
            logger.info("SearchService usando BraveSearchProvider")
        else:
            self.provider = DuckDuckGoProvider()
            logger.info("SearchService usando DuckDuckGoProvider (fallback gratuito)")

    def trocar_provider(self, provider: SearchProvider) -> None:
        """
        Permite trocar provider em runtime.

        Args:
            provider: Novo provider a ser usado.
        """
        self.provider = provider
        logger.info(f"Provider alterado para {provider.__class__.__name__}")

    async def buscar(self, query: str, max_resultados: int = 3) -> str:
        """
        Retorna resultados formatados como string para o LLM.

        Args:
            query: Termo de busca.
            max_resultados: Número máximo de resultados (padrão: 3).

        Returns:
            String formatada com os resultados da busca.
        """
        try:
            resultados = await self.provider.buscar(query, max_resultados)
            
            if not resultados:
                return "Nenhum resultado encontrado."

            # Formatar para texto legível pelo LLM
            texto = "\n\n".join([
                f"**{r['title']}**\n{r['url']}\n{r.get('description', '')}"
                for r in resultados
            ])
            return texto

        except Exception as e:
            logger.error(f"Erro na busca web: {e}")
            return f"Erro ao buscar: {str(e)}"


# ============================================================================
# FUNÇÃO DE RESUMO DE PÁGINA COM WHITELIST
# ============================================================================

async def resumir_pagina(url: str) -> str:
    """
    Faz fetch de uma página e retorna um resumo do conteúdo.
    Apenas domínios na whitelist são permitidos.

    Args:
        url: URL da página a ser acessada.

    Returns:
        Resumo do conteúdo da página (primeiros 2000 caracteres).
    """
    try:
        # Verificar se domínio está na whitelist
        parsed = urlparse(url)
        dominio = parsed.netloc.lower()
        
        if not any(d in dominio for d in WHITELIST_DOMINIOS):
            logger.warning(f"Domínio {dominio} não está na whitelist")
            return f"Erro: Domínio {dominio} não está na lista de domínios permitidos."

        # Fazer fetch do HTML
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            html = response.text

        # Extrair texto relevante
        soup = BeautifulSoup(html, "html.parser")
        
        # Remover scripts, styles e outros elementos não relevantes
        for elemento in soup(["script", "style", "nav", "header", "footer"]):
            elemento.decompose()

        # Extrair texto limpo
        texto = soup.get_text(separator="\n", strip=True)
        
        # Limpar linhas vazias excessivas
        linhas = [linha for linha in texto.split("\n") if linha.strip()]
        texto_limpo = "\n".join(linhas)

        # Retornar primeiros 2000 caracteres
        resumo = texto_limpo[:2000]
        
        logger.info(f"Página resumida: {url} ({len(resumo)} caracteres)")
        return resumo

    except Exception as e:
        logger.error(f"Erro ao resumir página {url}: {e}")
        return f"Erro ao acessar página: {str(e)}"


# ============================================================================
# INSTÂNCIA GLOBAL E FUNÇÃO DE CONVENIÊNCIA
# ============================================================================

# Instância global do serviço de busca
search_service = SearchService()


@log_tool_call
async def buscar_web(query: str, max_resultados: int = 3) -> str:
    """
    Função de conveniência para buscar na web.
    Usa o SearchService global configurado automaticamente.

    Args:
        query: Termo de busca.
        max_resultados: Número máximo de resultados (padrão: 3).

    Returns:
        String formatada com os resultados da busca.
    """
    return await search_service.buscar(query, max_resultados)
