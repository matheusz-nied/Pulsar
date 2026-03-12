"""
agent.py — Agente de conversação com integração Claude API.

Responsável por:
- Gerenciar conversação com Claude API
- Processar mensagens do usuário com histórico de contexto
- Permitir fácil troca de provedores de IA
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any, Protocol

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlock
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from loguru import logger
from pydantic import SecretStr


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
    "abrir aplicativos e definir alarmes. Use-as quando necessário."
)


def _criar_tools() -> list[StructuredTool]:
    """
    Cria as tools formatadas para uso no LangGraph.

    Returns:
        Lista de StructuredTool prontas para binding com o LLM.
    """
    from backend.tools.news import buscar_noticias
    from backend.tools.system import abrir_app, definir_alarme
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
    ]


def _construir_grafo(
    llm_with_tools: Any,
    tools: list[StructuredTool],
) -> Any:
    """
    Constrói o grafo do LangGraph com nós LLM e Tools.

    Fluxo:
        START → llm → (tool_call?) → tools → llm → ... → END

    Args:
        llm_with_tools: LLM com tools vinculadas.
        tools: Lista de tools para o ToolNode.

    Returns:
        Grafo compilado do LangGraph.
    """
    async def llm_node(state: MessagesState) -> dict[str, list[Any]]:
        """Nó LLM: chama Claude com as tools disponíveis."""
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", ToolNode(tools))
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
            logger.info(
                f"ConversationAgent inicializado (legacy, "
                f"provider={provider.__class__.__name__})"
            )
        else:
            # Modo LangGraph: ChatAnthropic + tools
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

            logger.info(
                f"ConversationAgent inicializado com LangGraph "
                f"(model={model}, tools={len(self.tools)})"
            )

    def _converter_historico(
        self,
        mensagem: str,
        historico: list[dict[str, str]],
    ) -> list[SystemMessage | HumanMessage | AIMessage]:
        """
        Converte o histórico e mensagem para formato LangChain.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores.

        Returns:
            Lista de mensagens LangChain.
        """
        messages: list[SystemMessage | HumanMessage | AIMessage] = [
            SystemMessage(content=self.system_prompt),
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

    async def processar(
        self, mensagem: str, historico: list[dict[str, str]]
    ) -> str:
        """
        Processa uma mensagem do usuário pelo grafo LangGraph.

        O LLM decide se precisa chamar uma tool ou responder diretamente.
        Se chamar uma tool, o resultado é passado de volta ao LLM.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores no formato
                      [{"role": "user"/"assistant", "content": str}].

        Returns:
            Resposta gerada pelo agente.

        Raises:
            RuntimeError: Se houver erro no processamento.
        """
        logger.info(f"Processando mensagem: {mensagem[:50]}...")

        try:
            if not self._use_langgraph:
                resposta = await self.provider.gerar_resposta(mensagem, historico)  # type: ignore[arg-type]
                logger.debug(f"Resposta gerada (legacy): {resposta[:50]}...")
                return resposta

            messages = self._converter_historico(mensagem, historico)
            result = await self.graph.ainvoke({"messages": messages})

            # Extrair a última mensagem do AI (sem tool_calls)
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
                    logger.debug(f"Resposta gerada: {resposta[:50]}...")
                    return resposta

            return "Não foi possível gerar uma resposta."

        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {e}")
            raise RuntimeError(
                f"Não foi possível processar sua mensagem. Erro: {str(e)}"
            ) from e

    async def processar_stream(
        self, mensagem: str, historico: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        """
        Processa uma mensagem em modo streaming pelo grafo LangGraph.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Lista de mensagens anteriores.

        Yields:
            Chunks de texto da resposta conforme são gerados.

        Raises:
            RuntimeError: Se houver erro no processamento.
        """
        logger.info(f"Processando mensagem (stream): {mensagem[:50]}...")

        try:
            if not self._use_langgraph:
                async for chunk in self.provider.gerar_resposta_stream(mensagem, historico):  # type: ignore[arg-type]
                    yield chunk
                return

            messages = self._converter_historico(mensagem, historico)

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
        self.system_prompt = (
            "Você é um assistente virtual local chamado Pulsar. "
            "Você é direto, eficiente e responde em português brasileiro. "
            "Quando não souber algo, diz claramente."
        )

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
                    timeout=60.0,
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
