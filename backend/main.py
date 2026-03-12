"""
main.py — FastAPI app principal do Assistente Virtual Local.

Responsável por:
- Definir os endpoints REST da API
- Inicializar o agente e suas dependências
- Gerenciar o ciclo de vida da aplicação
- Servir como ponto de entrada do backend
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from backend.agent.agent import process_message
from backend.agent.memory import MemoryManager


# --- Models ---

class ChatRequest(BaseModel):
    """Modelo de requisição para o endpoint de chat."""
    message: str


class ChatResponse(BaseModel):
    """Modelo de resposta do endpoint de chat."""
    response: str


# --- Lifecycle ---

memory_manager = MemoryManager()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gerencia o ciclo de vida da aplicação FastAPI."""
    logger.info("🚀 Assistente Virtual Local iniciando...")
    logger.info(f"Ambiente: {'produção' if os.getenv('ENV') == 'production' else 'desenvolvimento'}")
    yield
    logger.info("👋 Assistente Virtual Local encerrando...")


# --- App ---

app = FastAPI(
    title="Assistente Virtual Local",
    description="API do assistente virtual pessoal com IA",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restringir para domínios específicos em produção
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Endpoints ---

@app.get("/health")
async def health_check() -> dict[str, str]:
    """Endpoint de health check."""
    return {"status": "ok", "service": "assistente-virtual-local"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Endpoint principal de chat.

    Recebe uma mensagem do usuário e retorna a resposta do agente.
    """
    try:
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="Mensagem não pode ser vazia.")

        await memory_manager.add_message("user", request.message)
        response = await process_message(request.message)
        await memory_manager.add_message("assistant", response)

        return ChatResponse(response=response)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro no endpoint /chat: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor.")
