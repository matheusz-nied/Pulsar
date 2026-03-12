"""
system.py — Tools de controle do sistema operacional.

Responsável por:
- Executar comandos no terminal
- Abrir/fechar aplicativos
- Gerenciar arquivos e diretórios
- Monitorar recursos do sistema (CPU, RAM, disco)
"""

from __future__ import annotations

import subprocess

from loguru import logger


async def run_command(command: str) -> str:
    """
    Executa um comando no terminal e retorna a saída.

    Args:
        command: Comando a ser executado.

    Returns:
        Saída do comando (stdout).
    """
    try:
        logger.info(f"Executando comando: {command}")
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"Comando retornou código {result.returncode}: {result.stderr}")
        return result.stdout or result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout ao executar comando: {command}")
        return "Erro: Comando excedeu o tempo limite."
    except Exception as e:
        logger.error(f"Erro ao executar comando: {e}")
        raise


async def get_system_info() -> dict[str, str]:
    """
    Retorna informações básicas do sistema.

    Returns:
        Dicionário com informações do sistema.
    """
    try:
        import platform
        return {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        }
    except Exception as e:
        logger.error(f"Erro ao obter info do sistema: {e}")
        raise
