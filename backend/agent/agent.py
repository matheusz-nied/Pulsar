"""
agent.py — Agente de conversação com integração Claude API.

Responsável por:
- Gerenciar conversação com Claude API
- Processar mensagens do usuário com histórico de contexto
- Permitir fácil troca de provedores de IA
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlock
from loguru import logger


class LLMProvider(Protocol):
    """Protocol para permitir diferentes provedores de LLM."""

    async def gerar_resposta(
        self, mensagem: str, historico: list[MessageParam]
    ) -> str:
        """Gera uma resposta usando o provedor de LLM."""
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


class ConversationAgent:
    """Agente de conversação principal."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        """
        Inicializa o agente de conversação.

        Args:
            provider: Provedor de LLM a ser usado. Se None, usa ClaudeProvider.
        """
        if provider is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY não encontrada nas variáveis de ambiente"
                )
            provider = ClaudeProvider(api_key=api_key)

        self.provider = provider
        logger.info("ConversationAgent inicializado")

    async def processar(self, mensagem: str, historico: list[MessageParam]) -> str:
        """
        Processa uma mensagem do usuário e retorna a resposta do agente.

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
            resposta = await self.provider.gerar_resposta(mensagem, historico)
            logger.debug(f"Resposta gerada: {resposta[:50]}...")
            return resposta

        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {e}")
            raise


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


def create_agent_from_config(provider_name: str | None = None) -> ConversationAgent:
    """
    Cria um agente baseado no nome do provider.

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
        return ConversationAgent(provider=ClaudeProvider(api_key=api_key))

    elif provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY não configurada no .env")
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
        return ConversationAgent(provider=GeminiProvider(api_key=api_key, model=model))

    elif provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada no .env")
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        return ConversationAgent(provider=OpenAIProvider(api_key=api_key, model=model))

    elif provider_name == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY não configurada no .env")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        return ConversationAgent(provider=DeepSeekProvider(api_key=api_key, model=model))

    elif provider_name == "ollama":
        model = os.getenv("OLLAMA_MODEL", "gemma3:4b-it-qat")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return ConversationAgent(provider=OllamaProvider(model=model, base_url=base_url))

    else:
        raise ValueError(
            f"Provider '{provider_name}' não reconhecido. "
            f"Opções: claude, gemini, openai, deepseek, ollama"
        )


# Instância global padrão (usa LLM_PROVIDER do .env ou Claude como fallback)
agent = create_agent_from_config()
