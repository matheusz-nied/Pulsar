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

import base64
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel


# --- Configuração do Ambiente ---

# Carrega variáveis do .env na raiz do projeto (assistente_local/.env)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# Backend imports (precisam do .env carregado para inicializar o agente)
from backend.agent.agent import agent  # noqa: E402
from backend.agent.memory import persistent_memory, session_memory, vector_memory  # noqa: E402
from backend.audio.stt import get_stt  # noqa: E402
from backend.audio.tts import get_tts  # noqa: E402
from backend.core.logging_config import read_last_lines, setup_logging  # noqa: E402
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
    
    # Inicializar APScheduler para alarmes
    from backend.tools.system import iniciar_scheduler
    iniciar_scheduler()
    
    yield
    
    # Parar APScheduler graciosamente
    from backend.tools.system import parar_scheduler
    parar_scheduler()
    
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
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
        "tauri://localhost",  # Tauri app
    ],
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
    # Verifica status do Ollama (fallback offline)
    ollama_status = "offline"
    if hasattr(agent, "ollama_agent") and agent.ollama_agent:
        try:
            if await agent.ollama_agent.check_ollama():
                ollama_status = "online"
        except Exception as e:
            logger.debug(f"Health check Ollama falhou: {e}")

    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        components={
            "llm_claude": "online",  # Assume online se o servidor está rodando
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

    try:
        # a. Carregar histórico da sessão
        historico = session_memory.get_history(session_id)

        # b. Chamar agente com mensagem e histórico (inclui busca/save na memória vetorial)
        agent_response = await agent.processar(request.mensagem, historico, session_id=session_id)  # type: ignore[arg-type]

        # c. Adicionar mensagem do usuário E resposta do agente ao histórico
        session_memory.add_message(session_id, "user", request.mensagem)
        session_memory.add_message(session_id, "assistant", agent_response.resposta)

        # d. Persistir histórico atualizado
        persistent_memory.save(session_id, session_memory.get_history(session_id))

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
    session_id: str | None = Form(None, description="ID da sessão para manter contexto"),
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

    try:
        # Gera session_id se não fornecido
        session_id = session_id or str(uuid.uuid4())

        # 1. Salvar arquivo temporário
        temp_filename = f"input_{uuid.uuid4()}.wav"
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
        stt = get_stt(model_size="base")  # Usa modelo base para melhor performance
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
        agent_response = await agent.processar(transcricao, historico, session_id=session_id)  # type: ignore[arg-type]

        # 4. Atualizar histórico da sessão
        session_memory.add_message(session_id, "user", transcricao)
        session_memory.add_message(session_id, "assistant", agent_response.resposta)
        persistent_memory.save(session_id, session_memory.get_history(session_id))

        logger.info(f"Resposta gerada (sessão {session_id}): {agent_response.resposta}")

        # 5. Sintetizar resposta (TTS)
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
            return NotifyResponse(enviado=True, detalhe="Notificação enviada com sucesso.")

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
    limite: int = Query(default=50, ge=1, le=500, description="Número máximo de linhas."),
) -> list[str]:
    """Lê as últimas N linhas do arquivo de log conforme o tipo informado."""
    try:
        linhas = read_last_lines(tipo=tipo, limite=limite)
        logger.debug("Endpoint /logs consultado: tipo={} limite={} linhas={}", tipo, limite, len(linhas))
        return linhas
    except Exception as exc:
        logger.error("Erro ao consultar logs: {}", exc)
        raise HTTPException(status_code=500, detail="Erro ao consultar logs.")


# --- WebSocket ---

@app.websocket("/ws/audio")
async def websocket_audio(ws: WebSocket) -> None:
    """
    WebSocket para processamento de áudio em streaming.

    Protocolo de mensagens (JSON):
    - Cliente envia: {"type": "audio_chunk", "data": "<base64>", "session_id": "<id>"}
    - Cliente envia: {"type": "audio_end", "session_id": "<id>"}
    - Servidor responde: {"type": "transcricao", "texto": str}
    - Servidor responde: {"type": "resposta_chunk", "texto": str}
    - Servidor responde: {"type": "audio_ready", "url": str}
    - Servidor responde: {"type": "erro", "mensagem": str}
    """
    await ws.accept()
    logger.info("WebSocket /ws/audio: conexão aceita")

    audio_buffer: bytearray = bytearray()
    session_id: str = str(uuid.uuid4())

    try:
        while True:
            raw = await ws.receive_text()

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
                        {"type": "erro", "mensagem": "Campo 'data' vazio no audio_chunk"}
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
                        {"type": "erro", "mensagem": "Nenhum áudio recebido antes de audio_end"}
                    )
                    continue

                temp_audio_path: Path | None = None
                try:
                    # 1. Salvar áudio temporário
                    temp_filename = f"ws_input_{uuid.uuid4()}.wav"
                    temp_audio_path = Path("/tmp") / temp_filename
                    temp_audio_path.write_bytes(bytes(audio_buffer))
                    audio_buffer.clear()

                    logger.info(
                        f"WS audio_end: {temp_audio_path.stat().st_size} bytes "
                        f"(session={session_id})"
                    )

                    # 2. Transcrever (STT)
                    stt = get_stt(model_size="base")
                    transcricao = await stt.transcrever(str(temp_audio_path))

                    await ws.send_json({"type": "transcricao", "texto": transcricao})
                    logger.info(f"WS transcricao: {transcricao[:80]}...")

                    # 3. Processar com agente (streaming com contexto vetorial)
                    historico = session_memory.get_history(session_id)
                    resposta_completa = ""

                    async for chunk in agent.processar_stream(
                        transcricao, historico, session_id=session_id
                    ):
                        resposta_completa += chunk
                        await ws.send_json({"type": "resposta_chunk", "texto": chunk})

                    logger.info(f"WS resposta completa: {resposta_completa[:80]}...")

                    # 4. Atualizar histórico
                    session_memory.add_message(session_id, "user", transcricao)
                    session_memory.add_message(session_id, "assistant", resposta_completa)
                    persistent_memory.save(
                        session_id, session_memory.get_history(session_id)
                    )

                    # 5a. Salvar na memória vetorial (streaming não salva dentro do agent)
                    if vector_memory is not None:
                        await vector_memory.salvar_conversa(
                            session_id, transcricao, resposta_completa
                        )

                    # 6. Sintetizar resposta (TTS)
                    tts = get_tts()
                    audio_path = await tts.sintetizar(resposta_completa)
                    audio_filename = Path(audio_path).name

                    await ws.send_json(
                        {"type": "audio_ready", "url": f"/audio/{audio_filename}"}
                    )

                    logger.success(
                        f"WS pipeline concluída (session={session_id}): "
                        f"audio={audio_filename}"
                    )

                except Exception as e:
                    logger.error(f"WS erro no pipeline: {e}")
                    await ws.send_json(
                        {"type": "erro", "mensagem": f"Erro no processamento: {str(e)}"}
                    )
                finally:
                    if temp_audio_path and temp_audio_path.exists():
                        try:
                            temp_audio_path.unlink()
                        except Exception:
                            pass

            else:
                await ws.send_json(
                    {"type": "erro", "mensagem": f"Tipo de mensagem desconhecido: {msg_type}"}
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket /ws/audio: desconectado (session={session_id})")
    except Exception as e:
        logger.error(f"WebSocket /ws/audio erro: {e}")
        try:
            await ws.send_json({"type": "erro", "mensagem": str(e)})
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
