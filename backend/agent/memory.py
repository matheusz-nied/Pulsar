"""
memory.py — Gerenciamento de memória do agente.

Responsável por:
- Memória de sessão em memória (histórico por session_id)
- Persistência de histórico em JSON
- Persistência assíncrona em background para não bloquear respostas
- Memória vetorial com ChromaDB para busca semântica
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from backend.core.logging_config import add_request_metric


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
        return [message.copy() for message in self._sessions.get(session_id, [])]

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
        self._write_lock = threading.Lock()
        logger.info(f"PersistentMemory inicializado: {self.storage_path}")

    def save(self, session_id: str, history: list[dict[str, Any]]) -> None:
        """
        Salva o histórico de uma sessão em arquivo JSON.

        Args:
            session_id: ID da sessão.
            history: Lista de mensagens da sessão.
        """
        try:
            with self._write_lock:
                data: dict[str, list[dict[str, Any]]] = {}
                if self.storage_path.exists():
                    with open(self.storage_path, "r", encoding="utf-8") as file_obj:
                        data = json.load(file_obj)

                data[session_id] = history

                with open(self.storage_path, "w", encoding="utf-8") as file_obj:
                    json.dump(data, file_obj, ensure_ascii=False)

            logger.info(
                f"Sessão {session_id} salva: {len(history)} mensagens em {self.storage_path}"
            )

        except Exception as exc:
            logger.error(f"Erro ao salvar sessão {session_id}: {exc}")
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
                logger.debug(
                    f"Arquivo {self.storage_path} não existe, retornando lista vazia"
                )
                return []

            with open(self.storage_path, "r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)

            history = data.get(session_id, [])
            logger.info(
                f"Sessão {session_id} carregada: {len(history)} mensagens de {self.storage_path}"
            )
            return history

        except Exception as exc:
            logger.error(f"Erro ao carregar sessão {session_id}: {exc}")
            return []


class VectorMemory:
    """Memória vetorial usando ChromaDB para busca semântica de conversas e fatos."""

    PERSIST_DIR = "backend/memory/chroma"
    COLLECTION_NAME = "conversas"
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"

    def __init__(self) -> None:
        """Inicializa ChromaDB persistente e modelo de embeddings sentence-transformers."""
        import chromadb
        from sentence_transformers import SentenceTransformer

        self._client = chromadb.PersistentClient(path=self.PERSIST_DIR)
        self._conversas = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._fatos = self._client.get_or_create_collection(
            name="fatos",
            metadata={"hnsw:space": "cosine"},
        )

        allow_download = os.getenv("VECTOR_MEMORY_ALLOW_DOWNLOAD", "1") == "1"
        self._model = SentenceTransformer(
            self.EMBEDDING_MODEL,
            device="cpu",
            local_files_only=not allow_download,
        )
        logger.info(
            f"VectorMemory inicializado "
            f"(model={self.EMBEDDING_MODEL}, persist={self.PERSIST_DIR})"
        )

    def _embed(self, text: str) -> list[float]:
        """Gera embedding para um texto usando sentence-transformers."""
        return self._model.encode(text).tolist()

    async def _buscar_documentos_por_embedding(
        self,
        collection: Any,
        embedding: list[float],
        n_resultados: int,
    ) -> list[str]:
        """
        Busca documentos em uma collection usando embedding já calculado.

        Args:
            collection: Collection do ChromaDB.
            embedding: Embedding previamente calculado.
            n_resultados: Número máximo de resultados.

        Returns:
            Lista de documentos relevantes.
        """
        total = await asyncio.to_thread(collection.count)
        if total == 0:
            return []

        resultados = await asyncio.to_thread(
            collection.query,
            query_embeddings=[embedding],
            n_results=min(n_resultados, total),
        )
        documentos = resultados.get("documents", [[]])
        return documentos[0] if documentos else []

    async def salvar_conversa(
        self, session_id: str, user_msg: str, assistant_msg: str
    ) -> None:
        """
        Salva um par de conversa (usuário + assistente) no ChromaDB.

        Args:
            session_id: ID da sessão.
            user_msg: Mensagem do usuário.
            assistant_msg: Resposta do assistente.
        """
        documento = f"Usuário: {user_msg}\nAssistente: {assistant_msg}"
        timestamp = datetime.now().isoformat()
        doc_id = f"{session_id}_{timestamp}"

        embedding = await asyncio.to_thread(self._embed, documento)
        await asyncio.to_thread(
            self._conversas.add,
            documents=[documento],
            embeddings=[embedding],
            metadatas=[
                {
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "tipo": "conversa",
                }
            ],
            ids=[doc_id],
        )
        logger.debug(f"Conversa salva no VectorMemory: {doc_id}")

    async def buscar_contexto(self, query: str, n_resultados: int = 5) -> list[str]:
        """
        Busca conversas semanticamente relevantes no ChromaDB.

        Args:
            query: Texto de busca.
            n_resultados: Número máximo de resultados.

        Returns:
            Lista de conversas relevantes como strings.
        """
        try:
            embedding = await asyncio.to_thread(self._embed, query)
            return await self._buscar_documentos_por_embedding(
                self._conversas,
                embedding,
                n_resultados,
            )

        except Exception as exc:
            logger.error(f"Erro ao buscar contexto no VectorMemory: {exc}")
            return []

    async def salvar_fato(self, fato: str, categoria: str = "geral") -> None:
        """
        Armazena um fato sobre o usuário no ChromaDB.

        Args:
            fato: Fato a ser armazenado (ex: "usuário prefere respostas curtas").
            categoria: Categoria do fato.
        """
        timestamp = datetime.now().isoformat()
        doc_id = f"fato_{timestamp}"

        embedding = await asyncio.to_thread(self._embed, fato)
        await asyncio.to_thread(
            self._fatos.add,
            documents=[fato],
            embeddings=[embedding],
            metadatas=[
                {
                    "tipo": "fato",
                    "categoria": categoria,
                    "timestamp": timestamp,
                }
            ],
            ids=[doc_id],
        )
        logger.debug(f"Fato salvo no VectorMemory: {fato[:50]}...")

    async def buscar_fatos(self, query: str) -> list[str]:
        """
        Busca fatos relevantes sobre o usuário no ChromaDB.

        Args:
            query: Texto de busca.

        Returns:
            Lista de fatos relevantes.
        """
        try:
            total = await asyncio.to_thread(self._fatos.count)
            if total == 0:
                return []

            embedding = await asyncio.to_thread(self._embed, query)
            resultados = await asyncio.to_thread(
                self._fatos.query,
                query_embeddings=[embedding],
                n_results=min(5, total),
            )

            documentos = resultados.get("documents", [[]])
            return documentos[0] if documentos else []

        except Exception as exc:
            logger.error(f"Erro ao buscar fatos no VectorMemory: {exc}")
            return []

    async def buscar_contextos_relevantes(
        self,
        query: str,
        n_resultados_contexto: int = 5,
        n_resultados_fatos: int = 5,
    ) -> tuple[list[str], list[str]]:
        """
        Busca conversas e fatos reutilizando o mesmo embedding da query.

        Args:
            query: Texto de busca.
            n_resultados_contexto: Máximo de conversas relevantes.
            n_resultados_fatos: Máximo de fatos relevantes.

        Returns:
            Tupla com (conversas, fatos).
        """
        try:
            embedding = await asyncio.to_thread(self._embed, query)
            conversas_task = self._buscar_documentos_por_embedding(
                self._conversas,
                embedding,
                n_resultados_contexto,
            )
            fatos_task = self._buscar_documentos_por_embedding(
                self._fatos,
                embedding,
                n_resultados_fatos,
            )
            return await asyncio.gather(conversas_task, fatos_task)
        except Exception as exc:
            logger.error(f"Erro ao buscar contextos relevantes no VectorMemory: {exc}")
            return [], []


@dataclass(slots=True)
class PersistenceJob:
    """Representa um job de persistência assíncrona."""

    kind: Literal["history", "vector_conversation"]
    payload: dict[str, Any]


class PersistenceWorker:
    """Executa persistência fora do caminho crítico da resposta."""

    QUEUE_MAXSIZE = 512

    def __init__(self) -> None:
        """Inicializa filas e tasks do worker."""
        self._history_queue: asyncio.Queue[PersistenceJob | None] | None = None
        self._vector_queue: asyncio.Queue[PersistenceJob | None] | None = None
        self._history_task: asyncio.Task[None] | None = None
        self._vector_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Inicia os workers de histórico e memória vetorial."""
        if self._history_queue is None:
            self._history_queue = asyncio.Queue(maxsize=self.QUEUE_MAXSIZE)
        if self._vector_queue is None:
            self._vector_queue = asyncio.Queue(maxsize=self.QUEUE_MAXSIZE)
        if self._history_task is None:
            self._history_task = asyncio.create_task(
                self._run_history_worker(),
                name="pulsar-history-persistence",
            )
        if self._vector_task is None:
            self._vector_task = asyncio.create_task(
                self._run_vector_worker(),
                name="pulsar-vector-persistence",
            )
        logger.info("PersistenceWorker iniciado")

    async def stop(self) -> None:
        """Drena as filas e encerra os workers graciosamente."""
        await self._drain_queue(self._history_queue, self._history_task)
        await self._drain_queue(self._vector_queue, self._vector_task)
        self._history_queue = None
        self._vector_queue = None
        self._history_task = None
        self._vector_task = None
        logger.info("PersistenceWorker encerrado")

    async def _drain_queue(
        self,
        queue: asyncio.Queue[PersistenceJob | None] | None,
        task: asyncio.Task[None] | None,
    ) -> None:
        """Aguarda a fila esvaziar e finaliza a task correspondente."""
        if task is None or queue is None:
            return

        await queue.join()
        await queue.put(None)
        await task

    def enqueue_history_save(
        self,
        session_id: str,
        history: list[dict[str, Any]],
    ) -> bool:
        """
        Agenda persistência do histórico da sessão.

        Args:
            session_id: ID da sessão.
            history: Snapshot do histórico.

        Returns:
            True se enfileirado com sucesso.
        """
        if self._history_queue is None:
            logger.warning(
                "Worker de histórico ainda não iniciado; salvamento ignorado"
            )
            return False

        job = PersistenceJob(
            kind="history",
            payload={
                "session_id": session_id,
                "history": [message.copy() for message in history],
            },
        )
        return self._put_nowait(self._history_queue, job)

    def enqueue_vector_conversation(
        self,
        session_id: str,
        user_msg: str,
        assistant_msg: str,
    ) -> bool:
        """
        Agenda gravação da conversa na memória vetorial.

        Args:
            session_id: ID da sessão.
            user_msg: Mensagem do usuário.
            assistant_msg: Resposta do assistente.

        Returns:
            True se enfileirado com sucesso.
        """
        if self._vector_queue is None:
            logger.warning("Worker vetorial ainda não iniciado; salvamento ignorado")
            return False

        if not assistant_msg.strip():
            return False

        job = PersistenceJob(
            kind="vector_conversation",
            payload={
                "session_id": session_id,
                "user_msg": user_msg,
                "assistant_msg": assistant_msg,
            },
        )
        return self._put_nowait(self._vector_queue, job)

    def _put_nowait(
        self,
        queue: asyncio.Queue[PersistenceJob | None],
        job: PersistenceJob,
    ) -> bool:
        """Insere um job na fila sem bloquear a resposta do usuário."""
        try:
            queue.put_nowait(job)
            return True
        except asyncio.QueueFull:
            logger.warning(
                f"Fila de persistência cheia; job descartado: kind={job.kind}"
            )
            return False

    async def _run_history_worker(self) -> None:
        """Processa jobs de persistência de histórico."""
        if self._history_queue is None:
            return

        while True:
            job = await self._history_queue.get()
            try:
                if job is None:
                    return

                await asyncio.to_thread(
                    persistent_memory.save,
                    job.payload["session_id"],
                    job.payload["history"],
                )
            except Exception as exc:
                logger.error(f"Erro no worker de histórico: {exc}")
            finally:
                self._history_queue.task_done()

    async def _run_vector_worker(self) -> None:
        """Processa jobs de persistência vetorial."""
        if self._vector_queue is None:
            return

        while True:
            job = await self._vector_queue.get()
            try:
                if job is None:
                    return

                vector = get_vector_memory_if_ready()
                if vector is None:
                    continue

                await vector.salvar_conversa(
                    job.payload["session_id"],
                    job.payload["user_msg"],
                    job.payload["assistant_msg"],
                )
            except Exception as exc:
                logger.error(f"Erro no worker vetorial: {exc}")
            finally:
                self._vector_queue.task_done()


session_memory = SessionMemory()
persistent_memory = PersistentMemory()
persistence_worker = PersistenceWorker()

vector_memory: VectorMemory | None = None
_vector_memory_failed = False
_vector_memory_loading = False
_vector_memory_state_lock = threading.Lock()


def get_vector_memory_if_ready() -> VectorMemory | None:
    """
    Retorna a memória vetorial apenas se já estiver carregada.

    Returns:
        Instância pronta ou None sem bloquear o fluxo atual.
    """
    return vector_memory


async def get_vector_memory() -> VectorMemory | None:
    """
    Inicializa a memória vetorial sob demanda.

    Returns:
        Instância pronta ou None em caso de falha.
    """
    global _vector_memory_failed

    if vector_memory is not None:
        return vector_memory

    if _vector_memory_failed:
        return None

    request_vector_memory_warmup()
    return None


def _initialize_vector_memory_background() -> None:
    """Inicializa a memória vetorial em thread daemon para não travar o shutdown."""
    global vector_memory, _vector_memory_failed, _vector_memory_loading

    try:
        instance = VectorMemory()
        with _vector_memory_state_lock:
            vector_memory = instance
            _vector_memory_failed = False
    except Exception as exc:
        with _vector_memory_state_lock:
            _vector_memory_failed = True
        logger.warning(f"VectorMemory não pôde ser inicializado: {exc}")
    finally:
        with _vector_memory_state_lock:
            _vector_memory_loading = False


def request_vector_memory_warmup() -> None:
    """Dispara aquecimento da memória vetorial sem bloquear o fluxo atual."""
    global _vector_memory_loading

    with _vector_memory_state_lock:
        if vector_memory is not None or _vector_memory_failed or _vector_memory_loading:
            return
        _vector_memory_loading = True

    thread = threading.Thread(
        target=_initialize_vector_memory_background,
        daemon=True,
        name="pulsar-vector-memory-warmup",
    )
    thread.start()


async def warmup_vector_memory() -> None:
    """Aquece a memória vetorial em background sem bloquear o startup."""
    request_vector_memory_warmup()


def schedule_conversation_persistence(
    session_id: str,
    history: list[dict[str, Any]],
    user_msg: str,
    assistant_msg: str,
) -> None:
    """
    Agenda persistência do histórico e da conversa vetorial.

    Args:
        session_id: ID da sessão.
        history: Snapshot do histórico atualizado.
        user_msg: Mensagem do usuário.
        assistant_msg: Resposta do assistente.
    """
    started_at = time.perf_counter()
    persistence_worker.enqueue_history_save(session_id, history)
    request_vector_memory_warmup()
    persistence_worker.enqueue_vector_conversation(
        session_id,
        user_msg,
        assistant_msg,
    )
    add_request_metric(
        "persist_queue_ms",
        (time.perf_counter() - started_at) * 1000,
    )
