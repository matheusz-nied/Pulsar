"""
test_fase1.py — Testes da Fase 1 (MVP de Texto).

Testa:
- Endpoints do FastAPI (/health, /conversar)
- SessionMemory e PersistentMemory
- Integração completa do fluxo de conversação
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from openai import APIError as OpenAIAPIError

from backend.agent.agent import (
    AgentResponse,
    ConversationAgent,
    _deve_responder_sem_tools,
)
from backend.agent.memory import PersistentMemory, SessionMemory


@pytest.fixture
def mock_llm_provider():
    """Mock do LLM provider para evitar chamadas reais à API."""
    # Mock do método processar do agent que já foi importado no main.py
    with patch(
        "backend.main.agent.processar", new_callable=AsyncMock
    ) as mock_processar:
        # Configura resposta padrão
        mock_processar.return_value = AgentResponse(
            resposta="Resposta mock para: teste",
            modelo_usado="mock-llm",
        )
        yield mock_processar


@pytest.fixture
def client():
    """Fixture do TestClient do FastAPI."""
    from backend.main import app

    return TestClient(app)


@pytest.fixture
def temp_session_memory():
    """Fixture de SessionMemory limpa para cada teste."""
    memory = SessionMemory()
    yield memory
    # Cleanup
    for session_id in memory.list_sessions():
        memory.clear_session(session_id)


@pytest.fixture
def temp_persistent_memory(tmp_path):
    """Fixture de PersistentMemory com arquivo temporário."""
    storage_file = tmp_path / "test_sessions.json"
    memory = PersistentMemory(storage_path=str(storage_file))
    yield memory
    # Cleanup automático pelo tmp_path


# --- Testes de Endpoints ---


def test_health(client):
    """Test 1: GET /health retorna 200 e status 'ok'."""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "components" in data
    assert data["components"]["llm_primary"] in {"online", "lazy"}
    assert data["components"]["memory"] == "online"


def test_conversar_sem_session(client, mock_llm_provider):
    """Test 2: POST /conversar sem session_id retorna resposta e gera session_id."""
    response = client.post(
        "/conversar",
        json={"mensagem": "Olá, como você está?"},
    )

    assert response.status_code == 200
    data = response.json()

    # Verifica que resposta foi gerada
    assert "resposta" in data
    assert len(data["resposta"]) > 0
    assert "Resposta mock para:" in data["resposta"]

    # Verifica que session_id foi gerado
    assert "session_id" in data
    assert len(data["session_id"]) > 0


def test_conversar_com_contexto(client, mock_llm_provider):
    """Test 3: Duas mensagens na mesma sessão mantêm contexto."""
    # Configura mock para retornar respostas diferentes
    respostas = [
        AgentResponse(
            resposta="Brasília é a capital do Brasil.",
            modelo_usado="mock-llm",
        ),
        AgentResponse(
            resposta="A população de Brasília é aproximadamente 3 milhões.",
            modelo_usado="mock-llm",
        ),
    ]
    mock_llm_provider.side_effect = respostas

    # Primeira mensagem
    response1 = client.post(
        "/conversar",
        json={"mensagem": "Qual é a capital do Brasil?"},
    )
    assert response1.status_code == 200
    data1 = response1.json()
    session_id = data1["session_id"]

    # Segunda mensagem na mesma sessão
    response2 = client.post(
        "/conversar",
        json={
            "mensagem": "E qual é a população?",
            "session_id": session_id,
        },
    )
    assert response2.status_code == 200
    data2 = response2.json()

    # Verifica que session_id foi mantido
    assert data2["session_id"] == session_id

    # Verifica que o agente foi chamado com histórico
    # Na segunda chamada, deve ter o histórico da primeira
    calls = mock_llm_provider.call_args_list
    assert len(calls) == 2

    # Segunda chamada deve ter histórico com 2 mensagens (user + assistant)
    # call_args retorna (args, kwargs) ou Mock.call(...)
    second_call = calls[1]
    historico = second_call[0][1]  # Segundo argumento posicional
    assert len(historico) >= 2  # Pelo menos user e assistant anteriores


def test_conversar_mensagem_vazia(client):
    """Test Extra: POST /conversar com mensagem vazia retorna 400."""
    response = client.post(
        "/conversar",
        json={"mensagem": ""},
    )

    assert response.status_code == 400
    assert "detail" in response.json()


def test_deve_responder_sem_tools_em_mensagem_social():
    """Perguntas sociais simples não devem entrar no tool calling."""
    assert _deve_responder_sem_tools("Quem é você?")
    assert _deve_responder_sem_tools("Oi")
    assert not _deve_responder_sem_tools("Quem é David Goggins?")
    assert not _deve_responder_sem_tools("Abra o Chrome")


# --- Testes de Memory ---


def test_memory_limit(temp_session_memory):
    """Test 4: SessionMemory mantém apenas MAX_HISTORY (20) mensagens."""
    session_id = "test_limit_session"

    # Adiciona 25 mensagens
    for i in range(25):
        temp_session_memory.add_message(session_id, "user", f"Mensagem {i + 1}")

    # Verifica que apenas 20 foram mantidas
    history = temp_session_memory.get_history(session_id)
    assert len(history) == temp_session_memory.MAX_HISTORY
    assert len(history) == 20

    # Verifica que as mais recentes foram mantidas
    assert history[0]["content"] == "Mensagem 6"  # 25 - 20 + 1 = 6
    assert history[-1]["content"] == "Mensagem 25"


def test_persistent_memory(temp_persistent_memory, temp_session_memory):
    """Test 5: Salvar e recarregar histórico do JSON."""
    session_id = "test_persistent_session"

    # Cria histórico
    messages = [
        {"role": "user", "content": "Primeira mensagem"},
        {"role": "assistant", "content": "Primeira resposta"},
        {"role": "user", "content": "Segunda mensagem"},
        {"role": "assistant", "content": "Segunda resposta"},
    ]

    # Adiciona ao SessionMemory
    for msg in messages:
        temp_session_memory.add_message(session_id, msg["role"], msg["content"])

    # Salva no disco
    history = temp_session_memory.get_history(session_id)
    temp_persistent_memory.save(session_id, history)

    # Verifica que arquivo foi criado
    assert temp_persistent_memory.storage_path.exists()

    # Limpa SessionMemory
    temp_session_memory.clear_session(session_id)
    assert len(temp_session_memory.get_history(session_id)) == 0

    # Recarrega do JSON
    loaded_history = temp_persistent_memory.load(session_id)

    # Valida que histórico foi restaurado corretamente
    assert len(loaded_history) == len(messages)
    assert loaded_history == messages


def test_persistent_memory_session_inexistente(temp_persistent_memory):
    """Test Extra: Carregar sessão inexistente retorna lista vazia."""
    history = temp_persistent_memory.load("session_nao_existe")
    assert history == []


def test_session_memory_list_sessions(temp_session_memory):
    """Test Extra: list_sessions() retorna todas as sessões ativas."""
    temp_session_memory.add_message("session1", "user", "msg1")
    temp_session_memory.add_message("session2", "user", "msg2")
    temp_session_memory.add_message("session3", "user", "msg3")

    sessions = temp_session_memory.list_sessions()
    assert len(sessions) == 3
    assert "session1" in sessions
    assert "session2" in sessions
    assert "session3" in sessions


def test_session_memory_clear(temp_session_memory):
    """Test Extra: clear_session() remove sessão."""
    session_id = "test_clear"
    temp_session_memory.add_message(session_id, "user", "mensagem")

    assert session_id in temp_session_memory.list_sessions()

    temp_session_memory.clear_session(session_id)

    assert session_id not in temp_session_memory.list_sessions()
    assert len(temp_session_memory.get_history(session_id)) == 0


# --- Teste de Integração Completa ---


def test_integracao_completa(client, mock_llm_provider):
    """Test 6: Fluxo completo de conversação com persistência."""
    # Simula respostas do LLM
    mock_llm_provider.side_effect = [
        AgentResponse(
            resposta="Python é uma linguagem de programação.",
            modelo_usado="mock-llm",
        ),
        AgentResponse(
            resposta="Sim, Python é muito popular para IA e Data Science.",
            modelo_usado="mock-llm",
        ),
    ]

    # Primeira mensagem
    response1 = client.post(
        "/conversar",
        json={"mensagem": "O que é Python?"},
    )
    data1 = response1.json()
    session_id = data1["session_id"]

    # Segunda mensagem
    response2 = client.post(
        "/conversar",
        json={"mensagem": "É popular?", "session_id": session_id},
    )
    data2 = response2.json()

    # Valida respostas
    assert "Python" in data1["resposta"]
    assert "popular" in data2["resposta"]
    assert data2["session_id"] == session_id

    # Verifica que histórico foi salvo (arquivo sessions.json deve existir)
    sessions_file = Path("backend/memory/sessions.json")
    if sessions_file.exists():
        with open(sessions_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
            # Verifica que a sessão foi salva
            assert session_id in saved_data
            assert len(saved_data[session_id]) == 4  # 2 user + 2 assistant


@pytest.mark.asyncio
async def test_processar_stream_aceita_eventos_com_namespace():
    """Aceita eventos `(namespace, mode, data)` emitidos pelo LangGraph."""
    agent = object.__new__(ConversationAgent)
    agent._verificar_confirmacao = AsyncMock(return_value=None)
    agent.try_fast_path = AsyncMock(return_value=None)
    agent._buscar_contexto_vetorial = AsyncMock(return_value=None)
    agent._converter_historico = lambda mensagem, historico, contexto: []
    agent._extrair_resposta_final = ConversationAgent._extrair_resposta_final.__get__(
        agent,
        ConversationAgent,
    )
    agent._normalizar_stream_evento = (
        ConversationAgent._normalizar_stream_evento.__get__(agent, ConversationAgent)
    )
    agent.ollama_agent = None

    async def fake_astream(*args, **kwargs):
        yield (
            (),
            "messages",
            (SimpleNamespace(content="Oi ", tool_call_chunks=None), {}),
        )
        yield (
            (),
            "messages",
            (SimpleNamespace(content="mundo", tool_call_chunks=None), {}),
        )
        yield ("values", {"messages": [AIMessage(content="Oi mundo")]})

    agent.graph = SimpleNamespace(astream=fake_astream)

    chunks = []
    async for chunk in ConversationAgent.processar_stream(
        agent,
        "teste",
        [],
        "sessao-teste",
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "Oi mundo"


@pytest.mark.asyncio
async def test_processar_stream_aceita_eventos_v2_com_dict():
    """Aceita eventos `version="v2"` no formato dict do LangGraph."""
    agent = object.__new__(ConversationAgent)
    agent._verificar_confirmacao = AsyncMock(return_value=None)
    agent.try_fast_path = AsyncMock(return_value=None)
    agent._buscar_contexto_vetorial = AsyncMock(return_value=None)
    agent._converter_historico = lambda mensagem, historico, contexto: []
    agent._extrair_resposta_final = ConversationAgent._extrair_resposta_final.__get__(
        agent,
        ConversationAgent,
    )
    agent._normalizar_stream_evento = (
        ConversationAgent._normalizar_stream_evento.__get__(agent, ConversationAgent)
    )
    agent.ollama_agent = None

    async def fake_astream(*args, **kwargs):
        yield {
            "type": "messages",
            "ns": (),
            "data": (SimpleNamespace(content="Oi ", tool_call_chunks=None), {}),
        }
        yield {
            "type": "messages",
            "ns": (),
            "data": (SimpleNamespace(content="mundo", tool_call_chunks=None), {}),
        }
        yield {
            "type": "values",
            "ns": (),
            "data": {"messages": [AIMessage(content="Oi mundo")]},
        }

    agent.graph = SimpleNamespace(astream=fake_astream)

    chunks = []
    async for chunk in ConversationAgent.processar_stream(
        agent,
        "teste",
        [],
        "sessao-teste",
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "Oi mundo"


@pytest.mark.asyncio
async def test_processar_mensagem_social_sem_tools_nao_chama_grafo():
    """Mensagens sociais simples devem usar o LLM direto, sem tools."""
    agent = object.__new__(ConversationAgent)
    agent.llm = SimpleNamespace()
    agent._verificar_confirmacao = AsyncMock(return_value=None)
    agent.try_fast_path = AsyncMock(return_value=None)
    agent._converter_historico = lambda mensagem, historico, contexto: []
    agent._responder_sem_tools = AsyncMock(return_value="Sou o Pulsar.")
    agent.graph = SimpleNamespace(
        ainvoke=AsyncMock(side_effect=AssertionError("graph não deveria ser chamado"))
    )

    result = await ConversationAgent.processar(
        agent,
        "Quem é você?",
        [],
        "sessao-teste",
    )

    assert result.resposta == "Sou o Pulsar."
    agent._responder_sem_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_processar_stream_faz_fallback_quando_groq_falha_tool_call():
    """Erros OpenAI/Groq no tool calling devem cair no fallback Ollama."""
    agent = object.__new__(ConversationAgent)
    agent._verificar_confirmacao = AsyncMock(return_value=None)
    agent.try_fast_path = AsyncMock(return_value=None)
    agent._buscar_contexto_vetorial = AsyncMock(return_value=None)
    agent._converter_historico = lambda mensagem, historico, contexto: []
    agent._normalizar_stream_evento = (
        ConversationAgent._normalizar_stream_evento.__get__(agent, ConversationAgent)
    )
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    provider_error = OpenAIAPIError(
        "Failed to call a function",
        request,
        body={"error": {"failed_generation": '{"tool_calls":[]}'}},
    )

    async def fake_astream(*args, **kwargs):
        raise provider_error
        yield  # pragma: no cover

    agent.graph = SimpleNamespace(astream=fake_astream)
    agent.ollama_agent = SimpleNamespace(
        check_ollama=AsyncMock(return_value=True),
        processar=AsyncMock(return_value="Resposta fallback do Ollama."),
    )

    chunks = []
    async for chunk in ConversationAgent.processar_stream(
        agent,
        "Quem é David Goggins?",
        [],
        "sessao-teste",
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "Resposta fallback do Ollama."
