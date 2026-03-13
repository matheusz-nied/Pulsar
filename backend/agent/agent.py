"""
agent.py — Agente de conversação com integração Claude API.

Responsável por:
- Gerenciar conversação com Claude API
- Processar mensagens do usuário com histórico de contexto
- Permitir fácil troca de provedores de IA
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic, RateLimitError
from anthropic.types import MessageParam, TextBlock
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from loguru import logger
from pydantic import SecretStr


# ============================================================================
# RESPONSE TYPES
# ============================================================================


@dataclass
class AgentResponse:
    """Resposta do agente com metadados do modelo usado."""

    resposta: str
    modelo_usado: Literal["claude", "ollama", "erro"]


# ============================================================================
# PROTOCOLS
# ============================================================================


class LLMProvider(Protocol):
    """Protocol para permitir diferentes provedores de LLM."""

    async def gerar_resposta(
        self, mensagem: str, historico: list[MessageParam]
    ) -> str:
        """Gera uma resposta usando o provedor de LLM."""
        ...

    def gerar_resposta_stream(
        self, mensagem: str, historico: list[MessageParam]
    ) -> AsyncIterator[str]:
        """Gera uma resposta em streaming usando o provedor de LLM."""
        ...


class ClaudeProvider:
    """Provedor de LLM usando Claude API da Anthropic."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        """
        Inicializa o provedor Claude.

        Args:
            api_key: Chave de API da Anthropic.
            model: Modelo do Claude a ser usado.
        """
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.system_prompt = (
            "Você é um assistente virtual local chamado Pulsar. "
            "Você é direto, eficiente e responde em português brasileiro. "
            "Quando não souber algo, diz claramente."
        )

    async def gerar_resposta(
        self, mensagem: str, historico: list[MessageParam]
    ) -> str:
        """
        Gera uma resposta usando a API do Claude.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores no formato
                      [{"role": "user"/"assistant", "content": str}].

        Returns:
            Resposta gerada pelo Claude.

        Raises:
            RuntimeError: Se houver erro na chamada da API.
        """
        try:
            messages: list[MessageParam] = historico + [{"role": "user", "content": mensagem}]

            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self.system_prompt,
                messages=messages,
            )

            primeiro_bloco = response.content[0]
            if isinstance(primeiro_bloco, TextBlock):
                return primeiro_bloco.text
            return str(primeiro_bloco)

        except Exception as e:
            logger.error(f"Erro ao chamar Claude API: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

    async def gerar_resposta_stream(
        self, mensagem: str, historico: list[MessageParam]
    ) -> AsyncIterator[str]:
        """
        Gera resposta em streaming usando a API do Claude.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores.

        Yields:
            Chunks de texto da resposta conforme são gerados.

        Raises:
            RuntimeError: Se houver erro na chamada da API.
        """
        try:
            messages: list[MessageParam] = historico + [{"role": "user", "content": mensagem}]

            async with self.client.messages.stream(
                model=self.model,
                max_tokens=1024,
                system=self.system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text

        except Exception as e:
            logger.error(f"Erro no streaming Claude API: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

# ============================================================================
# TOOLS PARA O LANGGRAPH
# ============================================================================

SYSTEM_PROMPT = (
    "Você é um assistente virtual local chamado Pulsar. "
    "Você é direto, eficiente e responde em português brasileiro. "
    "Quando não souber algo, diz claramente. "
    "Você tem acesso a tools para buscar na web, buscar notícias, "
    "abrir/fechar aplicativos, definir alarmes e controlar música. "
    "Use-as quando necessário. "
    "Ações críticas (como fechar aplicativos) requerem confirmação "
    "do usuário antes de serem executadas."
)


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
        """Nó LLM: chama Claude com as tools disponíveis."""
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    async def secured_tools_node(state: MessagesState) -> dict[str, list[Any]]:
        """Intercepta ações críticas e delega ações seguras ao ToolNode."""
        last_message = state["messages"][-1]

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            critical = [
                tc for tc in last_message.tool_calls
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
                            "Execução pausada: aguardando "
                            "confirmação de ação crítica."
                        )
                    results.append(
                        ToolMessage(content=msg, tool_call_id=tc["id"])
                    )
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
    """Agente de conversação principal com suporte a LangGraph e tools."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        provider: LLMProvider | None = None,
    ) -> None:
        """
        Inicializa o agente de conversação.

        Modo LangGraph (padrão): Usa ChatAnthropic + tools via grafo LangGraph.
        Modo Legacy: Usa um provider direto sem suporte a tools.

        Args:
            api_key: Chave de API da Anthropic (modo LangGraph).
            model: Modelo do Claude a ser usado (modo LangGraph).
            provider: Provedor de LLM legado. Se fornecido, desativa LangGraph.
        """
        self.system_prompt = SYSTEM_PROMPT

        if provider is not None:
            # Modo legacy: provider direto, sem tools
            self._use_langgraph = False
            self.provider = provider
            self.ollama_agent: OllamaAgent | None = None
            logger.info(
                f"ConversationAgent inicializado (legacy, "
                f"provider={provider.__class__.__name__})"
            )
        else:
            # Modo LangGraph: ChatAnthropic + tools + fallback Ollama
            self._use_langgraph = True

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

            # Inicializa agente Ollama para fallback offline
            self.ollama_agent = OllamaAgent()

            logger.info(
                f"ConversationAgent inicializado com LangGraph "
                f"(model={model}, tools={len(self.tools)}, fallback_ollama=True)"
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
        from backend.agent.memory import vector_memory
        from backend.security.sandbox import security_manager

        if not security_manager.tem_pendentes():
            return None

        texto = mensagem.strip()

        confirmar_match = re.search(
            r"(?i)\bconfirmar\s+([a-f0-9]{4})\b", texto
        )
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
            if vector_memory is not None:
                await vector_memory.salvar_conversa(
                    session_id, mensagem, resposta
                )
            return resposta

        if re.search(r"(?i)\bcancelar\b", texto):
            count = security_manager.cancelar_todas()
            resposta = f"✅ {count} ação(ões) pendente(s) cancelada(s)."
            if vector_memory is not None:
                await vector_memory.salvar_conversa(
                    session_id, mensagem, resposta
                )
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
        from backend.agent.memory import vector_memory

        if vector_memory is None:
            return None

        contexto_conversas = await vector_memory.buscar_contexto(mensagem)
        contexto_fatos = await vector_memory.buscar_fatos(mensagem)

        partes: list[str] = []
        if contexto_conversas:
            partes.append(
                "Contexto de conversas anteriores:\n"
                + "\n---\n".join(contexto_conversas)
            )
        if contexto_fatos:
            partes.append(
                "Fatos conhecidos sobre o usuário:\n"
                + "\n".join(contexto_fatos)
            )

        return "\n\n".join(partes) if partes else None

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
            logger.info(
                f"Ação confirmada executada: {acao} → {str(resultado)[:100]}"
            )
            return f"✅ {resultado}"
        except Exception as e:
            logger.error(f"Erro ao executar ação confirmada '{acao}': {e}")
            return f"Erro ao executar ação: {str(e)}"

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

        Fallback: Se Claude indisponível (APIConnectionError/RateLimitError),
        tenta Ollama local. Se ambos falharem, retorna erro amigável.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores no formato
                      [{"role": "user"/"assistant", "content": str}].
            session_id: ID da sessão para persistência na memória vetorial.

        Returns:
            AgentResponse com resposta e modelo_usado ("claude" | "ollama" | "erro").
        """
        from backend.agent.memory import vector_memory

        logger.info(f"Processando mensagem: {mensagem[:50]}...")

        try:
            if self._use_langgraph:
                resposta_seguranca = await self._verificar_confirmacao(
                    mensagem, session_id
                )
                if resposta_seguranca is not None:
                    return AgentResponse(resposta=resposta_seguranca, modelo_usado="claude")

            contexto_vetorial = await self._buscar_contexto_vetorial(mensagem)
            mensagem_com_contexto = (
                f"{contexto_vetorial}\n\nPergunta atual do usuário: {mensagem}"
                if contexto_vetorial
                else mensagem
            )

            if not self._use_langgraph:
                resposta = await self.provider.gerar_resposta(  # type: ignore[arg-type]
                    mensagem_com_contexto,
                    historico,
                )
                logger.debug(f"Resposta gerada (legacy): {resposta[:50]}...")
                if vector_memory is not None:
                    await vector_memory.salvar_conversa(session_id, mensagem, resposta)
                return AgentResponse(resposta=resposta, modelo_usado="claude")

            # Modo LangGraph: tenta Claude, fallback para Ollama
            messages = self._converter_historico(mensagem, historico, contexto_vetorial)

            try:
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
                        logger.debug(f"Resposta gerada (Claude): {resposta[:50]}...")

                        if vector_memory is not None:
                            await vector_memory.salvar_conversa(
                                session_id, mensagem, resposta
                            )

                        return AgentResponse(resposta=resposta, modelo_usado="claude")

            except (APIConnectionError, RateLimitError, APIStatusError) as e:
                # Claude indisponível - tenta fallback Ollama
                logger.warning(f"Claude indisponível ({type(e).__name__}), usando Ollama local")

                if self.ollama_agent and await self.ollama_agent.check_ollama():
                    try:
                        resposta = await self.ollama_agent.processar(mensagem, historico)
                        logger.info(f"Resposta gerada via Ollama: {resposta[:50]}...")

                        if vector_memory is not None:
                            await vector_memory.salvar_conversa(
                                session_id, mensagem, resposta
                            )

                        return AgentResponse(resposta=resposta, modelo_usado="ollama")

                    except Exception as ollama_error:
                        logger.error(f"Ollama também falhou: {ollama_error}")
                        return AgentResponse(
                            resposta=(
                                "⚠️ Desculpe, estou com problemas de conexão. "
                                "Meu servidor local também não está disponível no momento. "
                                "Por favor, tente novamente em alguns instantes."
                            ),
                            modelo_usado="erro"
                        )
                else:
                    logger.warning("Ollama não disponível para fallback")
                    return AgentResponse(
                        resposta=(
                            "⚠️ Estou sem conexão com a internet e meu modo offline "
                            "não está disponível. Verifique se o Ollama está rodando localmente."
                        ),
                        modelo_usado="erro"
                    )

            return AgentResponse(
                resposta="Não foi possível gerar uma resposta.",
                modelo_usado="erro"
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

        Fallback: Se Claude indisponível, tenta Ollama local (sem streaming).

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
            if self._use_langgraph:
                resposta_seguranca = await self._verificar_confirmacao(
                    mensagem, session_id
                )
                if resposta_seguranca is not None:
                    yield resposta_seguranca
                    return

            contexto_vetorial = await self._buscar_contexto_vetorial(mensagem)
            mensagem_com_contexto = (
                f"{contexto_vetorial}\n\nPergunta atual do usuário: {mensagem}"
                if contexto_vetorial
                else mensagem
            )

            if not self._use_langgraph:
                async for chunk in self.provider.gerar_resposta_stream(  # type: ignore[arg-type]
                    mensagem_com_contexto,
                    historico,
                ):
                    yield chunk
                return

            messages = self._converter_historico(mensagem, historico, contexto_vetorial)

            # Tenta streaming com Claude, fallback para Ollama se falhar
            try:
                async for event in self.graph.astream_events(
                    {"messages": messages}, version="v2"
                ):
                    if event["event"] == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        if (
                            isinstance(chunk.content, str)
                            and chunk.content
                            and not getattr(chunk, "tool_call_chunks", None)
                        ):
                            yield chunk.content

            except (APIConnectionError, RateLimitError, APIStatusError) as e:
                # Claude indisponível no meio do streaming - fallback Ollama
                logger.warning(f"Claude indisponível no streaming ({type(e).__name__}), usando Ollama")

                if self.ollama_agent and await self.ollama_agent.check_ollama():
                    try:
                        resposta = await self.ollama_agent.processar(mensagem, historico)
                        logger.info(f"Resposta via Ollama (fallback stream): {resposta[:50]}...")
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


class GeminiProvider:
    """Provedor de LLM usando Google Gemini API."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-exp") -> None:
        """
        Inicializa o provedor Gemini.

        Args:
            api_key: Chave de API do Google AI Studio.
            model: Modelo do Gemini a ser usado.
        """
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=api_key)  # type: ignore
        self.model = genai.GenerativeModel(  # type: ignore
            model_name=model,
            system_instruction=(
                "Você é um assistente virtual local chamado Pulsar. "
                "Você é direto, eficiente e responde em português brasileiro. "
                "Quando não souber algo, diz claramente."
            ),
        )

    async def gerar_resposta(
        self, mensagem: str, historico: list[MessageParam]
    ) -> str:
        """Gera resposta usando Gemini API."""
        try:
            history = []
            for msg in historico:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [msg["content"]]})

            chat = self.model.start_chat(history=history)
            response = await chat.send_message_async(mensagem)
            return response.text

        except Exception as e:
            logger.error(f"Erro ao chamar Gemini API: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

    async def gerar_resposta_stream(
        self, mensagem: str, historico: list[MessageParam]
    ) -> AsyncIterator[str]:
        """Fallback: gera resposta completa e yield como chunk único."""
        resposta = await self.gerar_resposta(mensagem, historico)
        yield resposta


class OpenAIProvider:
    """Provedor de LLM usando OpenAI API."""

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        """
        Inicializa o provedor OpenAI.

        Args:
            api_key: Chave de API da OpenAI.
            model: Modelo a ser usado (gpt-4o, gpt-4-turbo, etc).
        """
        from openai import AsyncOpenAI
        from openai.types.chat import ChatCompletionMessageParam  # noqa: F401

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = (
            "Você é um assistente virtual local chamado Pulsar. "
            "Você é direto, eficiente e responde em português brasileiro. "
            "Quando não souber algo, diz claramente."
        )

    async def gerar_resposta(
        self, mensagem: str, historico: list[MessageParam]
    ) -> str:
        """Gera resposta usando OpenAI API."""
        try:
            from openai.types.chat import ChatCompletionMessageParam

            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": self.system_prompt},  # type: ignore
                *[{"role": msg["role"], "content": msg["content"]} for msg in historico],  # type: ignore
                {"role": "user", "content": mensagem},  # type: ignore
            ]

            response = await self.client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=1024
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"Erro ao chamar OpenAI API: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

    async def gerar_resposta_stream(
        self, mensagem: str, historico: list[MessageParam]
    ) -> AsyncIterator[str]:
        """Fallback: gera resposta completa e yield como chunk único."""
        resposta = await self.gerar_resposta(mensagem, historico)
        yield resposta


class DeepSeekProvider:
    """Provedor de LLM usando DeepSeek API (compatível com OpenAI)."""

    def __init__(self, api_key: str, model: str = "deepseek-chat") -> None:
        """
        Inicializa o provedor DeepSeek.

        Args:
            api_key: Chave de API da DeepSeek.
            model: Modelo a ser usado.
        """
        from openai import AsyncOpenAI
        from openai.types.chat import ChatCompletionMessageParam  # noqa: F401

        self.client = AsyncOpenAI(
            api_key=api_key, base_url="https://api.deepseek.com"
        )
        self.model = model
        self.system_prompt = (
            "Você é um assistente virtual local chamado Pulsar. "
            "Você é direto, eficiente e responde em português brasileiro. "
            "Quando não souber algo, diz claramente."
        )

    async def gerar_resposta(
        self, mensagem: str, historico: list[MessageParam]
    ) -> str:
        """Gera resposta usando DeepSeek API."""
        try:
            from openai.types.chat import ChatCompletionMessageParam

            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": self.system_prompt},  # type: ignore
                *[{"role": msg["role"], "content": msg["content"]} for msg in historico],  # type: ignore
                {"role": "user", "content": mensagem},  # type: ignore
            ]

            response = await self.client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=1024
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"Erro ao chamar DeepSeek API: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

    async def gerar_resposta_stream(
        self, mensagem: str, historico: list[MessageParam]
    ) -> AsyncIterator[str]:
        """Fallback: gera resposta completa e yield como chunk único."""
        resposta = await self.gerar_resposta(mensagem, historico)
        yield resposta


class OllamaProvider:
    """Provedor de LLM local usando Ollama."""

    def __init__(
        self, model: str = "gemma3:4b-it-qat", base_url: str = "http://localhost:11434"
    ) -> None:
        """
        Inicializa o provedor Ollama.

        Args:
            model: Modelo local instalado no Ollama (llama3.2, mistral, etc).
            base_url: URL do servidor Ollama.
        """
        self.model = model
        self.base_url = base_url
        self.timeout = 30.0
        self.system_prompt = (
            "Você é um assistente virtual local chamado Pulsar. "
            "Você é direto, eficiente e responde em português brasileiro. "
            "Quando não souber algo, diz claramente."
        )

    async def check_ollama(self) -> bool:
        """
        Verifica se o servidor Ollama está acessível.

        Returns:
            True se o Ollama estiver online, False caso contrário.
        """
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/tags",
                    timeout=5.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.debug(f"Ollama não disponível: {e}")
            return False

    async def gerar_resposta(
        self, mensagem: str, historico: list[MessageParam]
    ) -> str:
        """Gera resposta usando Ollama local."""
        try:
            import httpx

            messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
            messages.extend([dict(msg) for msg in historico])
            messages.append({"role": "user", "content": mensagem})

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={"model": self.model, "messages": messages, "stream": False},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()["message"]["content"]

        except Exception as e:
            logger.error(f"Erro ao chamar Ollama: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

    async def gerar_resposta_stream(
        self, mensagem: str, historico: list[MessageParam]
    ) -> AsyncIterator[str]:
        """Fallback: gera resposta completa e yield como chunk único."""
        resposta = await self.gerar_resposta(mensagem, historico)
        yield resposta


class OllamaAgent:
    """
    Wrapper do OllamaProvider para uso como fallback offline.

    Fornece interface simplificada para o ConversationAgent
    com verificação de conectividade.
    """

    def __init__(self) -> None:
        """Inicializa o agente Ollama com configurações do .env."""
        self.model = os.getenv("OLLAMA_MODEL", "gemma3:4b-it-qat")
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.provider = OllamaProvider(model=self.model, base_url=self.base_url)

    async def check_ollama(self) -> bool:
        """
        Verifica conectividade com o servidor Ollama.

        Returns:
            True se o Ollama estiver online.
        """
        return await self.provider.check_ollama()

    async def processar(
        self, mensagem: str, historico: list[dict[str, str]]
    ) -> str:
        """
        Processa mensagem usando Ollama local.

        Args:
            mensagem: Mensagem do usuário.
            historico: Histórico de conversas.

        Returns:
            Resposta gerada pelo Ollama.
        """
        # Converte histórico para formato MessageParam
        historico_param: list[MessageParam] = [
            {"role": msg["role"], "content": msg["content"]} for msg in historico
        ]
        return await self.provider.gerar_resposta(mensagem, historico_param)


def create_agent_from_config(provider_name: str | None = None) -> ConversationAgent:
    """
    Cria um agente baseado no nome do provider.

    Para "claude": usa LangGraph com ChatAnthropic + tools (recomendado).
    Para outros providers: usa modo legacy sem suporte a tools.

    Args:
        provider_name: Nome do provider ("claude", "gemini", "openai", "deepseek", "ollama").
                      Se None, usa a variável de ambiente LLM_PROVIDER (padrão: "claude").

    Returns:
        ConversationAgent configurado com o provider escolhido.

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

    if provider_name == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY não configurada no .env")
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        return ConversationAgent(api_key=api_key, model=model)

    elif provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY não configurada no .env")
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
        logger.warning("Gemini: modo legacy sem suporte a tools do LangGraph")
        return ConversationAgent(provider=GeminiProvider(api_key=api_key, model=model))

    elif provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada no .env")
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        logger.warning("OpenAI: modo legacy sem suporte a tools do LangGraph")
        return ConversationAgent(provider=OpenAIProvider(api_key=api_key, model=model))

    elif provider_name == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY não configurada no .env")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        logger.warning("DeepSeek: modo legacy sem suporte a tools do LangGraph")
        return ConversationAgent(provider=DeepSeekProvider(api_key=api_key, model=model))

    elif provider_name == "ollama":
        model = os.getenv("OLLAMA_MODEL", "gemma3:4b-it-qat")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        logger.warning("Ollama: modo legacy sem suporte a tools do LangGraph")
        return ConversationAgent(provider=OllamaProvider(model=model, base_url=base_url))

    else:
        raise ValueError(
            f"Provider '{provider_name}' não reconhecido. "
            f"Opções: claude, gemini, openai, deepseek, ollama"
        )


# Instância global padrão (usa LLM_PROVIDER do .env ou Claude como fallback)
agent = create_agent_from_config()
