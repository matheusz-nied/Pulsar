"""
agent.py — Agente de conversação com suporte a múltiplos LLM providers via LangGraph.

Responsável por:
- Gerenciar conversação com LangGraph + tools para todos os providers
- Suportar Claude, Gemini, OpenAI, DeepSeek, Groq e Ollama com tools completas
- Permitir fácil troca de provedores de IA via LLM_PROVIDER no .env
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from anthropic import (
    APIConnectionError as AnthropicAPIConnectionError,
)
from anthropic import (
    APIStatusError as AnthropicAPIStatusError,
)
from anthropic import (
    RateLimitError as AnthropicRateLimitError,
)
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from loguru import logger
from openai import APIError as OpenAIAPIError
from pydantic import SecretStr

from backend.core.http_client import get_shared_http_client
from backend.core.logging_config import add_request_metric

# ============================================================================
# RESPONSE TYPES
# ============================================================================


@dataclass
class AgentResponse:
    """Resposta do agente com metadados do modelo usado."""

    resposta: str
    modelo_usado: str


# ============================================================================
# PROTOCOLS
# ============================================================================


class LLMProvider(Protocol):
    """Protocol mantido para compatibilidade retroativa com código externo."""

    async def gerar_resposta(self, mensagem: str, historico: list[Any]) -> str:
        """Gera uma resposta usando o provedor de LLM."""
        ...

    def gerar_resposta_stream(
        self, mensagem: str, historico: list[Any]
    ) -> AsyncIterator[str]:
        """Gera uma resposta em streaming usando o provedor de LLM."""
        ...


# ============================================================================
# TOOLS PARA O LANGGRAPH
# ============================================================================

SYSTEM_PROMPT = (
    "Você é um assistente virtual local chamado Pulsar. "
    "Você é direto, eficiente e responde em português brasileiro. "
    "Por padrão, responda de forma curta e objetiva, em 1 a 3 frases ou uma lista curta quando fizer sentido. "
    "Só dê respostas longas se o usuário pedir detalhes, explicação completa, comparação ou passo a passo. "
    "Quando usar tools, sintetize a informação com suas palavras. "
    "Não despeje resultados crus, não repita blocos de busca, não leia títulos/URLs em sequência e não use markdown desnecessário. "
    "Quando não souber algo, diz claramente. "
    "Você tem acesso a tools para buscar na web, buscar notícias, "
    "abrir/fechar aplicativos, definir alarmes e controlar música. "
    "Use-as quando necessário. "
    "Ações críticas (como fechar aplicativos) requerem confirmação "
    "do usuário antes de serem executadas."
)

_OPERACIONAL_PATTERN = re.compile(
    r"^\s*(abra|abrir|abre|feche|fechar|fecha|toque|tocar|toca|pause|pausar|"
    r"pausa|continue|continuar|pare|parar|pule|pular|volume|aumente|diminu[ae]|"
    r"defina|definir|agende|agendar|lembre|lembrar|crie|criar|inicie|iniciar|"
    r"abra o|abre o|abre a|abrir o|abrir a)\b",
    re.IGNORECASE,
)
_QUESTION_HINTS = {
    "?",
    "quem",
    "qual",
    "quais",
    "quando",
    "onde",
    "como",
    "porque",
    "por que",
    "quanto",
    "quantos",
    "explique",
}
_MEMORY_HINTS = {
    "conversa",
    "conversamos",
    "falamos",
    "histórico",
    "historico",
    "antes",
    "anterior",
    "lembra",
}
_SIMPLE_CHAT_PATTERNS = (
    re.compile(r"^(oi|olá|ola|opa|ei|e ai|e aí|bom dia|boa tarde|boa noite)$"),
    re.compile(
        r"^(tudo bem|como vai|como (?:você|voce|cê|ce) (?:está|esta)|"
        r"(?:você|voce|cê|ce) (?:está|esta) bem)$"
    ),
    re.compile(
        r"^(quem (?:é|e) você|qual (?:é|e) o seu nome|qual seu nome|"
        r"o que você faz|o que voce faz|me fale sobre você|me fale sobre voce)$"
    ),
    re.compile(r"^(obrigad[oa]|valeu|até mais|ate mais|tchau)$"),
)
_MAX_VECTOR_CONTEXT_CHARS = 1600
_APP_ALIASES = {
    "visual studio code": "vscode",
    "vs code": "vscode",
    "vscode": "vscode",
    "code": "vscode",
    "google chrome": "chrome",
    "chrome": "chrome",
    "firefox": "firefox",
    "terminal": "terminal",
    "calculadora": "calculadora",
}
_APP_ALIAS_ITEMS = sorted(
    _APP_ALIASES.items(),
    key=lambda item: len(item[0]),
    reverse=True,
)


def _limpar_texto_comando(texto: str) -> str:
    """Normaliza espaços e remove pontuação terminal simples."""
    return re.sub(r"\s+", " ", texto.strip()).strip(" .!?")


def _deve_responder_sem_tools(texto: str) -> bool:
    """Detecta mensagens sociais simples que não precisam de tools."""
    candidato = _limpar_texto_comando(texto).lower()
    if not candidato or len(candidato.split()) > 8:
        return False
    return any(padrao.fullmatch(candidato) for padrao in _SIMPLE_CHAT_PATTERNS)


def _extrair_texto_conteudo(content: Any) -> str:
    """Extrai texto de payloads de conteúdo retornados por providers diferentes."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        partes: list[str] = []
        for item in content:
            if isinstance(item, dict):
                texto = item.get("text")
                if isinstance(texto, str):
                    partes.append(texto)
            else:
                texto = getattr(item, "text", None)
                if isinstance(texto, str):
                    partes.append(texto)
        return "".join(partes)

    return str(content) if content is not None else ""


def _log_provider_error_details(error: Exception) -> None:
    """Registra detalhes úteis do provider quando disponíveis."""
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return

    error_payload = body.get("error")
    if not isinstance(error_payload, dict):
        logger.debug("Provider error body: {}", body)
        return

    failed_generation = error_payload.get("failed_generation")
    if failed_generation:
        logger.warning("Provider failed_generation: {}", failed_generation)
        return

    logger.debug("Provider error body: {}", error_payload)


def _normalizar_nome_app(texto: str) -> str | None:
    """Converte aliases amigáveis de app para o nome canônico da tool."""
    candidato = _limpar_texto_comando(texto).lower()
    for alias, nome_canonico in _APP_ALIAS_ITEMS:
        if candidato == alias or candidato.startswith(f"{alias} "):
            return nome_canonico
    return None


def _extrair_app_para_abrir(texto: str) -> str | None:
    """Extrai um app suportado de um comando explícito de abertura."""
    match = re.match(
        r"^\s*(abra|abrir|abre)\s+(?:o|a|um|uma)?\s*(.+?)\s*$",
        texto,
        re.IGNORECASE,
    )
    if not match:
        return None
    return _normalizar_nome_app(match.group(2))


def _extrair_query_musica(texto: str) -> str | None:
    """Extrai a query de um comando explícito para tocar música."""
    match = re.match(r"(?is)^\s*(toque|toca|tocar)\s+(.+?)\s*$", texto)
    if not match:
        return None
    query = _limpar_texto_comando(match.group(2))
    if query.lower().startswith(("na ", "no ", "em ", "sobre ")):
        return None
    return query or None


def _eh_comando_pause(texto: str) -> bool:
    """Verifica se a mensagem pede pause/play de forma explícita."""
    return bool(
        re.fullmatch(
            r"\s*(pause|pausar|pausa|continue|continuar|retome|retomar)"
            r"(?:\s+(?:a\s+)?(?:musica|música))?\s*",
            texto,
            re.IGNORECASE,
        )
    )


def _eh_comando_proxima(texto: str) -> bool:
    """Verifica se a mensagem pede próxima faixa."""
    return bool(
        re.fullmatch(
            r"\s*(proxima|próxima|pule|pular|avance|avançe|avancar|avançar)"
            r"(?:\s+(?:faixa|musica|música))?\s*",
            texto,
            re.IGNORECASE,
        )
    )


def _extrair_nivel_volume(texto: str) -> int | None:
    """Extrai um nível de volume de comandos explícitos."""
    texto_normalizado = texto.lower()

    if re.search(r"\b(mudo|mute|silencie|silenciar)\b", texto_normalizado):
        return 0

    if "volume" in texto_normalizado and re.search(
        r"\b(maximo|máximo)\b", texto_normalizado
    ):
        return 100

    match = re.search(
        r"\b(?:volume|som)\b(?:\s+(?:para|em))?\s*(\d{1,3})\b",
        texto_normalizado,
    )
    if match:
        nivel = int(match.group(1))
        return nivel if 0 <= nivel <= 100 else None

    match = re.search(
        r"^\s*(?:aumente|aumentar|diminu[ae]|diminuir)\s+"
        r"(?:o\s+)?(?:volume|som)\s+(?:para\s+)?(\d{1,3})\b",
        texto_normalizado,
    )
    if match:
        nivel = int(match.group(1))
        return nivel if 0 <= nivel <= 100 else None

    return None


def _eh_listar_alarmes(texto: str) -> bool:
    """Identifica pedidos explícitos para listar alarmes."""
    return bool(
        re.search(
            r"\b(listar|liste|mostre|mostrar|quais)\b.*\balarmes?\b",
            texto,
            re.IGNORECASE,
        )
        or re.fullmatch(r"\s*alarmes?(?:\s+ativos?)?\s*", texto, re.IGNORECASE)
    )


def _extrair_job_id_cancelar_alarme(texto: str) -> str | None:
    """Extrai um ID de alarme de um comando explícito de cancelamento."""
    match = re.search(
        r"\b(?:cancel[ae]|remov[ae]|apagu[ae])\b.*\balarme\b.*\b([a-z0-9_-]{6,})\b",
        texto,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1)


def _montar_horario_alarme(hora: str, data: str | None) -> str:
    """Concatena hora e data no formato esperado pela tool de alarme."""
    return f"{hora} {data}" if data else hora


def _extrair_alarme(texto: str) -> dict[str, str] | None:
    """Extrai horário e mensagem de comandos explícitos de alarme/lembrete."""
    padroes = [
        re.compile(
            r"(?is)\b(?:me\s+)?lembre(?:te)?\s+(?:de|para|pra)\s+(.+?)\s+"
            r"(?:às|as)\s+(\d{1,2}:\d{2})(?:\s+(\d{2}/\d{2}/\d{4}))?\b"
        ),
        re.compile(
            r"(?is)\b(?:me\s+)?lembre(?:te)?\s+(?:às|as)\s+(\d{1,2}:\d{2})"
            r"(?:\s+(\d{2}/\d{2}/\d{4}))?(?:\s+(?:para|de|pra)\s+(.+))?$"
        ),
        re.compile(
            r"(?is)\b(?:defina|crie|agende)\s+(?:um\s+)?(?:alarme|lembrete)\s+"
            r"(?:para|às|as)\s+(\d{1,2}:\d{2})(?:\s+(\d{2}/\d{2}/\d{4}))?"
            r"(?:\s+(?:para|de|pra)\s+(.+))?$"
        ),
        re.compile(
            r"(?is)\balarme\s+(?:para\s+|às\s+|as\s+)?(\d{1,2}:\d{2})"
            r"(?:\s+(\d{2}/\d{2}/\d{4}))?(?:\s+(?:para|de)\s+(.+))?$"
        ),
    ]

    for idx, padrao in enumerate(padroes):
        match = padrao.search(texto)
        if not match:
            continue

        if idx == 0:
            mensagem = _limpar_texto_comando(match.group(1))
            horario = _montar_horario_alarme(match.group(2), match.group(3))
        else:
            horario = _montar_horario_alarme(match.group(1), match.group(2))
            mensagem = _limpar_texto_comando(match.group(3) or "Alarme do Pulsar")

        return {"horario": horario, "mensagem": mensagem or "Alarme do Pulsar"}

    return None


def _finalizar_fast_path(
    tool_name: str, resposta: str, started_at: float
) -> AgentResponse:
    """Registra métricas e empacota a resposta do fast-path."""
    add_request_metric("fast_path_hits", 1)
    add_request_metric("fast_path_ms", (time.perf_counter() - started_at) * 1000)
    logger.info("Fast-path executado: {} | resposta={}", tool_name, resposta[:160])
    return AgentResponse(
        resposta=resposta,
        modelo_usado=f"fast_path:{tool_name}",
    )


async def _processar_fast_path_message(mensagem: str) -> AgentResponse | None:
    """Executa tools diretamente para comandos operacionais bem explícitos."""
    texto = _limpar_texto_comando(mensagem)
    if not texto:
        return None

    started_at = time.perf_counter()

    nome_app = _extrair_app_para_abrir(texto)
    if nome_app is not None:
        from backend.tools.system import abrir_app

        resposta = await abrir_app(nome_app)
        return _finalizar_fast_path("abrir_app", resposta, started_at)

    if _eh_listar_alarmes(texto):
        from backend.tools.system import listar_alarmes

        resposta = await listar_alarmes()
        return _finalizar_fast_path("listar_alarmes", resposta, started_at)

    job_id = _extrair_job_id_cancelar_alarme(texto)
    if job_id is not None:
        from backend.tools.system import cancelar_alarme

        resposta = await cancelar_alarme(job_id)
        return _finalizar_fast_path("cancelar_alarme", resposta, started_at)

    alarme = _extrair_alarme(mensagem)
    if alarme is not None:
        from backend.tools.system import definir_alarme

        resposta = await definir_alarme(alarme["horario"], alarme["mensagem"])
        return _finalizar_fast_path("definir_alarme", resposta, started_at)

    nivel_volume = _extrair_nivel_volume(texto)
    if nivel_volume is not None:
        from backend.tools.system import ajustar_volume

        resposta = await ajustar_volume(nivel_volume)
        return _finalizar_fast_path("ajustar_volume", resposta, started_at)

    if _eh_comando_pause(texto):
        from backend.tools.music import controlar_musica

        resposta = await controlar_musica("pausar")
        return _finalizar_fast_path("controlar_musica", resposta, started_at)

    if _eh_comando_proxima(texto):
        from backend.tools.music import controlar_musica

        resposta = await controlar_musica("proximo")
        return _finalizar_fast_path("controlar_musica", resposta, started_at)

    query_musica = _extrair_query_musica(mensagem)
    if query_musica is not None:
        from backend.tools.music import controlar_musica

        resposta = await controlar_musica("tocar", query_musica)
        return _finalizar_fast_path("controlar_musica", resposta, started_at)

    return None


def _criar_tools() -> list[StructuredTool]:
    """
    Cria as tools formatadas para uso no LangGraph.

    Returns:
        Lista de StructuredTool prontas para binding com o LLM.
    """
    from backend.tools.music import controlar_musica
    from backend.tools.news import buscar_noticias
    from backend.tools.system import abrir_app, definir_alarme, fechar_app
    from backend.tools.web import buscar_web

    return [
        StructuredTool.from_function(
            coroutine=buscar_web,
            name="buscar_web",
            description=(
                "Busca informações na web. "
                "Use quando o usuário pedir para pesquisar algo."
            ),
        ),
        StructuredTool.from_function(
            coroutine=buscar_noticias,
            name="buscar_noticias",
            description=(
                "Busca notícias recentes por categoria "
                "(ia, tech, financas, economia, software, brasil). "
                "Use quando o usuário pedir notícias ou informações "
                "sobre mercado/economia."
            ),
        ),
        StructuredTool.from_function(
            coroutine=abrir_app,
            name="abrir_app",
            description=(
                "Abre um aplicativo no computador. "
                "Use quando o usuário pedir para abrir um programa."
            ),
        ),
        StructuredTool.from_function(
            coroutine=definir_alarme,
            name="definir_alarme",
            description=(
                "Define um alarme ou lembrete para um horário específico. "
                "Use quando o usuário pedir para ser lembrado de algo. "
                "Formatos aceitos: 'HH:MM' ou 'HH:MM DD/MM/YYYY'."
            ),
        ),
        StructuredTool.from_function(
            coroutine=controlar_musica,
            name="controlar_musica",
            description=(
                "Controla reprodução de música via YouTube Music. "
                "Use quando o usuário pedir para tocar, pausar, pular música ou ajustar volume. "
                "Parâmetro 'acao': tocar, pausar, proximo, volume. "
                "Parâmetro 'query': nome da música/artista (para tocar) ou nível 0-100 (para volume)."
            ),
        ),
        StructuredTool.from_function(
            coroutine=fechar_app,
            name="fechar_app",
            description=(
                "Fecha um aplicativo em execução. "
                "Use quando o usuário pedir para fechar um programa. "
                "Esta é uma ação crítica que requer confirmação do usuário."
            ),
        ),
    ]


def _construir_grafo(
    llm_with_tools: Any,
    tools: list[StructuredTool],
) -> Any:
    """
    Constrói o grafo do LangGraph com nós LLM e Tools.

    O nó "tools" inclui um security gate que intercepta ações críticas
    (definidas em ACOES_CRITICAS) e exige confirmação verbal do usuário
    antes de executá-las.

    Fluxo:
        START → llm → (tool_call?) → tools (security gate) → llm → ... → END

    Args:
        llm_with_tools: LLM com tools vinculadas.
        tools: Lista de tools para o ToolNode.

    Returns:
        Grafo compilado do LangGraph.
    """
    from backend.security.sandbox import security_manager

    original_tool_node = ToolNode(tools)

    async def llm_node(state: MessagesState) -> dict[str, list[Any]]:
        """Nó LLM: chama o LLM configurado com as tools disponíveis."""
        logger.info(
            f"Chamando LLM: {llm_with_tools.model} (provider: {type(llm_with_tools).__name__})"
        )
        started_at = time.perf_counter()
        response = await llm_with_tools.ainvoke(state["messages"])
        add_request_metric("llm_ms", (time.perf_counter() - started_at) * 1000)
        return {"messages": [response]}

    async def secured_tools_node(state: MessagesState) -> dict[str, list[Any]]:
        """Intercepta ações críticas e delega ações seguras ao ToolNode."""
        last_message = state["messages"][-1]

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            critical = [
                tc
                for tc in last_message.tool_calls
                if security_manager.is_critica(tc["name"])
            ]

            if critical:
                results: list[ToolMessage] = []
                for tc in last_message.tool_calls:
                    if security_manager.is_critica(tc["name"]):
                        msg = security_manager.requer_confirmacao(
                            tc["name"], tc["args"]
                        )
                    else:
                        msg = (
                            "Execução pausada: aguardando confirmação de ação crítica."
                        )
                    results.append(ToolMessage(content=msg, tool_call_id=tc["id"]))
                return {"messages": results}

        return await original_tool_node.ainvoke(state)

    graph = StateGraph(MessagesState)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", secured_tools_node)
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", tools_condition)
    graph.add_edge("tools", "llm")

    return graph.compile()


# ============================================================================
# AGENTE DE CONVERSAÇÃO COM LANGGRAPH
# ============================================================================


class ConversationAgent:
    """Agente de conversação principal com suporte a LangGraph e tools.

    Todos os providers (Claude, Gemini, OpenAI, DeepSeek, Ollama) usam
    LangGraph com tools completas. O fallback para Ollama local é ativado
    automaticamente em caso de falha do provider principal.
    """

    def __init__(
        self,
        llm: BaseChatModel | None = None,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5",
    ) -> None:
        """
        Inicializa o agente de conversação.

        Args:
            llm: Instância de BaseChatModel LangChain (ChatAnthropic, ChatOpenAI, etc).
                 Se fornecido, é usado diretamente como LLM principal.
            api_key: Chave de API da Anthropic. Usado apenas como fallback
                     retroativo quando `llm` não é fornecido.
            model: Modelo Claude a ser usado no fallback retroativo.
        """
        self.system_prompt = SYSTEM_PROMPT

        if llm is not None:
            self.llm = llm
        else:
            # Compatibilidade retroativa: cria ChatAnthropic se nenhum llm passado
            if api_key is None:
                api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY não encontrada nas variáveis de ambiente"
                )
            self.llm = ChatAnthropic(
                model_name=model,
                api_key=SecretStr(api_key),
                max_tokens_to_sample=1024,
                timeout=30.0,
                stop=None,
            )

        self.tools = _criar_tools()
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        self.graph = _construir_grafo(self.llm_with_tools, self.tools)
        self.ollama_agent: OllamaAgent | None = OllamaAgent()

        logger.info(
            f"ConversationAgent inicializado com LangGraph "
            f"(llm={self.llm.__class__.__name__}, tools={len(self.tools)}, fallback_ollama=True)"
        )

    def _converter_historico(
        self,
        mensagem: str,
        historico: list[dict[str, str]],
        contexto_vetorial: str | None = None,
    ) -> list[SystemMessage | HumanMessage | AIMessage]:
        """
        Converte o histórico e mensagem para formato LangChain.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores.
            contexto_vetorial: Contexto extra da memória vetorial para injetar no system prompt.

        Returns:
            Lista de mensagens LangChain.
        """
        system_content = self.system_prompt
        if contexto_vetorial:
            system_content += f"\n\n{contexto_vetorial}"

        messages: list[SystemMessage | HumanMessage | AIMessage] = [
            SystemMessage(content=system_content),
        ]

        for msg in historico:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=mensagem))
        return messages

    async def _verificar_confirmacao(
        self,
        mensagem: str,
        session_id: str = "default",
    ) -> str | None:
        """
        Verifica se a mensagem é uma confirmação ou cancelamento de ação crítica.

        Args:
            mensagem: Mensagem do usuário.
            session_id: ID da sessão para salvar na memória vetorial.

        Returns:
            Resposta se for confirmação/cancelamento, None se for mensagem normal.
        """
        from backend.security.sandbox import security_manager

        if not security_manager.tem_pendentes():
            return None

        texto = mensagem.strip()

        confirmar_match = re.search(r"(?i)\bconfirmar\s+([a-f0-9]{4})\b", texto)
        if confirmar_match:
            token_parcial = confirmar_match.group(1)
            sucesso, dados = security_manager.confirmar(token_parcial)
            if sucesso and dados:
                resposta = await self._executar_acao_confirmada(dados)
            else:
                resposta = (
                    "❌ Token de confirmação inválido ou expirado. "
                    "Tente novamente ou diga 'cancelar'."
                )
            return resposta

        if re.search(r"(?i)\bcancelar\b", texto):
            count = security_manager.cancelar_todas()
            resposta = f"✅ {count} ação(ões) pendente(s) cancelada(s)."
            return resposta

        return None

    async def _buscar_contexto_vetorial(self, mensagem: str) -> str | None:
        """
        Busca contexto relevante na memória vetorial para enriquecer o prompt.

        Args:
            mensagem: Mensagem do usuário usada como query de busca.

        Returns:
            String formatada com o contexto encontrado, ou None se vazio.
        """
        from backend.agent.memory import get_vector_memory_if_ready

        if not self._deve_buscar_contexto_vetorial(mensagem):
            logger.debug("Pulando memória vetorial para comando curto/operacional")
            return None

        vector_memory = get_vector_memory_if_ready()
        if vector_memory is None:
            return None

        started_at = time.perf_counter()
        (
            contexto_conversas,
            contexto_fatos,
        ) = await vector_memory.buscar_contextos_relevantes(
            mensagem,
            n_resultados_contexto=3,
            n_resultados_fatos=5,
        )
        add_request_metric("vector_ms", (time.perf_counter() - started_at) * 1000)

        partes: list[str] = []
        if contexto_conversas:
            partes.append(
                "Contexto de conversas anteriores:\n"
                + "\n---\n".join(contexto_conversas)
            )
        if contexto_fatos:
            partes.append(
                "Fatos conhecidos sobre o usuário:\n" + "\n".join(contexto_fatos)
            )

        if not partes:
            return None

        contexto = "\n\n".join(partes)
        if len(contexto) > _MAX_VECTOR_CONTEXT_CHARS:
            contexto = (
                contexto[:_MAX_VECTOR_CONTEXT_CHARS].rstrip()
                + "\n...[contexto vetorial truncado]"
            )
        return contexto

    def _deve_buscar_contexto_vetorial(self, mensagem: str) -> bool:
        """
        Decide se vale consultar memória vetorial nesta mensagem.

        Args:
            mensagem: Mensagem atual do usuário.

        Returns:
            True quando a consulta semântica tende a ajudar; False para
            comandos curtos e operacionais.
        """
        texto = " ".join(mensagem.strip().lower().split())
        if not texto:
            return False

        if _OPERACIONAL_PATTERN.match(texto):
            return False

        if any(hint in texto for hint in _MEMORY_HINTS):
            return True

        palavras = texto.split()
        if len(texto) <= 28 and not any(hint in texto for hint in _QUESTION_HINTS):
            return False

        if len(palavras) <= 4 and not any(hint in texto for hint in _QUESTION_HINTS):
            return False

        return True

    async def _executar_acao_confirmada(self, dados: dict[str, Any]) -> str:
        """
        Executa uma ação previamente aprovada pelo SecurityManager.

        Args:
            dados: Dicionário com "acao" (nome da tool) e "params" (argumentos).

        Returns:
            Resultado da execução da tool.
        """
        from backend.agent.tools import TOOL_REGISTRY

        acao = dados["acao"]
        params = dados["params"]

        if acao not in TOOL_REGISTRY:
            return f"Erro: Tool '{acao}' não encontrada."

        try:
            tool_func = TOOL_REGISTRY[acao]["function"]
            resultado = await tool_func(**params)
            logger.info(f"Ação confirmada executada: {acao} → {str(resultado)[:100]}")
            return f"✅ {resultado}"
        except Exception as e:
            logger.error(f"Erro ao executar ação confirmada '{acao}': {e}")
            return f"Erro ao executar ação: {str(e)}"

    async def try_fast_path(self, mensagem: str) -> AgentResponse | None:
        """
        Tenta processar comandos operacionais sem passar pelo LLM.

        Args:
            mensagem: Mensagem original do usuário.

        Returns:
            AgentResponse quando um fast-path foi executado; caso contrário, None.
        """
        from backend.security.sandbox import security_manager

        if security_manager.tem_pendentes():
            return None
        return await _processar_fast_path_message(mensagem)

    async def _responder_sem_tools(
        self,
        messages: list[SystemMessage | HumanMessage | AIMessage],
    ) -> str:
        """
        Gera resposta direta sem expor tools ao modelo.

        Args:
            messages: Histórico já convertido para o formato LangChain.

        Returns:
            Texto da resposta gerada pelo LLM.
        """
        started_at = time.perf_counter()
        response = await self.llm.ainvoke(messages)
        add_request_metric("llm_ms", (time.perf_counter() - started_at) * 1000)
        return _extrair_texto_conteudo(getattr(response, "content", ""))

    async def _responder_sem_tools_stream(
        self,
        messages: list[SystemMessage | HumanMessage | AIMessage],
    ) -> AsyncIterator[str]:
        """
        Faz streaming de resposta direta sem tool calling.

        Args:
            messages: Histórico já convertido para o formato LangChain.

        Yields:
            Chunks textuais do LLM.
        """
        started_at = time.perf_counter()
        try:
            async for chunk in self.llm.astream(messages):
                content = _extrair_texto_conteudo(getattr(chunk, "content", ""))
                if content:
                    yield content
        finally:
            add_request_metric("llm_ms", (time.perf_counter() - started_at) * 1000)

    async def processar(
        self,
        mensagem: str,
        historico: list[dict[str, str]],
        session_id: str = "default",
    ) -> AgentResponse:
        """
        Processa uma mensagem do usuário pelo grafo LangGraph.

        O LLM decide se precisa chamar uma tool ou responder diretamente.
        Se chamar uma tool, o resultado é passado de volta ao LLM.
        Busca contexto semântico antes de chamar o LLM e salva a conversa após.

        Antes do processamento normal, verifica se a mensagem é uma
        confirmação ou cancelamento de ação crítica pendente.

        Fallback: Se o provider principal falhar com erro de conexão/rate limit
        (Anthropic), tenta Ollama local. Se ambos falharem, retorna erro amigável.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores no formato
                      [{"role": "user"/"assistant", "content": str}].
            session_id: ID da sessão para persistência na memória vetorial.

        Returns:
            AgentResponse com resposta e modelo_usado.
        """
        logger.info(f"Processando mensagem: {mensagem[:50]}...")

        try:
            resposta_seguranca = await self._verificar_confirmacao(mensagem, session_id)
            if resposta_seguranca is not None:
                return AgentResponse(
                    resposta=resposta_seguranca,
                    modelo_usado=self.llm.__class__.__name__,
                )

            resposta_fast_path = await self.try_fast_path(mensagem)
            if resposta_fast_path is not None:
                return resposta_fast_path

            usar_sem_tools = _deve_responder_sem_tools(mensagem)
            if usar_sem_tools:
                add_request_metric("no_tools_hits", 1)
                messages = self._converter_historico(mensagem, historico, None)
            else:
                contexto_vetorial = await self._buscar_contexto_vetorial(mensagem)
                messages = self._converter_historico(
                    mensagem,
                    historico,
                    contexto_vetorial,
                )

            try:
                if usar_sem_tools:
                    logger.info("Mensagem conversacional simples; usando LLM sem tools")
                    resposta = await self._responder_sem_tools(messages)
                    return AgentResponse(
                        resposta=resposta,
                        modelo_usado=f"{self.llm.__class__.__name__}:no_tools",
                    )

                result = await self.graph.ainvoke({"messages": messages})

                for msg in reversed(result["messages"]):
                    if (
                        isinstance(msg, AIMessage)
                        and msg.content
                        and not msg.tool_calls
                    ):
                        resposta = (
                            msg.content
                            if isinstance(msg.content, str)
                            else str(msg.content)
                        )
                        logger.debug(
                            f"Resposta gerada ({self.llm.__class__.__name__}): {resposta[:50]}..."
                        )

                        return AgentResponse(
                            resposta=resposta,
                            modelo_usado=self.llm.__class__.__name__,
                        )

            except (
                AnthropicAPIConnectionError,
                AnthropicRateLimitError,
                AnthropicAPIStatusError,
                OpenAIAPIError,
            ) as e:
                _log_provider_error_details(e)
                logger.warning(
                    f"Provider indisponível ({type(e).__name__}), usando Ollama local"
                )

                if self.ollama_agent and await self.ollama_agent.check_ollama():
                    try:
                        resposta = await self.ollama_agent.processar(
                            mensagem, historico
                        )
                        logger.info(f"Resposta gerada via Ollama: {resposta[:50]}...")

                        return AgentResponse(resposta=resposta, modelo_usado="ollama")

                    except Exception as ollama_error:
                        logger.error(f"Ollama também falhou: {ollama_error}")
                        return AgentResponse(
                            resposta=(
                                "⚠️ Desculpe, estou com problemas de conexão. "
                                "Meu servidor local também não está disponível no momento. "
                                "Por favor, tente novamente em alguns instantes."
                            ),
                            modelo_usado="erro",
                        )
                else:
                    logger.warning("Ollama não disponível para fallback")
                    return AgentResponse(
                        resposta=(
                            "⚠️ Estou sem conexão com a internet e meu modo offline "
                            "não está disponível. Verifique se o Ollama está rodando localmente."
                        ),
                        modelo_usado="erro",
                    )

            return AgentResponse(
                resposta="Não foi possível gerar uma resposta.", modelo_usado="erro"
            )

        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

    async def processar_stream(
        self,
        mensagem: str,
        historico: list[dict[str, str]],
        session_id: str = "default",
    ) -> AsyncIterator[str]:
        """
        Processa uma mensagem em modo streaming pelo grafo LangGraph.

        Busca contexto semântico antes de iniciar o streaming.
        O salvamento na memória vetorial deve ser feito pelo chamador
        após coletar a resposta completa.

        Fallback: Se o provider falhar, tenta Ollama local (sem streaming).

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores.
            session_id: ID da sessão (usado para contexto vetorial).

        Yields:
            Chunks de texto da resposta conforme são gerados.

        Raises:
            RuntimeError: Se houver erro no processamento.
        """
        logger.info(f"Processando mensagem (stream): {mensagem[:50]}...")

        try:
            resposta_seguranca = await self._verificar_confirmacao(mensagem, session_id)
            if resposta_seguranca is not None:
                yield resposta_seguranca
                return

            resposta_fast_path = await self.try_fast_path(mensagem)
            if resposta_fast_path is not None:
                yield resposta_fast_path.resposta
                return

            usar_sem_tools = _deve_responder_sem_tools(mensagem)
            if usar_sem_tools:
                add_request_metric("no_tools_hits", 1)
                messages = self._converter_historico(mensagem, historico, None)
            else:
                contexto_vetorial = await self._buscar_contexto_vetorial(mensagem)
                messages = self._converter_historico(
                    mensagem,
                    historico,
                    contexto_vetorial,
                )

            resposta_final = ""
            resposta_stream = ""

            try:
                if usar_sem_tools:
                    logger.info(
                        "Mensagem conversacional simples; usando streaming sem tools"
                    )
                    async for chunk in self._responder_sem_tools_stream(messages):
                        resposta_stream += chunk
                        yield chunk
                    return

                async for event in self.graph.astream(
                    {"messages": messages},
                    stream_mode=["messages", "values"],
                    version="v2",
                ):
                    mode, data = self._normalizar_stream_evento(event)

                    if mode == "messages":
                        if not isinstance(data, tuple) or len(data) != 2:
                            continue

                        chunk, _metadata = data
                        if getattr(chunk, "tool_call_chunks", None):
                            continue

                        content = getattr(chunk, "content", "")
                        if isinstance(content, str) and content:
                            resposta_stream += content
                            yield content

                    elif mode == "values":
                        if not isinstance(data, dict):
                            continue

                        resposta_extraida = self._extrair_resposta_final(
                            data.get("messages", [])
                        )
                        if resposta_extraida:
                            resposta_final = resposta_extraida

                if resposta_final and resposta_final != resposta_stream:
                    if resposta_final.startswith(resposta_stream):
                        restante = resposta_final[len(resposta_stream) :]
                    else:
                        restante = resposta_final

                    if restante:
                        yield restante

            except (
                AnthropicAPIConnectionError,
                AnthropicRateLimitError,
                AnthropicAPIStatusError,
                OpenAIAPIError,
            ) as e:
                _log_provider_error_details(e)
                logger.warning(
                    f"Provider indisponível no streaming ({type(e).__name__}), usando Ollama"
                )

                if self.ollama_agent and await self.ollama_agent.check_ollama():
                    try:
                        resposta = await self.ollama_agent.processar(
                            mensagem, historico
                        )
                        logger.info(
                            f"Resposta via Ollama (fallback stream): {resposta[:50]}..."
                        )
                        yield resposta
                    except Exception as ollama_error:
                        logger.error(f"Ollama falhou no streaming: {ollama_error}")
                        yield (
                            "⚠️ Estou com problemas de conexão. "
                            "Por favor, tente novamente em alguns instantes."
                        )
                else:
                    yield (
                        "⚠️ Estou sem conexão e meu modo offline não está disponível. "
                        "Verifique se o Ollama está rodando."
                    )

        except Exception as e:
            logger.error(f"Erro ao processar mensagem (stream): {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

    def _normalizar_stream_evento(self, event: Any) -> tuple[str, Any]:
        """
        Normaliza eventos emitidos por `graph.astream`.

        O LangGraph pode emitir eventos em dois formatos quando há múltiplos
        `stream_mode`s:
        - `{"type": ..., "ns": ..., "data": ...}` no formato `version="v2"`
        - `(mode, data)`
        - `(namespace, mode, data)`

        Args:
            event: Evento bruto emitido pelo LangGraph.

        Returns:
            Tupla normalizada `(mode, data)`.

        Raises:
            ValueError: Se o formato do evento for desconhecido.
        """
        if isinstance(event, dict):
            mode = event.get("type")
            if not isinstance(mode, str) or "data" not in event:
                raise ValueError(
                    "Evento de stream inválido: dict sem chaves 'type'/'data'"
                )
            return mode, event["data"]

        if not isinstance(event, tuple):
            raise ValueError(
                f"Evento de stream inválido: esperado tuple, recebido {type(event).__name__}"
            )

        if len(event) == 2:
            mode, data = event
            return str(mode), data

        if len(event) == 3:
            _namespace, mode, data = event
            return str(mode), data

        raise ValueError(f"Evento de stream inválido: tamanho inesperado {len(event)}")

    def _extrair_resposta_final(self, mensagens: list[Any]) -> str:
        """
        Extrai a última resposta final do assistente do estado do grafo.

        Args:
            mensagens: Mensagens retornadas pelo estado atual do LangGraph.

        Returns:
            Texto da última resposta do assistente, ou string vazia.
        """
        for msg in reversed(mensagens):
            if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                return msg.content if isinstance(msg.content, str) else str(msg.content)
        return ""


# ============================================================================
# AGENTE OLLAMA (FALLBACK OFFLINE)
# ============================================================================


class OllamaAgent:
    """
    Agente Ollama para uso como fallback offline.

    Fornece interface simplificada para o ConversationAgent
    com verificação de conectividade.
    Reutiliza um cliente HTTP compartilhado para comunicar com o servidor local.
    """

    def __init__(self) -> None:
        """Inicializa o agente Ollama com configurações do .env."""
        self.model = os.getenv("OLLAMA_MODEL", "gemma3:4b-it-qat")
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._timeout = 30.0
        self._healthcheck_ttl = 5.0
        self._last_healthcheck_at = 0.0
        self._last_healthcheck_ok = False
        self._system_prompt = (
            "Você é um assistente virtual local chamado Pulsar. "
            "Você é direto, eficiente e responde em português brasileiro. "
            "Quando não souber algo, diz claramente."
        )

    async def check_ollama(self) -> bool:
        """
        Verifica conectividade com o servidor Ollama.

        Returns:
            True se o Ollama estiver online.
        """
        now = time.monotonic()
        if now - self._last_healthcheck_at < self._healthcheck_ttl:
            return self._last_healthcheck_ok

        try:
            client = await get_shared_http_client("ollama", timeout=self._timeout)
            response = await client.get(
                f"{self.base_url}/api/tags",
                timeout=5.0,
            )
            self._last_healthcheck_ok = response.status_code == 200
            self._last_healthcheck_at = now
            return self._last_healthcheck_ok
        except Exception as e:
            self._last_healthcheck_ok = False
            self._last_healthcheck_at = now
            logger.debug(f"Ollama não disponível: {e}")
            return False

    async def processar(self, mensagem: str, historico: list[dict[str, str]]) -> str:
        """
        Processa mensagem usando Ollama local.

        Args:
            mensagem: Mensagem do usuário.
            historico: Histórico de conversas.

        Returns:
            Resposta gerada pelo Ollama.
        """
        try:
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": self._system_prompt}
            ]
            messages.extend(
                [{"role": msg["role"], "content": msg["content"]} for msg in historico]
            )
            messages.append({"role": "user", "content": mensagem})

            started_at = time.perf_counter()
            client = await get_shared_http_client("ollama", timeout=self._timeout)
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=self._timeout,
            )
            response.raise_for_status()
            add_request_metric("llm_ms", (time.perf_counter() - started_at) * 1000)
            return response.json()["message"]["content"]

        except Exception as e:
            logger.error(f"Erro ao chamar Ollama: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e


# ============================================================================
# FACTORY
# ============================================================================


def create_agent_from_config(provider_name: str | None = None) -> ConversationAgent:
    """
    Cria um ConversationAgent com LangGraph + tools para o provider escolhido.

    Todos os providers usam LangGraph com tools completas. Não há mais modo legacy.

    Args:
        provider_name: Nome do provider ("claude", "gemini", "openai",
            "deepseek", "groq", "ollama"). Se None, usa a variável de
            ambiente LLM_PROVIDER (padrão: "claude").

    Returns:
        ConversationAgent configurado com o LLM escolhido.

    Raises:
        ValueError: Se o provider não for reconhecido ou a API key não estiver configurada.

    Exemplo:
        # Via variável de ambiente LLM_PROVIDER=gemini
        agent = create_agent_from_config()

        # Via parâmetro direto
        agent = create_agent_from_config("openai")
    """
    if provider_name is None:
        provider_name = os.getenv("LLM_PROVIDER", "claude").lower()

    provider_name = provider_name.lower()
    llm: BaseChatModel

    if provider_name == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY não configurada no .env")
        model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
        llm = ChatAnthropic(
            model_name=model,
            api_key=SecretStr(api_key),
            max_tokens_to_sample=1024,
            timeout=30.0,
            stop=None,
        )

    elif provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY não configurada no .env")
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
        llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=SecretStr(api_key),
            max_output_tokens=1024,
        )

    elif provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada no .env")
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        llm = ChatOpenAI(
            model=model,
            api_key=SecretStr(api_key),
            max_completion_tokens=1024,
        )

    elif provider_name == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY não configurada no .env")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        llm = ChatOpenAI(
            model=model,
            api_key=SecretStr(api_key),
            base_url="https://api.deepseek.com",
            max_completion_tokens=1024,
        )

    elif provider_name == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY não configurada no .env")
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        llm = ChatOpenAI(
            model=model,
            api_key=SecretStr(api_key),
            base_url="https://api.groq.com/openai/v1",
            max_completion_tokens=1024,
        )

    elif provider_name == "ollama":
        model = os.getenv("OLLAMA_MODEL", "gemma3:4b-it-qat")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        llm = ChatOllama(
            model=model,
            base_url=base_url,
            num_predict=1024,
        )

    else:
        raise ValueError(
            f"Provider '{provider_name}' não reconhecido. "
            f"Opções: claude, gemini, openai, deepseek, groq, ollama"
        )

    return ConversationAgent(llm=llm)


_agent_instance: ConversationAgent | None = None
_agent_lock = threading.Lock()


def get_agent() -> ConversationAgent:
    """
    Retorna a instância global do agente, inicializando sob demanda.

    Returns:
        Instância de ConversationAgent configurada pelo ambiente.
    """
    global _agent_instance

    if _agent_instance is not None:
        return _agent_instance

    with _agent_lock:
        if _agent_instance is None:
            _agent_instance = create_agent_from_config()
    return _agent_instance


def get_loaded_agent() -> ConversationAgent | None:
    """
    Retorna a instância global somente se já estiver carregada.

    Returns:
        Agente carregado ou None.
    """
    return _agent_instance


class LazyConversationAgent:
    """Proxy leve que inicializa o agente real apenas no primeiro uso."""

    async def try_fast_path(self, mensagem: str) -> AgentResponse | None:
        """
        Tenta executar fast-path sem forçar inicialização do LLM principal.

        Args:
            mensagem: Mensagem original do usuário.

        Returns:
            AgentResponse quando um comando operacional for atendido diretamente.
        """
        from backend.security.sandbox import security_manager

        if security_manager.tem_pendentes():
            return None
        return await _processar_fast_path_message(mensagem)

    async def processar(
        self,
        mensagem: str,
        historico: list[dict[str, str]],
        session_id: str = "default",
    ) -> AgentResponse:
        """Encaminha processamento para a instância real do agente."""
        resposta_fast_path = await self.try_fast_path(mensagem)
        if resposta_fast_path is not None:
            return resposta_fast_path
        return await get_agent().processar(
            mensagem,
            historico,
            session_id=session_id,
        )

    async def processar_stream(
        self,
        mensagem: str,
        historico: list[dict[str, str]],
        session_id: str = "default",
    ) -> AsyncIterator[str]:
        """Encaminha streaming para a instância real do agente."""
        resposta_fast_path = await self.try_fast_path(mensagem)
        if resposta_fast_path is not None:
            yield resposta_fast_path.resposta
            return
        async for chunk in get_agent().processar_stream(
            mensagem,
            historico,
            session_id=session_id,
        ):
            yield chunk

    @property
    def ollama_agent(self) -> OllamaAgent | None:
        """Retorna o agente Ollama somente se o agente real já estiver carregado."""
        loaded_agent = get_loaded_agent()
        return loaded_agent.ollama_agent if loaded_agent is not None else None


# Instância global lazy (usa LLM_PROVIDER do .env quando for realmente necessária)
agent = LazyConversationAgent()
