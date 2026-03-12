"""
conftest.py — Configuração global de testes para pytest.

Define fixtures compartilhadas e configuração de ambiente.
"""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Configura variáveis de ambiente para testes antes de importar módulos.
    
    Usa Ollama como provider padrão para evitar necessidade de API keys.
    """
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["OLLAMA_MODEL"] = "gemma3:4b-it-qat"
    os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"
    os.environ["ENV"] = "testing"
    
    yield
    
    # Cleanup após todos os testes
    os.environ.pop("LLM_PROVIDER", None)
    os.environ.pop("OLLAMA_MODEL", None)
    os.environ.pop("ENV", None)
