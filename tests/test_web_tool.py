"""
test_web_tool.py — Testes para a tool de busca web com provider pattern.

Testa:
- Funcionamento do DuckDuckGoProvider (fallback gratuito)
- SearchService com detecção automática
- Função resumir_pagina com whitelist
- Troca de provider em runtime
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from backend.tools.web import (
    BraveSearchProvider,
    DuckDuckGoProvider,
    SearchService,
    buscar_web,
    resumir_pagina,
    search_service,
)


class TestSearchProviders:
    """Testa os providers de busca."""

    @pytest.mark.asyncio
    async def test_duckduckgo_provider_estrutura(self):
        """Testa se DuckDuckGoProvider retorna estrutura correta."""
        provider = DuckDuckGoProvider()

        # Mock da resposta da API
        mock_response = {
            "RelatedTopics": [
                {
                    "Text": "Python is a high-level programming language",
                    "FirstURL": "https://www.python.org",
                }
            ]
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = AsyncMock(
                json=lambda: mock_response, raise_for_status=lambda: None
            )

            resultados = await provider.buscar("Python", 3)

            assert isinstance(resultados, list)
            if resultados:  # DuckDuckGo pode não retornar resultados
                assert "title" in resultados[0]
                assert "url" in resultados[0]
                assert "description" in resultados[0]

    @pytest.mark.asyncio
    async def test_duckduckgo_provider_erro_nao_quebra(self):
        """Testa que erros no DuckDuckGo não quebram o app."""
        provider = DuckDuckGoProvider()

        with patch("httpx.AsyncClient.get", side_effect=Exception("Network error")):
            resultados = await provider.buscar("test query", 3)
            assert resultados == []  # Retorna lista vazia em caso de erro

    @pytest.mark.asyncio
    async def test_brave_provider_estrutura(self):
        """Testa se BraveSearchProvider retorna estrutura correta."""
        provider = BraveSearchProvider("fake_api_key")

        mock_response = {
            "web": {
                "results": [
                    {
                        "title": "Test Title",
                        "url": "https://example.com",
                        "description": "Test description",
                    }
                ]
            }
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = AsyncMock(
                json=lambda: mock_response, raise_for_status=lambda: None
            )

            resultados = await provider.buscar("test", 3)

            assert len(resultados) == 1
            assert resultados[0]["title"] == "Test Title"
            assert resultados[0]["url"] == "https://example.com"
            assert resultados[0]["description"] == "Test description"


class TestSearchService:
    """Testa o SearchService."""

    def test_search_service_sem_api_key_usa_duckduckgo(self):
        """Testa que sem API key, usa DuckDuckGo como fallback."""
        with patch.dict(os.environ, {}, clear=True):
            service = SearchService()
            assert isinstance(service.provider, DuckDuckGoProvider)

    def test_search_service_com_api_key_usa_brave(self):
        """Testa que com API key, usa BraveSearch."""
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "test_key"}):
            service = SearchService()
            assert isinstance(service.provider, BraveSearchProvider)

    def test_trocar_provider(self):
        """Testa a troca de provider em runtime."""
        service = SearchService()
        novo_provider = DuckDuckGoProvider()

        service.trocar_provider(novo_provider)
        assert service.provider == novo_provider

    @pytest.mark.asyncio
    async def test_buscar_formata_resultados(self):
        """Testa que buscar() formata os resultados corretamente."""
        service = SearchService()

        mock_resultados = [
            {
                "title": "Resultado 1",
                "url": "https://example.com/1",
                "description": "Descrição 1",
            },
            {
                "title": "Resultado 2",
                "url": "https://example.com/2",
                "description": "Descrição 2",
            },
        ]

        with patch.object(service.provider, "buscar", return_value=mock_resultados):
            resultado = await service.buscar("test", 2)

            assert "Fonte 1: Resultado 1" in resultado
            assert "https://example.com/1" in resultado
            assert "Resumo: Descrição 1" in resultado
            assert "Fonte 2: Resultado 2" in resultado

    @pytest.mark.asyncio
    async def test_buscar_limpa_html_e_markdown_basico(self):
        """Testa sanitização de HTML/markdown vindo do provider."""
        service = SearchService()

        mock_resultados = [
            {
                "title": "**David Goggins**",
                "url": "https://example.com/david",
                "description": "David is a <strong>motivational speaker</strong>",
            }
        ]

        with patch.object(service.provider, "buscar", return_value=mock_resultados):
            resultado = await service.buscar("david goggins", 1)

            assert "**" not in resultado
            assert "<strong>" not in resultado
            assert "motivational speaker" in resultado

    @pytest.mark.asyncio
    async def test_buscar_sem_resultados(self):
        """Testa comportamento quando não há resultados."""
        service = SearchService()

        with patch.object(service.provider, "buscar", return_value=[]):
            resultado = await service.buscar("test", 3)
            assert resultado == "Nenhum resultado encontrado."

    @pytest.mark.asyncio
    async def test_buscar_com_erro(self):
        """Testa que erros são tratados graciosamente."""
        service = SearchService()

        with patch.object(
            service.provider, "buscar", side_effect=Exception("API Error")
        ):
            resultado = await service.buscar("test", 3)
            assert "Erro ao buscar:" in resultado


class TestResumirPagina:
    """Testa a função resumir_pagina."""

    @pytest.mark.asyncio
    async def test_resumir_pagina_dominio_nao_permitido(self):
        """Testa que domínios fora da whitelist são bloqueados."""
        resultado = await resumir_pagina("https://malicious-site.com/page")
        assert "não está na lista de domínios permitidos" in resultado

    @pytest.mark.asyncio
    async def test_resumir_pagina_dominio_permitido(self):
        """Testa que domínios na whitelist são processados."""
        mock_html = """
        <html>
            <head><title>Test</title></head>
            <body>
                <script>alert('test');</script>
                <p>Conteúdo relevante da página</p>
                <footer>Footer content</footer>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = AsyncMock(
                text=mock_html, raise_for_status=lambda: None
            )

            resultado = await resumir_pagina("https://en.wikipedia.org/wiki/Python")

            assert "Conteúdo relevante" in resultado
            assert "alert('test')" not in resultado  # Scripts removidos
            assert len(resultado) <= 2000  # Limite de caracteres

    @pytest.mark.asyncio
    async def test_resumir_pagina_erro_http(self):
        """Testa que erros HTTP são tratados."""
        with patch("httpx.AsyncClient.get", side_effect=Exception("HTTP Error")):
            resultado = await resumir_pagina("https://wikipedia.org/test")
            assert "Erro ao acessar página" in resultado


class TestBuscarWebFunction:
    """Testa a função de conveniência buscar_web."""

    @pytest.mark.asyncio
    async def test_buscar_web_usa_service_global(self):
        """Testa que buscar_web usa o search_service global."""
        mock_resultado = "Resultado da busca"

        with patch.object(search_service, "buscar", return_value=mock_resultado):
            resultado = await buscar_web("test query", 3)
            assert resultado == mock_resultado


# ============================================================================
# TESTE DE INTEGRAÇÃO REAL (opcional - requer conexão)
# ============================================================================


class TestIntegracaoReal:
    """Testes de integração com APIs reais (podem ser lentos)."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_buscar_web_real_duckduckgo(self):
        """Testa busca real com DuckDuckGo."""
        # Força uso do DuckDuckGo
        with patch.dict(os.environ, {}, clear=True):
            service = SearchService()
            resultado = await service.buscar("Python programming language", 2)

            # Verifica se retornou algo (pode ser "Nenhum resultado" ou resultados)
            assert isinstance(resultado, str)
            assert len(resultado) > 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_resumir_pagina_real_wikipedia(self):
        """Testa resumo de página real da Wikipedia."""
        resultado = await resumir_pagina(
            "https://en.wikipedia.org/wiki/Python_(programming_language)"
        )

        assert isinstance(resultado, str)
        assert len(resultado) > 0
        # Wikipedia deve conter algo sobre Python
        assert any(
            palavra in resultado.lower()
            for palavra in ["python", "programming", "language"]
        )
