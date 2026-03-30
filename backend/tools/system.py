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

import asyncio
import platform
import subprocess
from typing import Any

import psutil
from loguru import logger

from backend.core.logging_config import log_tool_call

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
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise subprocess.TimeoutExpired(command, 30) from exc

        stdout_text = stdout.decode("utf-8", errors="ignore")
        stderr_text = stderr.decode("utf-8", errors="ignore")

        if process.returncode != 0:
            logger.warning(
                f"Comando retornou código {process.returncode}: {stderr_text}"
            )
        return stdout_text or stderr_text
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout ao executar comando: {command}")
        return "Erro: Comando excedeu o tempo limite."
    except Exception as e:
        logger.error(f"Erro ao executar comando: {e}")
        raise


async def _run_exec_checked(*args: str) -> tuple[str, str]:
    """
    Executa um comando com create_subprocess_exec e valida retorno.

    Args:
        *args: Lista de argumentos do executável.

    Returns:
        Tupla com stdout e stderr decodificados.

    Raises:
        FileNotFoundError: Quando o executável não existe.
        subprocess.CalledProcessError: Quando o retorno é diferente de zero.
    """
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    stdout_text = stdout.decode("utf-8", errors="ignore")
    stderr_text = stderr.decode("utf-8", errors="ignore")

    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode,
            list(args),
            output=stdout_text,
            stderr=stderr_text,
        )

    return stdout_text, stderr_text


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


@log_tool_call
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


@log_tool_call
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
                    processos_encontrados.append(
                        {
                            "pid": proc.info["pid"],
                            "name": proc.info["name"],
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not processos_encontrados:
            return f"Nenhum processo encontrado com o nome '{nome}'."

        lista_processos = "\n".join(
            f"  - PID {p['pid']}: {p['name']}" for p in processos_encontrados
        )

        return (
            f"Encontrados {len(processos_encontrados)} processo(s) de '{nome}':\n"
            f"{lista_processos}\n\n"
            f"Use confirmar_fechar('{nome}') para fechar todos esses processos."
        )

    except Exception as e:
        logger.error(f"Erro ao buscar processos de '{nome}': {e}")
        return f"Erro ao buscar processos: {str(e)}"


@log_tool_call
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
                    logger.info(
                        f"Processo {proc.info['pid']} ({proc.info['name']}) terminado"
                    )
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


@log_tool_call
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
                await _run_exec_checked(
                    "pactl",
                    "set-sink-volume",
                    "@DEFAULT_SINK@",
                    f"{nivel}%",
                )
                logger.info(f"Volume ajustado para {nivel}% via pactl")
                return f"Volume ajustado para {nivel}%."
            except (FileNotFoundError, subprocess.CalledProcessError):
                try:
                    await _run_exec_checked(
                        "amixer",
                        "set",
                        "Master",
                        f"{nivel}%",
                    )
                    logger.info(f"Volume ajustado para {nivel}% via amixer")
                    return f"Volume ajustado para {nivel}%."
                except (FileNotFoundError, subprocess.CalledProcessError) as e:
                    logger.error(f"Erro ao ajustar volume no Linux: {e}")
                    return "Erro: Não foi possível ajustar o volume. Instale pactl ou amixer."

        elif sistema == "Windows":
            try:
                from ctypes import POINTER, cast

                from comtypes import CLSCTX_ALL  # type: ignore
                from pycaw.pycaw import (  # type: ignore
                    AudioUtilities,
                    IAudioEndpointVolume,
                )

                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(
                    IAudioEndpointVolume._iid_, CLSCTX_ALL, None
                )
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(nivel / 100.0, None)
                logger.info(f"Volume ajustado para {nivel}% via pycaw")
                return f"Volume ajustado para {nivel}%."
            except ImportError:
                logger.warning("pycaw não instalado, tentando nircmd")
                try:
                    await _run_exec_checked(
                        "nircmd.exe",
                        "setsysvolume",
                        str(int(nivel * 655.35)),
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
                await _run_exec_checked(
                    "osascript",
                    "-e",
                    f"set volume output volume {nivel}",
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


# ============================================================================
# AGENDAMENTO DE ALARMES
# ============================================================================

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Scheduler global (será iniciado no lifespan do FastAPI)
scheduler: AsyncIOScheduler | None = None


def iniciar_scheduler() -> None:
    """
    Inicializa o scheduler do APScheduler.
    Deve ser chamado no startup do FastAPI.
    """
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
        scheduler.start()
        logger.info("APScheduler iniciado com sucesso")
    else:
        logger.warning("APScheduler já está iniciado")


def parar_scheduler() -> None:
    """
    Para o scheduler graciosamente.
    Deve ser chamado no shutdown do FastAPI.
    """
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=True)
        logger.info("APScheduler encerrado")
        scheduler = None


async def _executar_alarme(mensagem: str, job_id: str) -> None:
    """
    Callback executado quando um alarme dispara.

    Args:
        mensagem: Mensagem do alarme.
        job_id: ID do job agendado.
    """
    try:
        logger.info(f"🔔 ALARME DISPARADO (ID={job_id}): {mensagem}")

        # TTS: sintetizar e tocar o áudio
        try:
            from backend.audio.tts import get_tts

            tts = get_tts()
            audio_path = await tts.sintetizar(mensagem)
            logger.info(f"Áudio do alarme gerado: {audio_path}")
        except Exception as e:
            logger.warning(f"Erro ao sintetizar áudio do alarme: {e}")

        # Telegram: enviar notificação se configurado
        try:
            from telegram_bot.bot import send_notification

            enviado = await send_notification(f"🔔 Alarme:\n{mensagem}")
            if enviado:
                logger.info("Notificação do alarme enviada via Telegram")
            else:
                logger.warning(
                    "Notificação do alarme não enviada: verifique TELEGRAM_OWNER_ID"
                )
        except Exception as e:
            logger.warning(f"Erro ao enviar notificação do alarme via Telegram: {e}")

    except Exception as e:
        logger.error(f"Erro ao executar alarme {job_id}: {e}")


@log_tool_call
async def definir_alarme(horario: str, mensagem: str) -> str:
    """
    Define um alarme para um horário específico.

    Args:
        horario: Horário no formato "HH:MM" ou "HH:MM DD/MM/YYYY".
        mensagem: Mensagem a ser exibida/tocada quando o alarme disparar.

    Returns:
        Mensagem de confirmação com o horário e ID do job.
    """
    global scheduler

    if scheduler is None:
        return "Erro: Scheduler não está inicializado. Reinicie o servidor."

    try:
        # Parsear horário
        horario_limpo = horario.strip()

        # Tentar formato "HH:MM DD/MM/YYYY"
        try:
            data_hora = datetime.strptime(horario_limpo, "%H:%M %d/%m/%Y")
        except ValueError:
            # Tentar formato "HH:MM" (hoje)
            try:
                hora_minuto = datetime.strptime(horario_limpo, "%H:%M")
                agora = datetime.now()
                data_hora = agora.replace(
                    hour=hora_minuto.hour,
                    minute=hora_minuto.minute,
                    second=0,
                    microsecond=0,
                )

                # Se o horário já passou hoje, agendar para amanhã
                if data_hora <= agora:
                    from datetime import timedelta

                    data_hora += timedelta(days=1)

            except ValueError:
                return (
                    f"Erro: Formato de horário inválido '{horario}'. "
                    f"Use 'HH:MM' ou 'HH:MM DD/MM/YYYY'."
                )

        # Verificar se o horário está no futuro
        if data_hora <= datetime.now():
            return "Erro: O horário do alarme deve estar no futuro."

        # Criar job único
        job = scheduler.add_job(
            _executar_alarme,
            trigger="date",
            run_date=data_hora,
            args=[mensagem, ""],  # job_id será preenchido depois
            id=None,  # Gerar ID automático
        )

        # Atualizar args com o job_id real
        scheduler.modify_job(job.id, args=[mensagem, job.id])

        data_hora_formatada = data_hora.strftime("%d/%m/%Y às %H:%M")
        logger.info(
            f"Alarme agendado: {mensagem} para {data_hora_formatada} (ID={job.id})"
        )

        return (
            f"✅ Alarme agendado para {data_hora_formatada}\n"
            f"Mensagem: {mensagem}\n"
            f"ID: {job.id}"
        )

    except Exception as e:
        logger.error(f"Erro ao definir alarme: {e}")
        return f"Erro ao definir alarme: {str(e)}"


@log_tool_call
async def listar_alarmes() -> str:
    """
    Lista todos os alarmes agendados ativos.

    Returns:
        String formatada com a lista de alarmes ou mensagem indicando que não há alarmes.
    """
    global scheduler

    if scheduler is None:
        return "Erro: Scheduler não está inicializado."

    try:
        jobs = scheduler.get_jobs()

        if not jobs:
            return "Nenhum alarme agendado no momento."

        linhas = ["📋 Alarmes agendados:\n"]
        for job in jobs:
            # Extrair informações do job
            job_id = job.id
            run_date = job.next_run_time

            if run_date:
                data_hora_formatada = run_date.strftime("%d/%m/%Y às %H:%M:%S")
            else:
                data_hora_formatada = "Data não disponível"

            # Tentar extrair mensagem dos args
            mensagem = "Sem mensagem"
            if job.args and len(job.args) > 0:
                mensagem = job.args[0]

            linhas.append(
                f"  • ID: {job_id}\n"
                f"    Horário: {data_hora_formatada}\n"
                f"    Mensagem: {mensagem}\n"
            )

        return "\n".join(linhas)

    except Exception as e:
        logger.error(f"Erro ao listar alarmes: {e}")
        return f"Erro ao listar alarmes: {str(e)}"


@log_tool_call
async def cancelar_alarme(job_id: str) -> str:
    """
    Cancela um alarme pelo seu ID.

    Args:
        job_id: ID do job a ser cancelado.

    Returns:
        Mensagem de confirmação ou erro se o alarme não for encontrado.
    """
    global scheduler

    if scheduler is None:
        return "Erro: Scheduler não está inicializado."

    try:
        # Tentar remover o job
        job = scheduler.get_job(job_id)

        if job is None:
            return f"Erro: Alarme com ID '{job_id}' não encontrado."

        scheduler.remove_job(job_id)
        logger.info(f"Alarme {job_id} cancelado")

        return f"✅ Alarme '{job_id}' cancelado com sucesso."

    except Exception as e:
        logger.error(f"Erro ao cancelar alarme {job_id}: {e}")
        return f"Erro ao cancelar alarme: {str(e)}"
