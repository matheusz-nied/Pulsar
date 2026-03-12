"""
system.py — Tools de controle do sistema operacional.

Responsável por:
- Executar comandos no terminal
- Abrir/fechar aplicativos
- Gerenciar arquivos e diretórios
- Monitorar recursos do sistema (CPU, RAM, disco)
- Controle de volume
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

import psutil
from loguru import logger


# ============================================================================
# WHITELIST DE APLICATIVOS
# ============================================================================

APP_WHITELIST: dict[str, list[str]] = {
    "chrome": ["google-chrome", "chromium-browser", "chrome.exe"],
    "firefox": ["firefox", "firefox.exe"],
    "vscode": ["code", "code.exe"],
    "terminal": ["gnome-terminal", "xterm", "cmd.exe", "konsole", "alacritty"],
    "calculadora": ["gnome-calculator", "kcalc", "calc.exe"],
}


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
        return {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        }
    except Exception as e:
        logger.error(f"Erro ao obter info do sistema: {e}")
        raise


# ============================================================================
# GERENCIAMENTO DE APLICATIVOS
# ============================================================================

async def abrir_app(nome: str) -> str:
    """
    Abre um aplicativo da whitelist.

    Args:
        nome: Nome amigável do aplicativo (ex: "firefox", "chrome").

    Returns:
        Mensagem de sucesso ou erro.
    """
    try:
        nome_normalizado = nome.lower().strip()

        if nome_normalizado not in APP_WHITELIST:
            apps_disponiveis = ", ".join(APP_WHITELIST.keys())
            return (
                f"Erro: Aplicativo '{nome}' não está na whitelist. "
                f"Aplicativos permitidos: {apps_disponiveis}"
            )

        executaveis = APP_WHITELIST[nome_normalizado]
        sistema = platform.system()

        for executavel in executaveis:
            try:
                if sistema == "Windows":
                    subprocess.Popen(
                        executavel,
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.Popen(
                        [executavel],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )

                logger.info(f"Aplicativo '{nome}' aberto com sucesso: {executavel}")
                return f"Aplicativo '{nome}' aberto com sucesso."

            except (FileNotFoundError, OSError):
                continue

        return f"Erro: Não foi possível abrir '{nome}'. Nenhum executável encontrado no sistema."

    except Exception as e:
        logger.error(f"Erro ao abrir aplicativo '{nome}': {e}")
        return f"Erro ao abrir aplicativo: {str(e)}"


async def fechar_app(nome: str) -> str:
    """
    Encontra processos pelo nome e solicita confirmação para fechar.

    Args:
        nome: Nome do aplicativo a ser fechado.

    Returns:
        Mensagem solicitando confirmação ou informando que não há processos.
    """
    try:
        nome_normalizado = nome.lower().strip()
        processos_encontrados: list[dict[str, Any]] = []

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_name = proc.info["name"].lower()
                if nome_normalizado in proc_name:
                    processos_encontrados.append({
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not processos_encontrados:
            return f"Nenhum processo encontrado com o nome '{nome}'."

        lista_processos = "\n".join(
            f"  - PID {p['pid']}: {p['name']}"
            for p in processos_encontrados
        )

        return (
            f"Encontrados {len(processos_encontrados)} processo(s) de '{nome}':\n"
            f"{lista_processos}\n\n"
            f"Use confirmar_fechar('{nome}') para fechar todos esses processos."
        )

    except Exception as e:
        logger.error(f"Erro ao buscar processos de '{nome}': {e}")
        return f"Erro ao buscar processos: {str(e)}"


async def confirmar_fechar(nome: str) -> str:
    """
    Fecha todos os processos encontrados pelo nome (após confirmação via fechar_app).

    Args:
        nome: Nome do aplicativo cujos processos serão fechados.

    Returns:
        Mensagem de sucesso ou erro.
    """
    try:
        nome_normalizado = nome.lower().strip()
        processos_fechados = 0

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_name = proc.info["name"].lower()
                if nome_normalizado in proc_name:
                    proc.terminate()
                    processos_fechados += 1
                    logger.info(f"Processo {proc.info['pid']} ({proc.info['name']}) terminado")
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.warning(f"Não foi possível fechar processo: {e}")
                continue

        if processos_fechados == 0:
            return f"Nenhum processo de '{nome}' foi encontrado para fechar."

        return f"{processos_fechados} processo(s) de '{nome}' fechado(s) com sucesso."

    except Exception as e:
        logger.error(f"Erro ao fechar processos de '{nome}': {e}")
        return f"Erro ao fechar processos: {str(e)}"


# ============================================================================
# CONTROLE DE VOLUME
# ============================================================================

async def ajustar_volume(nivel: int) -> str:
    """
    Ajusta o volume do sistema.

    Args:
        nivel: Nível de volume entre 0 e 100.

    Returns:
        Mensagem com o novo nível de volume ou erro.
    """
    try:
        if not 0 <= nivel <= 100:
            return "Erro: Nível de volume deve estar entre 0 e 100."

        sistema = platform.system()

        if sistema == "Linux":
            try:
                subprocess.run(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{nivel}%"],
                    check=True,
                    capture_output=True,
                )
                logger.info(f"Volume ajustado para {nivel}% via pactl")
                return f"Volume ajustado para {nivel}%."
            except (FileNotFoundError, subprocess.CalledProcessError):
                try:
                    subprocess.run(
                        ["amixer", "set", "Master", f"{nivel}%"],
                        check=True,
                        capture_output=True,
                    )
                    logger.info(f"Volume ajustado para {nivel}% via amixer")
                    return f"Volume ajustado para {nivel}%."
                except (FileNotFoundError, subprocess.CalledProcessError) as e:
                    logger.error(f"Erro ao ajustar volume no Linux: {e}")
                    return "Erro: Não foi possível ajustar o volume. Instale pactl ou amixer."

        elif sistema == "Windows":
            try:
                from ctypes import POINTER, cast
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(nivel / 100.0, None)
                logger.info(f"Volume ajustado para {nivel}% via pycaw")
                return f"Volume ajustado para {nivel}%."
            except ImportError:
                logger.warning("pycaw não instalado, tentando nircmd")
                try:
                    subprocess.run(
                        ["nircmd.exe", "setsysvolume", str(int(nivel * 655.35))],
                        check=True,
                        capture_output=True,
                    )
                    logger.info(f"Volume ajustado para {nivel}% via nircmd")
                    return f"Volume ajustado para {nivel}%."
                except (FileNotFoundError, subprocess.CalledProcessError) as e:
                    logger.error(f"Erro ao ajustar volume no Windows: {e}")
                    return "Erro: Não foi possível ajustar o volume. Instale pycaw ou nircmd."
            except Exception as e:
                logger.error(f"Erro ao ajustar volume via pycaw: {e}")
                return f"Erro ao ajustar volume: {str(e)}"

        elif sistema == "Darwin":
            try:
                subprocess.run(
                    ["osascript", "-e", f"set volume output volume {nivel}"],
                    check=True,
                    capture_output=True,
                )
                logger.info(f"Volume ajustado para {nivel}% via osascript")
                return f"Volume ajustado para {nivel}%."
            except (FileNotFoundError, subprocess.CalledProcessError) as e:
                logger.error(f"Erro ao ajustar volume no macOS: {e}")
                return f"Erro ao ajustar volume no macOS: {str(e)}"

        else:
            return f"Erro: Sistema operacional '{sistema}' não suportado para ajuste de volume."

    except Exception as e:
        logger.error(f"Erro ao ajustar volume: {e}")
        return f"Erro ao ajustar volume: {str(e)}"
