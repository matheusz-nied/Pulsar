"""
memory.py — Gerenciamento de memória do agente.

Responsável por:
- Memória de curto prazo (contexto da conversa atual)
- Memória de longo prazo (ChromaDB para busca semântica)
- Persistência de histórico em SQLite
"""

from __future__ import annotations

from typing import Any

from loguru import logger


class MemoryManager:
    """Gerencia memória de curto e longo prazo do agente."""

    def __init__(self) -> None:
        """Inicializa o gerenciador de memória."""
        self._short_term: list[dict[str, Any]] = []
        logger.info("MemoryManager inicializado.")

    async def add_message(self, role: str, content: str) -> None:
        """
        Adiciona uma mensagem à memória de curto prazo.

        Args:
            role: Papel do autor (user, assistant, system).
            content: Conteúdo da mensagem.
        """
        self._short_term.append({"role": role, "content": content})
        logger.debug(f"Mensagem adicionada à memória: role={role}")

    async def get_context(self) -> list[dict[str, Any]]:
        """
        Retorna o contexto atual da conversa.

        Returns:
            Lista de mensagens na memória de curto prazo.
        """
        return self._short_term.copy()

    async def clear_short_term(self) -> None:
        """Limpa a memória de curto prazo."""
        self._short_term.clear()
        logger.info("Memória de curto prazo limpa.")
