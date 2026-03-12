"""
memory.py — Gerenciamento de memória do agente.

Responsável por:
- Memória de sessão em memória (histórico por session_id)
- Persistência de histórico em JSON
- Limite de mensagens por sessão
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


class SessionMemory:
    """Gerencia histórico de conversas por sessão em memória."""

    MAX_HISTORY = 20

    def __init__(self) -> None:
        """Inicializa o gerenciador de memória de sessão."""
        self._sessions: dict[str, list[dict[str, str]]] = {}
        logger.info("SessionMemory inicializado")

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        """
        Retorna o histórico de uma sessão.

        Args:
            session_id: ID da sessão.

        Returns:
            Lista de mensagens da sessão no formato [{"role": str, "content": str}].
        """
        return self._sessions.get(session_id, []).copy()

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """
        Adiciona uma mensagem ao histórico da sessão.

        Args:
            session_id: ID da sessão.
            role: Papel do autor (user, assistant).
            content: Conteúdo da mensagem.
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        self._sessions[session_id].append({"role": role, "content": content})

        # Remove mensagens mais antigas se exceder o limite
        if len(self._sessions[session_id]) > self.MAX_HISTORY:
            removed = len(self._sessions[session_id]) - self.MAX_HISTORY
            self._sessions[session_id] = self._sessions[session_id][-self.MAX_HISTORY :]
            logger.debug(
                f"Sessão {session_id}: removidas {removed} mensagens antigas "
                f"(limite: {self.MAX_HISTORY})"
            )

        logger.debug(
            f"Mensagem adicionada à sessão {session_id}: role={role}, "
            f"total={len(self._sessions[session_id])}"
        )

    def clear_session(self, session_id: str) -> None:
        """
        Limpa o histórico de uma sessão.

        Args:
            session_id: ID da sessão a ser limpa.
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Sessão {session_id} limpa")
        else:
            logger.warning(f"Tentativa de limpar sessão inexistente: {session_id}")

    def list_sessions(self) -> list[str]:
        """
        Lista todas as sessões ativas.

        Returns:
            Lista de session_ids.
        """
        return list(self._sessions.keys())


class PersistentMemory:
    """Gerencia persistência de histórico em arquivo JSON."""

    def __init__(self, storage_path: str = "backend/memory/sessions.json") -> None:
        """
        Inicializa o gerenciador de memória persistente.

        Args:
            storage_path: Caminho para o arquivo JSON de armazenamento.
        """
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"PersistentMemory inicializado: {self.storage_path}")

    def save(self, session_id: str, history: list[dict[str, Any]]) -> None:
        """
        Salva o histórico de uma sessão em arquivo JSON.

        Args:
            session_id: ID da sessão.
            history: Lista de mensagens da sessão.
        """
        try:
            # Carrega dados existentes
            data: dict[str, list[dict[str, Any]]] = {}
            if self.storage_path.exists():
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            # Atualiza sessão
            data[session_id] = history

            # Salva de volta
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(
                f"Sessão {session_id} salva: {len(history)} mensagens em {self.storage_path}"
            )

        except Exception as e:
            logger.error(f"Erro ao salvar sessão {session_id}: {e}")
            raise

    def load(self, session_id: str) -> list[dict[str, Any]]:
        """
        Carrega o histórico de uma sessão do arquivo JSON.

        Args:
            session_id: ID da sessão.

        Returns:
            Lista de mensagens da sessão, ou lista vazia se não existir.
        """
        try:
            if not self.storage_path.exists():
                logger.debug(f"Arquivo {self.storage_path} não existe, retornando lista vazia")
                return []

            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            history = data.get(session_id, [])
            logger.info(
                f"Sessão {session_id} carregada: {len(history)} mensagens de {self.storage_path}"
            )
            return history

        except Exception as e:
            logger.error(f"Erro ao carregar sessão {session_id}: {e}")
            return []


# Instâncias globais
session_memory = SessionMemory()
persistent_memory = PersistentMemory()
