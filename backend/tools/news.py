"""
news.py — Tools de busca de notícias com arquitetura de provider pattern.

Responsável por:
- Busca de notícias via NewsAPI, RSS feeds e Alpha Vantage
- Roteamento inteligente por categoria
- Formatação de resultados para injeção no contexto do LLM
- Fallback gracioso quando providers não estão configurados
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, cast

import feedparser
import httpx
from loguru import logger

from backend.core.logging_config import log_api_call


# ============================================================================
# INTERFACE BASE: NewsProvider
# ============================================================================

class NewsProvider(ABC):
    """Interface abstrata para providers de notícias."""

    @abstractmethod
    async def buscar(self, query: str, categoria: str, max_resultados: int) -> list[dict[str, Any]]:
        """
        Retorna lista de notícias padronizadas.

        Args:
            query: Termo de busca.
            categoria: Categoria de notícias.
            max_resultados: Número máximo de resultados.

        Returns:
            Lista de dicts com campos: title, description, url, source, published_at.
        """
        pass


# ============================================================================
# IMPLEMENTAÇÃO: NewsApiProvider
# ============================================================================

class NewsApiProvider(NewsProvider):
    """Provider de notícias usando NewsAPI (https://newsapi.org)."""

    CATEGORIAS_FONTES: dict[str, str] = {
        "ia_tech": "techcrunch,the-verge,wired,ars-technica,hacker-news",
        "financas": "bloomberg,financial-times,the-wall-street-journal",
        "economia": "reuters,bbc-news,associated-press",
        "software": "techcrunch,hacker-news,ars-technica",
    }

    def __init__(self, api_key: str) -> None:
        """
        Inicializa o provider da NewsAPI.

        Args:
            api_key: Chave de API do NewsAPI.
        """
        self.api_key = api_key
        self.base_url = "https://newsapi.org/v2/everything"

    @log_api_call
    async def buscar(self, query: str, categoria: str, max_resultados: int) -> list[dict[str, Any]]:
        """Busca notícias via NewsAPI."""
        try:
            # Mapear categorias do agente para categorias internas
            categoria_map: dict[str, str] = {
                "ia": "ia_tech",
                "tech": "ia_tech",
                "software": "software",
                "financas": "financas",
                "economia": "economia",
            }
            cat_interna = categoria_map.get(categoria, "ia_tech")
            fontes = self.CATEGORIAS_FONTES.get(cat_interna)

            params: dict[str, Any] = {
                "apiKey": self.api_key,
                "pageSize": max_resultados,
                "sortBy": "publishedAt",
            }

            if fontes:
                params["sources"] = fontes
            if query:
                params["q"] = query
            elif not fontes:
                # Sem fontes e sem query, busca genérica por tecnologia
                params["q"] = categoria

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.base_url, params=params)

                # Fallback: se fonte não disponível no plano gratuito, busca por keyword
                if response.status_code == 426 or (
                    response.status_code == 200
                    and response.json().get("status") == "error"
                ):
                    logger.warning("NewsAPI: fontes indisponíveis no plano gratuito, buscando por keyword")
                    params.pop("sources", None)
                    params["q"] = query or categoria
                    response = await client.get(self.base_url, params=params)

                response.raise_for_status()
                data = response.json()

            resultados: list[dict[str, Any]] = []
            for article in data.get("articles", []):
                resultados.append({
                    "title": article.get("title", ""),
                    "description": article.get("description", ""),
                    "url": article.get("url", ""),
                    "source": article.get("source", {}).get("name", ""),
                    "published_at": article.get("publishedAt", ""),
                })

            logger.info(f"NewsAPI: {len(resultados)} resultados para categoria='{categoria}', query='{query}'")
            return resultados

        except Exception as e:
            logger.error(f"Erro no NewsApiProvider: {e}")
            return []


# ============================================================================
# IMPLEMENTAÇÃO: RSSProvider (Fontes Brasileiras)
# ============================================================================

class RSSProvider(NewsProvider):
    """Provider de notícias via RSS feeds (sem necessidade de chave de API)."""

    FEEDS_BR: dict[str, str] = {
        "financas_br": "https://valor.globo.com/rss/home",
        "economia_br": "https://exame.com/feed",
        "tech_br": "https://olhardigital.com.br/feed",
    }

    @log_api_call
    async def buscar(self, query: str, categoria: str, max_resultados: int) -> list[dict[str, Any]]:
        """Busca notícias via RSS feeds brasileiros."""
        try:
            feed_url = self.FEEDS_BR.get(categoria)
            if not feed_url:
                # Se categoria não mapeada, tenta tech_br como fallback
                feed_url = self.FEEDS_BR.get("tech_br", "")
                logger.info(f"RSS: categoria '{categoria}' não mapeada, usando tech_br como fallback")

            if not feed_url:
                return []

            # feedparser é síncrono, mas rápido o suficiente para RSS
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(feed_url, follow_redirects=True)
                response.raise_for_status()
                content = response.text

            feed = feedparser.parse(content)
            feed_meta = cast(dict[str, Any], feed.feed)

            resultados: list[dict[str, Any]] = []
            for entry in feed.entries[:max_resultados]:
                entry_data = cast(dict[str, Any], entry)
                published_raw = entry_data.get("published", entry_data.get("updated", ""))
                published = str(published_raw) if published_raw is not None else ""
                # Tentar formatar a data se possível
                published_parsed = entry_data.get("published_parsed")
                if isinstance(published_parsed, tuple) and len(published_parsed) >= 6:
                    try:
                        published = datetime(
                            int(published_parsed[0]),
                            int(published_parsed[1]),
                            int(published_parsed[2]),
                            int(published_parsed[3]),
                            int(published_parsed[4]),
                            int(published_parsed[5]),
                        ).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        pass

                description_raw = entry_data.get("summary", entry_data.get("description", ""))
                description = str(description_raw) if description_raw is not None else ""
                # Limpar HTML básico do description
                if "<" in description:
                    from html import unescape
                    import re
                    description = re.sub(r"<[^>]+>", "", unescape(description))
                description = description[:300]

                source_raw = feed_meta.get("title", "RSS")
                source = str(source_raw) if source_raw is not None else "RSS"

                resultados.append({
                    "title": str(entry_data.get("title", "")),
                    "description": description,
                    "url": str(entry_data.get("link", "")),
                    "source": source,
                    "published_at": published,
                })

            # Filtrar por query se fornecida
            if query:
                query_lower = query.lower()
                resultados = [
                    r for r in resultados
                    if query_lower in r["title"].lower() or query_lower in r["description"].lower()
                ]

            logger.info(f"RSS: {len(resultados)} resultados para categoria='{categoria}', query='{query}'")
            return resultados

        except Exception as e:
            logger.error(f"Erro no RSSProvider: {e}")
            return []


# ============================================================================
# IMPLEMENTAÇÃO: AlphaVantageProvider (Finanças com Sentiment)
# ============================================================================

class AlphaVantageProvider(NewsProvider):
    """Provider de notícias financeiras com análise de sentimento via Alpha Vantage."""

    def __init__(self, api_key: str) -> None:
        """
        Inicializa o provider do Alpha Vantage.

        Args:
            api_key: Chave de API do Alpha Vantage.
        """
        self.api_key = api_key
        self.base_url = "https://www.alphavantage.co/query"

    @log_api_call
    async def buscar(self, query: str, categoria: str, max_resultados: int) -> list[dict[str, Any]]:
        """Busca notícias financeiras com sentiment via Alpha Vantage."""
        try:
            params: dict[str, Any] = {
                "function": "NEWS_SENTIMENT",
                "apikey": self.api_key,
                "topics": "finance",
                "limit": max_resultados,
            }

            if query:
                params["tickers"] = query

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()

            resultados: list[dict[str, Any]] = []
            for item in data.get("feed", [])[:max_resultados]:
                # Classificar sentiment
                score = float(item.get("overall_sentiment_score", 0))
                if score >= 0.15:
                    sentiment_label = "Bullish"
                elif score <= -0.15:
                    sentiment_label = "Bearish"
                else:
                    sentiment_label = "Neutral"

                resultados.append({
                    "title": item.get("title", ""),
                    "description": item.get("summary", "")[:300],
                    "url": item.get("url", ""),
                    "source": item.get("source", ""),
                    "published_at": item.get("time_published", ""),
                    "sentiment_score": score,
                    "sentiment_label": sentiment_label,
                })

            logger.info(f"AlphaVantage: {len(resultados)} resultados para query='{query}'")
            return resultados

        except Exception as e:
            logger.error(f"Erro no AlphaVantageProvider: {e}")
            return []


# ============================================================================
# SERVIÇO DE NOTÍCIAS COM ROTEAMENTO POR CATEGORIA
# ============================================================================

class NewsService:
    """
    Serviço de notícias que detecta automaticamente providers disponíveis
    e roteia buscas por categoria para o provider mais apropriado.
    """

    def __init__(self) -> None:
        """Inicializa o serviço com detecção automática de providers."""
        self.providers: dict[str, NewsProvider] = {}

        news_api_key = os.getenv("NEWS_API_KEY")
        if news_api_key:
            self.providers["newsapi"] = NewsApiProvider(news_api_key)
            logger.info("NewsApiProvider disponível")

        alpha_key = os.getenv("ALPHA_VANTAGE_KEY")
        if alpha_key:
            self.providers["alphavantage"] = AlphaVantageProvider(alpha_key)
            logger.info("AlphaVantageProvider disponível")

        # RSS sempre disponível (gratuito)
        self.providers["rss"] = RSSProvider()
        logger.info("RSSProvider disponível")

    async def buscar_por_categoria(
        self,
        categoria: str,
        query: str = "",
        max_resultados: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Roteia para o provider apropriado baseado na categoria.

        Args:
            categoria: Uma de: ia, tech, financas, economia, software, brasil, geral.
            query: Termo de busca opcional.
            max_resultados: Número máximo de resultados (padrão: 5).

        Returns:
            Lista de notícias padronizadas.
        """
        resultados: list[dict[str, Any]] = []

        try:
            if categoria in ["ia", "tech", "software"]:
                if "newsapi" in self.providers:
                    resultados = await self.providers["newsapi"].buscar(query, categoria, max_resultados)

            elif categoria == "financas":
                # Prefere Alpha Vantage se disponível (tem sentiment)
                if "alphavantage" in self.providers:
                    resultados = await self.providers["alphavantage"].buscar(query, categoria, max_resultados)
                elif "newsapi" in self.providers:
                    resultados = await self.providers["newsapi"].buscar(query, categoria, max_resultados)

            elif categoria == "economia":
                # Mescla NewsAPI + RSS
                if "newsapi" in self.providers:
                    news_api_results = await self.providers["newsapi"].buscar(
                        query, categoria, max_resultados // 2
                    )
                    resultados.extend(news_api_results)

                rss_results = await self.providers["rss"].buscar(query, "economia_br", max_resultados // 2)
                resultados.extend(rss_results)

            elif categoria == "brasil":
                # Apenas RSS (fontes brasileiras)
                resultados = await self.providers["rss"].buscar(query, "tech_br", max_resultados)

            else:  # "geral"
                # Tenta qualquer provider disponível
                for provider_name, provider in self.providers.items():
                    try:
                        results = await provider.buscar(query, categoria, max_resultados)
                        if results:
                            resultados = results
                            break
                    except Exception as e:
                        logger.warning(f"Provider {provider_name} falhou: {e}")
                        continue

        except Exception as e:
            logger.error(f"Erro ao buscar notícias: {e}")

        return resultados[:max_resultados]

    def formatar_para_llm(self, noticias: list[dict[str, Any]]) -> str:
        """
        Formata as notícias como texto estruturado para injetar no contexto do LLM.

        Args:
            noticias: Lista de notícias padronizadas.

        Returns:
            String formatada com as notícias.
        """
        if not noticias:
            return "Nenhuma notícia encontrada."

        linhas: list[str] = []
        for noticia in noticias:
            sentiment = ""
            if "sentiment_label" in noticia:
                sentiment = f" [{noticia['sentiment_label']}]"

            linha = (
                f"📰 [{noticia['source']}] {noticia['title']}{sentiment}\n"
                f"   {noticia.get('description', '')}\n"
                f"   {noticia.get('published_at', '')}\n"
            )
            linhas.append(linha)

        return "\n".join(linhas)


# ============================================================================
# INSTÂNCIA GLOBAL E FUNÇÃO DE CONVENIÊNCIA
# ============================================================================

# Instância global do serviço de notícias
news_service = NewsService()


async def buscar_noticias(categoria: str = "geral", query: str = "") -> str:
    """
    Busca notícias recentes.

    Args:
        categoria: Uma de: ia, tech, financas, economia, software, brasil, geral.
        query: Termo de busca opcional.

    Returns:
        String formatada com as notícias encontradas.
    """
    try:
        noticias = await news_service.buscar_por_categoria(categoria, query)
        return news_service.formatar_para_llm(noticias)
    except Exception as e:
        logger.error(f"Erro na tool buscar_noticias: {e}")
        return f"Não foi possível buscar notícias no momento: {str(e)}"
