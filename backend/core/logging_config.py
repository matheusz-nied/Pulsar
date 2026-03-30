"""Configuração centralizada de logging e decorators de observabilidade."""

from __future__ import annotations

import inspect
import json
import sys
import time
from contextvars import ContextVar, Token
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar, cast

from loguru import logger

from backend.memory.database import db

F = TypeVar("F", bound=Callable[..., Any])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_APP_LOG_FILE = _LOGS_DIR / "app.log"
_ERROR_LOG_FILE = _LOGS_DIR / "errors.log"

_SENSITIVE_KEYS = {
    "password",
    "senha",
    "token",
    "api_key",
    "authorization",
    "secret",
    "credentials",
    "cookie",
    "chave",
}

_REQUEST_METRICS: ContextVar[dict[str, float] | None] = ContextVar(
    "pulsar_request_metrics",
    default=None,
)


def setup_logging() -> None:
    """Configura handlers do loguru para console e arquivos."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger.remove()

    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level="INFO",
        colorize=True,
    )

    logger.add(
        str(_APP_LOG_FILE),
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        level="DEBUG",
        rotation="00:00",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
    )

    logger.add(
        str(_ERROR_LOG_FILE),
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        level="ERROR",
        retention="30 days",
        encoding="utf-8",
    )


def _sanitize_data(value: Any) -> Any:
    """Remove dados sensíveis de estruturas aninhadas para logging seguro."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in _SENSITIVE_KEYS):
                sanitized[key] = "***"
            else:
                sanitized[key] = _sanitize_data(item)
        return sanitized

    if isinstance(value, list):
        return [_sanitize_data(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_data(item) for item in value)

    if isinstance(value, str) and len(value) > 500:
        return f"{value[:500]}..."

    return value


def _safe_json(data: Any) -> str:
    """Serializa payload para JSON de forma resiliente."""
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        return str(data)


def start_request_metrics() -> Token[dict[str, float] | None]:
    """Inicia a coleta de métricas no contexto assíncrono atual."""
    return _REQUEST_METRICS.set({})


def finish_request_metrics(token: Token[dict[str, float] | None]) -> None:
    """Encerra a coleta de métricas do contexto atual."""
    _REQUEST_METRICS.reset(token)


def add_request_metric(name: str, value: float) -> None:
    """Acumula uma métrica numérica no contexto atual."""
    metrics = _REQUEST_METRICS.get()
    if metrics is None:
        return
    metrics[name] = metrics.get(name, 0.0) + value


def set_request_metric(name: str, value: float) -> None:
    """Define o valor absoluto de uma métrica no contexto atual."""
    metrics = _REQUEST_METRICS.get()
    if metrics is None:
        return
    metrics[name] = value


def get_request_metrics() -> dict[str, float]:
    """Retorna um snapshot das métricas acumuladas no contexto atual."""
    metrics = _REQUEST_METRICS.get()
    if metrics is None:
        return {}
    return dict(metrics)


def log_tool_call(func: F) -> F:
    """Decorator para logar chamada de tools e registrar ação no SQLite."""

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        sanitized_args = _sanitize_data(args)
        sanitized_kwargs = _sanitize_data(kwargs)
        tool_name = func.__name__

        logger.info(
            "Tool call iniciada: {} | args={} | kwargs={}",
            tool_name,
            _safe_json(sanitized_args),
            _safe_json(sanitized_kwargs),
        )

        try:
            result = await cast(Callable[..., Awaitable[Any]], func)(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            sanitized_result = _sanitize_data(result)

            logger.info(
                "Tool call finalizada: {} | resultado={} | tempo_ms={:.2f}",
                tool_name,
                _safe_json(sanitized_result),
                elapsed_ms,
            )
            add_request_metric("tools_ms", elapsed_ms)

            try:
                await db.registrar_acao(
                    tipo="tool",
                    descricao=(
                        f"{tool_name} args={_safe_json(sanitized_args)} "
                        f"kwargs={_safe_json(sanitized_kwargs)}"
                    ),
                    resultado=_safe_json(sanitized_result),
                )
            except Exception as db_exc:
                logger.warning("Falha ao registrar ação no SQLite: {}", db_exc)

            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.error(
                "Tool call com erro: {} | erro={} | tempo_ms={:.2f}",
                tool_name,
                str(exc),
                elapsed_ms,
            )
            raise

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        sanitized_args = _sanitize_data(args)
        sanitized_kwargs = _sanitize_data(kwargs)
        tool_name = func.__name__

        logger.info(
            "Tool call iniciada: {} | args={} | kwargs={}",
            tool_name,
            _safe_json(sanitized_args),
            _safe_json(sanitized_kwargs),
        )

        try:
            result = func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            add_request_metric("tools_ms", elapsed_ms)
            logger.info(
                "Tool call finalizada: {} | resultado={} | tempo_ms={:.2f}",
                tool_name,
                _safe_json(_sanitize_data(result)),
                elapsed_ms,
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.error(
                "Tool call com erro: {} | erro={} | tempo_ms={:.2f}",
                tool_name,
                str(exc),
                elapsed_ms,
            )
            raise

    if inspect.iscoroutinefunction(func):
        return cast(F, async_wrapper)

    return cast(F, sync_wrapper)


def log_api_call(func: F) -> F:
    """Decorator para logar chamadas externas e uso de tokens quando disponível."""

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        endpoint = _resolve_endpoint(func, args, kwargs)

        try:
            result = await cast(Callable[..., Awaitable[Any]], func)(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            tokens = _extract_tokens(result)

            logger.info(
                "API call concluída: endpoint={} | tokens={} | tempo_ms={:.2f}",
                endpoint,
                tokens,
                elapsed_ms,
            )
            add_request_metric("api_ms", elapsed_ms)
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.error(
                "API call com erro: endpoint={} | erro={} | tempo_ms={:.2f}",
                endpoint,
                str(exc),
                elapsed_ms,
            )
            raise

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        endpoint = _resolve_endpoint(func, args, kwargs)

        try:
            result = func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "API call concluída: endpoint={} | tokens={} | tempo_ms={:.2f}",
                endpoint,
                _extract_tokens(result),
                elapsed_ms,
            )
            add_request_metric("api_ms", elapsed_ms)
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.error(
                "API call com erro: endpoint={} | erro={} | tempo_ms={:.2f}",
                endpoint,
                str(exc),
                elapsed_ms,
            )
            raise

    if inspect.iscoroutinefunction(func):
        return cast(F, async_wrapper)

    return cast(F, sync_wrapper)


def _extract_tokens(result: Any) -> str:
    """Extrai informações de token de respostas de APIs quando disponível."""
    usage = getattr(result, "usage", None)
    if usage is not None:
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if input_tokens is not None or output_tokens is not None:
            return f"input={input_tokens}, output={output_tokens}"

    if isinstance(result, dict):
        usage_dict = result.get("usage")
        if isinstance(usage_dict, dict):
            in_tokens = usage_dict.get("input_tokens")
            out_tokens = usage_dict.get("output_tokens")
            if in_tokens is not None or out_tokens is not None:
                return f"input={in_tokens}, output={out_tokens}"

    return "n/a"


def _resolve_endpoint(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    """Resolve endpoint/url para logs de API de forma tolerante."""
    endpoint = kwargs.get("endpoint") or kwargs.get("url")
    if isinstance(endpoint, str) and endpoint:
        return endpoint

    if args:
        maybe_self = args[0]
        base_url = getattr(maybe_self, "base_url", None)
        if isinstance(base_url, str) and base_url:
            return base_url

    return func.__name__


def get_log_file_path(tipo: str) -> Path:
    """Retorna o caminho do arquivo de log com base no tipo informado."""
    tipo_normalizado = tipo.lower().strip()

    if tipo_normalizado in {"erros", "erro", "errors"}:
        return _ERROR_LOG_FILE

    return _APP_LOG_FILE


def read_last_lines(tipo: str, limite: int = 50) -> list[str]:
    """Lê as últimas N linhas do arquivo de log correspondente."""
    limite_clamped = max(1, min(limite, 500))
    log_file = get_log_file_path(tipo)

    if not log_file.exists():
        return []

    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
        return lines[-limite_clamped:]
    except Exception as exc:
        logger.error("Erro ao ler arquivo de log {}: {}", log_file, exc)
        return []


def get_logs_dir() -> Path:
    """Retorna o diretório padrão de logs do projeto."""
    return _LOGS_DIR
