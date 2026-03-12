"""
tools.py — Registro e definição das tools do agente.

Responsável por:
- Registrar todas as tools disponíveis para o LangGraph
- Definir schemas de entrada/saída de cada tool
- Mapear tools para suas implementações em /tools/
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

# Registro centralizado de tools
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_tool(name: str, description: str) -> Callable:
    """
    Decorador para registrar uma tool no registry do agente.

    Args:
        name: Nome da tool.
        description: Descrição do que a tool faz.

    Returns:
        Decorador que registra a função.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        TOOL_REGISTRY[name] = {
            "function": func,
            "description": description,
        }
        logger.info(f"Tool registrada: {name}")
        return func
    return decorator


def get_available_tools() -> list[dict[str, str]]:
    """
    Retorna a lista de tools disponíveis.

    Returns:
        Lista de dicionários com nome e descrição de cada tool.
    """
    return [
        {"name": name, "description": info["description"]}
        for name, info in TOOL_REGISTRY.items()
    ]
