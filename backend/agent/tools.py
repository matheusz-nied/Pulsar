"""
tools.py — Registro e definição das tools do agente.

Responsável por:
- Registrar todas as tools disponíveis para o LangGraph
- Definir schemas de entrada/saída de cada tool
- Mapear tools para suas implementações em /tools/
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

from loguru import logger


class ToolInfo(TypedDict):
    """Informações de uma tool registrada."""
    function: Callable[..., Any]
    description: str


# Registro centralizado de tools
TOOL_REGISTRY: dict[str, ToolInfo] = {}


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


def _register_builtin_tools() -> None:
    """Registra as tools internas do agente."""
    from backend.tools.news import buscar_noticias

    register_tool(
        name="buscar_noticias",
        description=(
            "Busca notícias recentes. Categorias: ia, tech, financas, economia, "
            "software, brasil, geral. Aceita query opcional para filtrar resultados."
        ),
    )(buscar_noticias)


_register_builtin_tools()


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
