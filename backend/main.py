"""
main.py — FastAPI app principal do Assistente Virtual Local.

Responsável por:
- Definir os endpoints REST da API
- Configurar logging com loguru (console + arquivo)
- Carregar variáveis de ambiente do .env
- Gerenciar o ciclo de vida da aplicação
- Servir como ponto de entrada do backend
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, AsyncGenerator

import uvicorn
from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel

# --- Configuração do Ambiente ---

# Carrega variáveis do .env na raiz do projeto (assistente_local/.env)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# Backend imports (precisam do .env carregado para inicializar o agente)
from backend.agent.agent import agent, get_agent, get_loaded_agent  # noqa: E402
from backend.agent.memory import (  # noqa: E402
    persistence_worker,
    schedule_conversation_persistence,
    session_memory,
    warmup_vector_memory,
)
from backend.core.http_client import close_shared_http_clients  # noqa: E402
from backend.core.logging_config import (  # noqa: E402
    finish_request_metrics,
    get_request_metrics,
    read_last_lines,
    set_request_metric,
    setup_logging,
    start_request_metrics,
)
from backend.memory.database import db  # noqa: E402

# --- Configuração do Loguru ---

setup_logging()


# --- Models ---


class ConversarRequest(BaseModel):
    """Modelo de requisição para o endpoint /conversar."""

    mensagem: str
    session_id: str | None = None


class ConversarResponse(BaseModel):
    """Modelo de resposta do endpoint /conversar."""

    resposta: str
    session_id: str
    modelo_usado: str = "claude"  # "claude" | "ollama" | "erro"


class HealthResponse(BaseModel):
    """Modelo de resposta do endpoint /health."""

    status: str
    version: str
    components: dict[str, str]


class ErrorResponse(BaseModel):
    """Modelo de resposta de erro."""

    detail: str


class VoiceResponse(BaseModel):
    """Modelo de resposta do endpoint /voice."""

    transcricao: str
    resposta: str
    audio_url: str
    session_id: str
    modelo_usado: str = "claude"  # "claude" | "ollama" | "erro"


class NotifyRequest(BaseModel):
    """Modelo de requisição para o endpoint /notify."""

    mensagem: str


class NotifyResponse(BaseModel):
    """Modelo de resposta para o endpoint /notify."""

    enviado: bool
    detalhe: str


def _json_stream_event(payload: dict[str, Any]) -> str:
    """Serializa um evento em JSON Lines para streaming HTTP."""
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _resolver_extensao_upload_audio(audio: UploadFile) -> str:
    """
    Resolve uma extensao segura para salvar uploads de audio temporarios.

    Args:
        audio: Arquivo enviado pelo cliente.

    Returns:
        Extensao com ponto inicial, ex: ".webm" ou ".mp3".
    """
    extensoes_permitidas = {
        ".wav",
        ".mp3",
        ".webm",
        ".ogg",
        ".m4a",
        ".mp4",
        ".aac",
        ".flac",
    }
    if audio.filename:
        suffix = Path(audio.filename).suffix.lower()
        if suffix in extensoes_permitidas:
            return suffix

    content_type = (audio.content_type or "").split(";", maxsplit=1)[0].strip()
    content_type_map = {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/wave": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "application/ogg": ".ogg",
        "audio/mp4": ".mp4",
        "audio/x-m4a": ".m4a",
        "audio/aac": ".aac",
        "audio/flac": ".flac",
    }
    return content_type_map.get(content_type, ".webm")


def _extrair_frases_tts(
    buffer: str,
    min_chars: int = 18,
) -> tuple[list[str], str]:
    """
    Extrai frases prontas para TTS incremental a partir do buffer.

    Args:
        buffer: Texto acumulado até o momento.
        min_chars: Tamanho mínimo para fragmentos curtos.

    Returns:
        Tupla com (frases_prontas, restante_do_buffer).
    """
    frases: list[str] = []
    inicio = 0
    pontuacao_forte = ".!?:"
    pontuacao_fraca = ";"
    min_chars_virgula = 72

    for idx, char in enumerate(buffer):
        if char not in pontuacao_forte and char not in pontuacao_fraca and char != ",":
            continue

        frase = buffer[inicio : idx + 1].strip()
        if not frase:
            inicio = idx + 1
            continue

        if char == "," and len(frase) < min_chars_virgula:
            continue

        if char in pontuacao_fraca and len(frase) < min_chars:
            continue

        if len(frase) < 8:
            continue

        frases.append(frase)
        inicio = idx + 1

    restante = buffer[inicio:].lstrip()
    return frases, restante


def _log_request_metrics(
    route: str,
    session_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Emite um log consolidado com as métricas coletadas na requisição.

    Args:
        route: Identificador da rota ou pipeline.
        session_id: Sessão associada à requisição.
        extra: Metadados adicionais para facilitar análise.
    """
    metrics = {
        name: round(value, 2) for name, value in sorted(get_request_metrics().items())
    }
    extra_payload = extra or {}
    logger.info(
        "Request metrics: route={} | session_id={} | metrics={} | extra={}",
        route,
        session_id,
        json.dumps(metrics, ensure_ascii=False),
        json.dumps(extra_payload, ensure_ascii=False),
    )


_stt_warmup_started = False
_stt_warmup_lock = threading.Lock()


def _warmup_stt_sync() -> None:
    """Carrega o STT em thread daemon para evitar cold start na primeira voz."""
    try:
        from backend.audio.stt import get_stt

        get_stt("small")
    except Exception as exc:
        logger.warning(f"Warmup de STT falhou: {exc}")


async def _warmup_agent_async() -> None:
    """Pré-carrega o agente principal em background sem travar o startup."""
    try:
        await asyncio.to_thread(get_agent)
    except Exception as exc:
        logger.warning(f"Warmup do agente falhou: {exc}")


def _request_stt_warmup() -> None:
    """Dispara aquecimento do STT em background sem bloquear o app."""
    global _stt_warmup_started

    with _stt_warmup_lock:
        if _stt_warmup_started:
            return
        _stt_warmup_started = True

    threading.Thread(
        target=_warmup_stt_sync,
        daemon=True,
        name="pulsar-stt-warmup",
    ).start()


async def _warmup_runtime_components() -> None:
    """Aquece componentes pesados em background sem bloquear o startup."""
    await warmup_vector_memory()
    _request_stt_warmup()
    asyncio.create_task(
        _warmup_agent_async(),
        name="pulsar-agent-warmup",
    )


# --- Lifecycle ---


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Gerencia o ciclo de vida da aplicação FastAPI.

    Startup: Inicializa serviços, loga informações do ambiente.
    Shutdown: Encerra conexões e limpa recursos.
    """
    logger.info("🚀 Assistente Virtual Local iniciando...")
    logger.info(f"Ambiente: {os.getenv('ENV', 'development')}")
    logger.info(f"Projeto raiz: {_PROJECT_ROOT}")

    # Inicializar banco de dados SQLite
    await db.inicializar()
    await persistence_worker.start()

    # Inicializar APScheduler para alarmes
    from backend.tools.system import iniciar_scheduler

    iniciar_scheduler()

    warmup_task = asyncio.create_task(
        _warmup_runtime_components(),
        name="pulsar-runtime-warmup",
    )
    app.state.warmup_task = warmup_task

    # Inicializar Wake Word Listener (Porcupine) se habilitado
    wake_listener = None
    if os.getenv("PORCUPINE_ACCESS_KEY", ""):
        try:
            from backend.audio.wake_word import get_wake_word_listener

            wake_listener = get_wake_word_listener()
            wake_listener.start(asyncio.get_event_loop())
        except Exception as e:
            logger.warning(f"Wake word desativado: {e}")

    yield

    # Parar Wake Word Listener
    if wake_listener is not None:
        wake_listener.stop()

    # Parar APScheduler graciosamente
    from backend.tools.system import parar_scheduler

    parar_scheduler()

    warmup_task = getattr(app.state, "warmup_task", None)
    if warmup_task is not None and not warmup_task.done():
        warmup_task.cancel()
        with suppress(asyncio.CancelledError):
            await warmup_task

    await persistence_worker.stop()
    await close_shared_http_clients()

    # Fechar conexão com banco de dados
    await db.fechar()

    logger.info("👋 Assistente Virtual Local encerrando...")


# --- App ---

APP_VERSION = "0.1.0"

app = FastAPI(
    title="Assistente Virtual Local",
    description="API do assistente virtual pessoal com IA",
    version=APP_VERSION,
    lifespan=lifespan,
)

# CORS configurado para desenvolvimento local
app.add_middleware(
    CORSMiddleware,
    # Em ambiente local/desktop (incluindo Tauri), é seguro liberar
    # todas as origens para evitar problemas de preflight/OPTIONS.
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Exception Handler Global ---


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Tratamento global de exceções não capturadas.

    Loga o erro completo e retorna uma mensagem amigável ao cliente.

    Args:
        request: Requisição HTTP que gerou o erro.
        exc: Exceção capturada.

    Returns:
        Resposta JSON com status 500 e mensagem amigável.
    """
    logger.error(
        f"Erro não tratado em {request.method} {request.url.path}: "
        f"{type(exc).__name__}: {exc}"
    )
    logger.exception(exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Ocorreu um erro interno no servidor. "
            "Tente novamente ou contacte o administrador."
        },
    )


# --- Endpoints ---


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Verifica o status de saúde da API e seus componentes.",
)
async def health_check() -> HealthResponse:
    """
    Retorna o status de saúde da API e seus componentes internos.

    Verifica conectividade com:
    - llm_claude: API da Anthropic (online/offline)
    - llm_ollama: Servidor local Ollama (online/offline)
    - memory: Sistema de memória (online)

    Returns:
        Status da API e de cada componente.
    """
    loaded_agent = get_loaded_agent()
    provider_name = os.getenv("LLM_PROVIDER", "claude").lower()
    primary_status = "online" if loaded_agent is not None else "lazy"

    # Verifica status do Ollama (fallback offline)
    ollama_status = "lazy"
    if loaded_agent is not None and loaded_agent.ollama_agent:
        try:
            if await loaded_agent.ollama_agent.check_ollama():
                ollama_status = "online"
            else:
                ollama_status = "offline"
        except Exception as e:
            logger.debug(f"Health check Ollama falhou: {e}")

    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        components={
            "llm_primary": primary_status,
            f"llm_{provider_name}": primary_status,
            "llm_ollama": ollama_status,
            "memory": "online",
        },
    )


@app.post(
    "/conversar",
    response_model=ConversarResponse,
    summary="Enviar mensagem ao assistente",
    description="Envia uma mensagem de texto e recebe a resposta do agente.",
    responses={
        400: {"model": ErrorResponse, "description": "Mensagem inválida"},
        500: {"model": ErrorResponse, "description": "Erro interno do servidor"},
    },
)
async def conversar(request: ConversarRequest) -> ConversarResponse:
    """
    Endpoint principal de conversação.

    Recebe uma mensagem do usuário, gera ou reutiliza um session_id,
    e retorna a resposta do agente.

    Args:
        request: Corpo da requisição com 'mensagem' e 'session_id' opcional.

    Returns:
        Resposta do agente e o session_id da conversa.

    Raises:
        HTTPException: 400 se a mensagem for vazia.
    """
    if not request.mensagem.strip():
        raise HTTPException(
            status_code=400,
            detail="A mensagem não pode ser vazia.",
        )

    # Gera um novo session_id se não fornecido
    session_id = request.session_id or str(uuid.uuid4())
    token = start_request_metrics()
    started_at = time.perf_counter()
    modelo_usado = "erro"

    try:
        # a. Carregar histórico da sessão
        historico = session_memory.get_history(session_id)

        # b. Chamar agente com mensagem e histórico (inclui busca/save na memória vetorial)
        agent_response = await agent.processar(
            request.mensagem, historico, session_id=session_id
        )  # type: ignore[arg-type]
        modelo_usado = agent_response.modelo_usado

        # c. Adicionar mensagem do usuário E resposta do agente ao histórico
        session_memory.add_message(session_id, "user", request.mensagem)
        session_memory.add_message(session_id, "assistant", agent_response.resposta)

        # d. Persistir fora do caminho crítico
        schedule_conversation_persistence(
            session_id,
            session_memory.get_history(session_id),
            request.mensagem,
            agent_response.resposta,
        )

        # e. Retornar resposta com session_id e modelo usado
        return ConversarResponse(
            resposta=agent_response.resposta,
            session_id=session_id,
            modelo_usado=agent_response.modelo_usado,
        )

    except Exception as e:
        logger.error(f"Erro ao processar mensagem na sessão {session_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erro ao processar sua mensagem. Tente novamente.",
        )
    finally:
        set_request_metric("total_ms", (time.perf_counter() - started_at) * 1000)
        _log_request_metrics(
            "/conversar",
            session_id,
            {
                "mensagem_chars": len(request.mensagem),
                "modelo_usado": modelo_usado,
            },
        )
        finish_request_metrics(token)


@app.post(
    "/conversar/stream",
    summary="Enviar mensagem ao assistente com streaming",
    description="Envia uma mensagem de texto e recebe chunks da resposta em tempo real.",
)
async def conversar_stream(request: ConversarRequest) -> StreamingResponse:
    """
    Endpoint de conversação com streaming HTTP em JSON Lines.

    Args:
        request: Corpo da requisição com 'mensagem' e 'session_id' opcional.

    Returns:
        StreamingResponse com eventos JSON Lines.
    """
    if not request.mensagem.strip():
        raise HTTPException(
            status_code=400,
            detail="A mensagem não pode ser vazia.",
        )

    session_id = request.session_id or str(uuid.uuid4())

    async def event_generator() -> AsyncGenerator[str, None]:
        token = start_request_metrics()
        started_at = time.perf_counter()
        resposta_completa = ""
        modelo_usado = "erro"

        try:
            historico = session_memory.get_history(session_id)
            yield _json_stream_event({"type": "session", "session_id": session_id})

            fast_path_response = await agent.try_fast_path(request.mensagem)  # type: ignore[attr-defined]
            if fast_path_response is not None:
                resposta_completa = fast_path_response.resposta
                modelo_usado = fast_path_response.modelo_usado

                if resposta_completa:
                    yield _json_stream_event(
                        {"type": "chunk", "texto": resposta_completa}
                    )

                session_memory.add_message(session_id, "user", request.mensagem)
                session_memory.add_message(session_id, "assistant", resposta_completa)
                schedule_conversation_persistence(
                    session_id,
                    session_memory.get_history(session_id),
                    request.mensagem,
                    resposta_completa,
                )
                yield _json_stream_event(
                    {
                        "type": "done",
                        "session_id": session_id,
                        "texto": resposta_completa,
                        "modelo_usado": modelo_usado,
                    }
                )
                return

            async for chunk in agent.processar_stream(
                request.mensagem,
                historico,
                session_id=session_id,
            ):
                resposta_completa += chunk
                yield _json_stream_event({"type": "chunk", "texto": chunk})

            if not resposta_completa.strip():
                yield _json_stream_event(
                    {
                        "type": "error",
                        "mensagem": "Não foi possível gerar uma resposta.",
                    }
                )
                return

            session_memory.add_message(session_id, "user", request.mensagem)
            session_memory.add_message(session_id, "assistant", resposta_completa)
            schedule_conversation_persistence(
                session_id,
                session_memory.get_history(session_id),
                request.mensagem,
                resposta_completa,
            )

            loaded_agent = get_loaded_agent()
            modelo_usado = (
                loaded_agent.llm.__class__.__name__
                if loaded_agent is not None
                else "lazy"
            )
            yield _json_stream_event(
                {
                    "type": "done",
                    "session_id": session_id,
                    "texto": resposta_completa,
                    "modelo_usado": modelo_usado,
                }
            )
        except Exception as exc:
            logger.error(f"Erro no streaming da sessão {session_id}: {exc}")
            yield _json_stream_event(
                {
                    "type": "error",
                    "mensagem": "Erro ao processar sua mensagem em streaming.",
                }
            )
        finally:
            set_request_metric("total_ms", (time.perf_counter() - started_at) * 1000)
            _log_request_metrics(
                "/conversar/stream",
                session_id,
                {
                    "mensagem_chars": len(request.mensagem),
                    "modelo_usado": modelo_usado,
                    "resposta_chars": len(resposta_completa),
                },
            )
            finish_request_metrics(token)

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(
    "/voice",
    response_model=VoiceResponse,
    summary="Processar mensagem de voz",
    description="Recebe áudio, transcreve, processa com o agente e retorna resposta em áudio.",
    responses={
        400: {"model": ErrorResponse, "description": "Arquivo de áudio inválido"},
        500: {"model": ErrorResponse, "description": "Erro interno do servidor"},
    },
)
async def processar_voz(
    audio: UploadFile = File(..., description="Arquivo de áudio (WAV, MP3, etc.)"),
    session_id: str | None = Form(
        None, description="ID da sessão para manter contexto"
    ),
) -> VoiceResponse:
    """
    Endpoint de processamento de voz.

    Fluxo completo:
    1. Recebe arquivo de áudio via multipart/form-data
    2. Salva temporariamente e transcreve com STT
    3. Processa texto com o agente
    4. Sintetiza resposta com TTS
    5. Retorna transcrição, resposta textual e URL do áudio

    Args:
        audio: Arquivo de áudio enviado pelo cliente.
        session_id: ID da sessão (opcional, será gerado se não fornecido).

    Returns:
        Transcrição, resposta do agente, URL do áudio e session_id.

    Raises:
        HTTPException: 400 se o arquivo for inválido, 500 em erros de processamento.
    """
    temp_audio_path: Path | None = None
    session_id = session_id or str(uuid.uuid4())
    token = start_request_metrics()
    started_at = time.perf_counter()
    modelo_usado = "erro"

    try:
        # 1. Salvar arquivo temporário
        temp_suffix = _resolver_extensao_upload_audio(audio)
        temp_filename = f"input_{uuid.uuid4()}{temp_suffix}"
        temp_audio_path = Path("/tmp") / temp_filename

        logger.info(
            f"Recebendo áudio: {audio.filename} "
            f"(content_type={audio.content_type}, session={session_id})"
        )

        # Salva o arquivo enviado
        content = await audio.read()
        if not content:
            raise HTTPException(
                status_code=400,
                detail="Arquivo de áudio vazio.",
            )

        temp_audio_path.write_bytes(content)
        logger.debug(f"Áudio salvo temporariamente em: {temp_audio_path}")

        # 2. Transcrever áudio (STT)
        from backend.audio.stt import get_stt

        stt = get_stt(model_size="small")
        transcricao = await stt.transcrever(str(temp_audio_path))

        if not transcricao.strip():
            raise HTTPException(
                status_code=400,
                detail="Não foi possível transcrever o áudio. "
                "Verifique se o áudio contém fala clara.",
            )

        logger.info(f"Transcrição (sessão {session_id}): {transcricao}")

        # 3. Processar com o agente (inclui busca/save na memória vetorial)
        historico = session_memory.get_history(session_id)
        agent_response = await agent.processar(
            transcricao, historico, session_id=session_id
        )  # type: ignore[arg-type]
        modelo_usado = agent_response.modelo_usado

        # 4. Atualizar histórico da sessão
        session_memory.add_message(session_id, "user", transcricao)
        session_memory.add_message(session_id, "assistant", agent_response.resposta)
        schedule_conversation_persistence(
            session_id,
            session_memory.get_history(session_id),
            transcricao,
            agent_response.resposta,
        )

        logger.info(f"Resposta gerada (sessão {session_id}): {agent_response.resposta}")

        # 5. Sintetizar resposta (TTS)
        from backend.audio.tts import get_tts

        tts = get_tts()
        audio_path = await tts.sintetizar(agent_response.resposta)
        audio_filename = Path(audio_path).name

        # 6. Gerar URL do áudio
        audio_url = f"/audio/{audio_filename}"

        logger.success(
            f"Processamento de voz concluído (sessão {session_id}): "
            f"transcricao={len(transcricao)} chars, "
            f"resposta={len(agent_response.resposta)} chars, "
            f"audio={audio_filename}"
        )

        return VoiceResponse(
            transcricao=transcricao,
            resposta=agent_response.resposta,
            audio_url=audio_url,
            session_id=session_id,
            modelo_usado=agent_response.modelo_usado,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao processar áudio na sessão {session_id}: {e}")
        logger.exception(e)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao processar áudio: {str(e)}",
        )
    finally:
        set_request_metric("total_ms", (time.perf_counter() - started_at) * 1000)
        _log_request_metrics(
            "/voice",
            session_id,
            {"audio_filename": audio.filename or "", "modelo_usado": modelo_usado},
        )
        finish_request_metrics(token)
        # Limpar arquivo temporário
        if temp_audio_path and temp_audio_path.exists():
            try:
                temp_audio_path.unlink()
                logger.debug(f"Arquivo temporário removido: {temp_audio_path}")
            except Exception as e:
                logger.warning(f"Erro ao remover arquivo temporário: {e}")


@app.get(
    "/audio/{filename}",
    summary="Servir arquivo de áudio",
    description="Retorna um arquivo MP3 do cache de áudio gerado pelo TTS.",
    responses={
        404: {"model": ErrorResponse, "description": "Arquivo não encontrado"},
    },
)
async def servir_audio(filename: str) -> FileResponse:
    """
    Serve arquivos de áudio MP3 do cache do TTS.

    Args:
        filename: Nome do arquivo MP3 (hash MD5 + .mp3).

    Returns:
        Arquivo MP3 para download/streaming.

    Raises:
        HTTPException: 404 se o arquivo não existir.
    """
    from backend.audio.tts import get_tts

    # Validar que o filename não contém caracteres perigosos
    if ".." in filename or "/" in filename:
        raise HTTPException(
            status_code=400,
            detail="Nome de arquivo inválido.",
        )

    # Validar extensão
    if not filename.endswith(".mp3"):
        raise HTTPException(
            status_code=400,
            detail="Apenas arquivos .mp3 são suportados.",
        )

    # Montar caminho do arquivo
    tts = get_tts()
    audio_path = tts.cache_path / filename

    # Verificar se existe
    if not audio_path.exists():
        logger.warning(f"Arquivo de áudio não encontrado: {filename}")
        raise HTTPException(
            status_code=404,
            detail="Arquivo de áudio não encontrado.",
        )

    logger.debug(f"Servindo áudio: {filename} ({audio_path.stat().st_size} bytes)")

    return FileResponse(
        path=str(audio_path),
        media_type="audio/mpeg",
        filename=filename,
    )


@app.get(
    "/agendamentos",
    summary="Listar agendamentos ativos",
    description="Retorna alarmes agendados em formato estruturado para integrações externas.",
)
async def listar_agendamentos() -> dict[str, Any]:
    """Lista os alarmes ativos no scheduler em formato JSON estruturado."""
    try:
        from backend.tools.system import scheduler

        if scheduler is None:
            return {"alarmes": [], "total": 0}

        alarmes: list[dict[str, str]] = []
        for job in scheduler.get_jobs():
            horario = ""
            if job.next_run_time is not None:
                horario = job.next_run_time.isoformat()

            mensagem = ""
            if job.args and len(job.args) > 0 and isinstance(job.args[0], str):
                mensagem = job.args[0]

            alarmes.append(
                {
                    "id": job.id,
                    "horario": horario,
                    "mensagem": mensagem,
                }
            )

        return {"alarmes": alarmes, "total": len(alarmes)}
    except Exception as exc:
        logger.error("Erro ao listar agendamentos: {}", exc)
        raise HTTPException(status_code=500, detail="Erro ao listar agendamentos.")


@app.post(
    "/notify",
    response_model=NotifyResponse,
    summary="Enviar notificação via Telegram",
    description="Recebe uma mensagem e envia para o chat do dono no Telegram.",
)
async def notify_telegram(payload: NotifyRequest) -> NotifyResponse:
    """Encaminha uma mensagem de notificação para o dono via bot do Telegram."""
    if not payload.mensagem.strip():
        raise HTTPException(status_code=400, detail="A mensagem não pode ser vazia.")

    try:
        from telegram_bot.bot import send_notification

        enviado = await send_notification(payload.mensagem.strip())
        if enviado:
            return NotifyResponse(
                enviado=True, detalhe="Notificação enviada com sucesso."
            )

        return NotifyResponse(
            enviado=False,
            detalhe="Não foi possível enviar notificação. Verifique TELEGRAM_OWNER_ID e TELEGRAM_BOT_TOKEN.",
        )
    except Exception as exc:
        logger.error("Erro no endpoint /notify: {}", exc)
        raise HTTPException(status_code=500, detail="Erro ao enviar notificação.")


@app.get(
    "/logs",
    response_model=list[str],
    summary="Ler logs da aplicação",
    description="Retorna as últimas linhas do arquivo de log conforme tipo e limite.",
)
async def obter_logs(
    tipo: str = Query(default="acoes", description="Tipo do log: acoes ou erros."),
    limite: int = Query(
        default=50, ge=1, le=500, description="Número máximo de linhas."
    ),
) -> list[str]:
    """Lê as últimas N linhas do arquivo de log conforme o tipo informado."""
    try:
        linhas = read_last_lines(tipo=tipo, limite=limite)
        logger.debug(
            "Endpoint /logs consultado: tipo={} limite={} linhas={}",
            tipo,
            limite,
            len(linhas),
        )
        return linhas
    except Exception as exc:
        logger.error("Erro ao consultar logs: {}", exc)
        raise HTTPException(status_code=500, detail="Erro ao consultar logs.")


# --- WebSocket ---


@app.websocket("/ws/audio")
async def websocket_audio(ws: WebSocket) -> None:
    """
    WebSocket para processamento de áudio em streaming.

    Protocolo de mensagens:
    - Cliente envia: frames binários WebM/Opus com áudio incremental
    - Cliente também pode enviar: {"type": "audio_chunk", "data": "<base64>", "session_id": "<id>"} para compatibilidade
    - Cliente envia: {"type": "audio_end", "session_id": "<id>"}
    - Servidor responde: {"type": "transcricao", "texto": str}
    - Servidor responde: {"type": "resposta_chunk", "texto": str}
    - Servidor responde: {"type": "audio_chunk", "url": str}
    - Servidor responde: {"type": "audio_ready", "url": str}
    - Servidor responde: {"type": "erro", "mensagem": str}
    """
    await ws.accept()
    logger.info("WebSocket /ws/audio: conexão aceita")

    audio_buffer: bytearray = bytearray()
    session_id: str = str(uuid.uuid4())

    try:
        while True:
            event = await ws.receive()
            event_type = event.get("type")
            if event_type == "websocket.disconnect":
                logger.info(f"WebSocket /ws/audio: desconectado (session={session_id})")
                break

            data_bytes = event.get("bytes")
            if data_bytes is not None:
                audio_buffer.extend(data_bytes)
                continue

            raw = event.get("text")
            if raw is None:
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "erro", "mensagem": "JSON inválido"})
                continue

            msg_type = msg.get("type")

            # Atualiza session_id se fornecido
            if msg.get("session_id"):
                session_id = msg["session_id"]

            # --- audio_chunk: acumular dados ---
            if msg_type == "audio_chunk":
                data_b64 = msg.get("data", "")
                if not data_b64:
                    await ws.send_json(
                        {
                            "type": "erro",
                            "mensagem": "Campo 'data' vazio no audio_chunk",
                        }
                    )
                    continue
                try:
                    audio_buffer.extend(base64.b64decode(data_b64))
                except Exception:
                    await ws.send_json(
                        {"type": "erro", "mensagem": "Base64 inválido no campo 'data'"}
                    )
                    continue

            # --- audio_end: processar pipeline completa ---
            elif msg_type == "audio_end":
                if not audio_buffer:
                    await ws.send_json(
                        {
                            "type": "erro",
                            "mensagem": "Nenhum áudio recebido antes de audio_end",
                        }
                    )
                    continue

                token = start_request_metrics()
                started_at = time.perf_counter()
                modelo_usado = "erro"
                audio_size = len(audio_buffer)
                temp_audio_path: Path | None = None
                phrase_queue: asyncio.Queue[str | None] | None = None
                tts_task: asyncio.Task[None] | None = None
                try:
                    # 1. Salvar áudio temporário no formato enviado pelo browser
                    temp_filename = f"ws_input_{uuid.uuid4()}.webm"
                    temp_audio_path = Path("/tmp") / temp_filename
                    temp_audio_path.write_bytes(bytes(audio_buffer))
                    audio_buffer.clear()

                    logger.info(
                        f"WS audio_end: {temp_audio_path.stat().st_size} bytes "
                        f"(session={session_id})"
                    )

                    # 2. Transcrever (STT)
                    from backend.audio.stt import get_stt

                    stt = get_stt(model_size="small")
                    transcricao = await stt.transcrever(str(temp_audio_path))

                    await ws.send_json({"type": "transcricao", "texto": transcricao})
                    logger.info(f"WS transcricao: {transcricao[:80]}...")

                    resposta_completa = ""
                    frase_buffer = ""
                    audio_chunk_urls: list[str] = []
                    from backend.audio.tts import get_tts

                    tts = get_tts()
                    phrase_queue = asyncio.Queue()

                    async def tts_worker() -> None:
                        while True:
                            frase = await phrase_queue.get()
                            try:
                                if frase is None:
                                    return

                                audio_path = await tts.sintetizar_frase(frase)
                                audio_filename = Path(audio_path).name
                                audio_url = f"/audio/{audio_filename}"
                                audio_chunk_urls.append(audio_url)
                                set_request_metric(
                                    "tts_chunks",
                                    float(len(audio_chunk_urls)),
                                )
                                await ws.send_json(
                                    {"type": "audio_chunk", "url": audio_url}
                                )
                            except Exception as exc:
                                logger.warning(
                                    "WS falhou ao sintetizar frase para TTS incremental: {}",
                                    exc,
                                )
                            finally:
                                phrase_queue.task_done()

                    tts_task = asyncio.create_task(
                        tts_worker(),
                        name=f"pulsar-ws-audio-tts-{session_id}",
                    )

                    fast_path_response = await agent.try_fast_path(transcricao)  # type: ignore[attr-defined]
                    if fast_path_response is not None:
                        resposta_completa = fast_path_response.resposta
                        modelo_usado = fast_path_response.modelo_usado
                        if resposta_completa:
                            await ws.send_json(
                                {
                                    "type": "resposta_chunk",
                                    "texto": resposta_completa,
                                }
                            )
                            frase_buffer += resposta_completa
                            frases_prontas, frase_buffer = _extrair_frases_tts(
                                frase_buffer
                            )
                            for frase in frases_prontas:
                                await phrase_queue.put(frase)
                    else:
                        # 3. Processar com agente (streaming com contexto vetorial)
                        historico = session_memory.get_history(session_id)
                        async for chunk in agent.processar_stream(
                            transcricao, historico, session_id=session_id
                        ):
                            resposta_completa += chunk
                            frase_buffer += chunk
                            await ws.send_json(
                                {"type": "resposta_chunk", "texto": chunk}
                            )
                            frases_prontas, frase_buffer = _extrair_frases_tts(
                                frase_buffer
                            )
                            for frase in frases_prontas:
                                await phrase_queue.put(frase)

                        loaded_agent = get_loaded_agent()
                        modelo_usado = (
                            loaded_agent.llm.__class__.__name__
                            if loaded_agent is not None
                            else "lazy"
                        )

                    logger.info(f"WS resposta completa: {resposta_completa[:80]}...")

                    # 4. Atualizar histórico
                    session_memory.add_message(session_id, "user", transcricao)
                    session_memory.add_message(
                        session_id, "assistant", resposta_completa
                    )
                    schedule_conversation_persistence(
                        session_id,
                        session_memory.get_history(session_id),
                        transcricao,
                        resposta_completa,
                    )

                    # 5. Finalizar TTS incremental (flush do restante)
                    if frase_buffer.strip():
                        await phrase_queue.put(frase_buffer.strip())
                    await phrase_queue.put(None)
                    await phrase_queue.join()
                    await tts_task

                    await ws.send_json(
                        {
                            "type": "audio_ready",
                            "url": audio_chunk_urls[0] if audio_chunk_urls else "",
                        }
                    )

                    logger.success(
                        f"WS pipeline concluída (session={session_id}): "
                        f"audio_chunks={len(audio_chunk_urls)}"
                    )

                except Exception as e:
                    logger.error(f"WS erro no pipeline: {e}")
                    await ws.send_json(
                        {"type": "erro", "mensagem": f"Erro no processamento: {str(e)}"}
                    )
                finally:
                    if tts_task is not None and not tts_task.done():
                        if phrase_queue is not None:
                            with suppress(asyncio.QueueFull):
                                await phrase_queue.put(None)
                        tts_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await tts_task
                    set_request_metric(
                        "total_ms", (time.perf_counter() - started_at) * 1000
                    )
                    _log_request_metrics(
                        "/ws/audio",
                        session_id,
                        {
                            "audio_bytes": audio_size,
                            "modelo_usado": modelo_usado,
                        },
                    )
                    finish_request_metrics(token)
                    if temp_audio_path and temp_audio_path.exists():
                        try:
                            temp_audio_path.unlink()
                        except Exception:
                            pass

            else:
                await ws.send_json(
                    {
                        "type": "erro",
                        "mensagem": f"Tipo de mensagem desconhecido: {msg_type}",
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket /ws/audio: desconectado (session={session_id})")
    except Exception as e:
        logger.error(f"WebSocket /ws/audio erro: {e}")
        try:
            await ws.send_json({"type": "erro", "mensagem": str(e)})
        except Exception:
            pass


# --- WebSocket: eventos de voz (wake word, STT, resposta, TTS) ---


@app.websocket("/ws/voice")
async def websocket_voice(ws: WebSocket) -> None:
    """
    WebSocket para o frontend receber eventos do pipeline de voz.

    O cliente se conecta e apenas escuta — o servidor empurra eventos:
      {"type": "wake_word"}                  → wake word detectada
      {"type": "transcricao", "texto": ...}  → STT concluído
      {"type": "resposta_chunk", "texto": ...} → chunk de resposta do agente
      {"type": "audio_chunk", "url": ...}    → segmento de TTS pronto
      {"type": "audio_ready", "url": ...}    → TTS pronto para reproduzir
      {"type": "voice_idle"}                 → pipeline encerrou sem áudio válido
      {"type": "erro", "mensagem": ...}      → erro no pipeline
    """
    await ws.accept()
    logger.info("WebSocket /ws/voice: cliente conectado")

    # Registra callback que envia eventos para este cliente
    async def _send(event: dict) -> None:
        await ws.send_json(event)

    try:
        from backend.audio.wake_word import (
            register_voice_listener,
            unregister_voice_listener,
        )

        register_voice_listener(_send)

        # Mantém conexão viva até o cliente desconectar
        while True:
            try:
                # Aguarda mensagem (keep-alive ou configuração futura)
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                # Aceitar ping do cliente para manter conexão
                if msg == "ping":
                    await ws.send_text("pong")
            except asyncio.TimeoutError:
                # Envia keep-alive para evitar timeout do proxy/OS
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info("WebSocket /ws/voice: cliente desconectado")
    except Exception as e:
        logger.error(f"WebSocket /ws/voice erro: {e}")
    finally:
        try:
            from backend.audio.wake_word import unregister_voice_listener

            unregister_voice_listener(_send)
        except Exception:
            pass


# --- Entrypoint ---

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
