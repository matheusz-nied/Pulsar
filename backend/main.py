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

import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel


# --- Configuração do Ambiente ---

# Carrega variáveis do .env na raiz do projeto (assistente_local/.env)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


# --- Configuração do Loguru ---

# Remove o handler padrão do loguru para reconfigurar
logger.remove()

# Log no console com formato colorido
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
           "<level>{level: <8}</level> | "
           "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
           "<level>{message}</level>",
    level="DEBUG",
    colorize=True,
)

# Log em arquivo com rotação diária e retenção de 30 dias
_LOGS_DIR = _PROJECT_ROOT / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger.add(
    str(_LOGS_DIR / "app.log"),
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    level="INFO",
    rotation="00:00",  # Rotação diária à meia-noite
    retention="30 days",
    compression="zip",
    encoding="utf-8",
)


# --- Models ---

class ConversarRequest(BaseModel):
    """Modelo de requisição para o endpoint /conversar."""
    mensagem: str
    session_id: str | None = None


class ConversarResponse(BaseModel):
    """Modelo de resposta do endpoint /conversar."""
    resposta: str
    session_id: str


class HealthResponse(BaseModel):
    """Modelo de resposta do endpoint /health."""
    status: str
    version: str
    components: dict[str, str]


class ErrorResponse(BaseModel):
    """Modelo de resposta de erro."""
    detail: str


# --- Funções Placeholder ---

async def processar_mensagem(mensagem: str, session_id: str) -> str:
    """
    Processa uma mensagem do usuário (placeholder).

    Será substituída pela integração real com LangGraph + Claude
    na próxima fase do projeto.

    Args:
        mensagem: Texto enviado pelo usuário.
        session_id: ID da sessão de conversa.

    Returns:
        Resposta gerada pelo agente.
    """
    logger.info(f"Processando mensagem na sessão {session_id}: {mensagem[:80]}...")
    return f"Processando: {mensagem}"


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
    yield
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

    Returns:
        Status da API e de cada componente (llm, memory).
    """
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        components={
            "llm": "online",
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
        resposta = await processar_mensagem(request.mensagem, session_id)
        return ConversarResponse(resposta=resposta, session_id=session_id)
    except Exception as e:
        logger.error(f"Erro ao processar mensagem na sessão {session_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erro ao processar sua mensagem. Tente novamente.",
        )


# --- Entrypoint ---

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
