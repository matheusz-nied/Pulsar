"""
wake_word.py — Detecção de wake word "Pulsar" via Porcupine + pipeline de voz completo.

Fluxo:
  1. Porcupine escuta o microfone continuamente em background thread
  2. Detecta "Pulsar" → notifica todos os clientes WebSocket (type: wake_word)
  3. Grava áudio do usuário até silêncio prolongado
  4. STT (Whisper) → transcrição → notifica (type: transcricao)
  5. Agente processa → notifica chunks (type: resposta_chunk)
  6. TTS (edge-tts) sintetiza → notifica URL (type: audio_ready)
  7. Volta a escutar
"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import numpy as np
import sounddevice as sd
import soundfile as sf
from loguru import logger

from backend.core.logging_config import (
    finish_request_metrics,
    get_request_metrics,
    set_request_metric,
    start_request_metrics,
)

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

# ── Configurações ──────────────────────────────────────────────────────────────

SAMPLE_RATE = 16000  # Hz — exigido pelo Porcupine e pelo Whisper
FRAME_LENGTH = 512  # amostras por frame do Porcupine
RECORD_SAMPLE_RATE = 16000  # Hz para gravação pós-wake-word
CHANNELS = 1

# Detecção de silêncio após wake word
SILENCE_THRESHOLD = 0.010  # RMS abaixo disso = silêncio (mais permissivo)
SILENCE_DURATION = 1.0  # segundos contínuos de silêncio para encerrar (aumentado)
MIN_SPEECH_DURATION = 0.8  # espera mínima antes de checar silêncio (aumentado)
MAX_RECORD_DURATION = 20.0  # segundos máximos de gravação

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PPN_PATH = _PROJECT_ROOT / "Pulsar_pt_linux_v4_0_0" / "Pulsar_pt_linux_v4_0_0.ppn"
MODEL_PATH = _PROJECT_ROOT / "Pulsar_pt_linux_v4_0_0" / "porcupine_params_pt.pv"

# ── Gerenciador de conexões WebSocket ──────────────────────────────────────────

# Conjunto global de callbacks para notificar clientes conectados.
# Cada cliente WebSocket registra uma função async aqui ao conectar.
_voice_listeners: set[Callable] = set()


def register_voice_listener(callback: Callable) -> None:
    _voice_listeners.add(callback)


def unregister_voice_listener(callback: Callable) -> None:
    _voice_listeners.discard(callback)


async def _broadcast(event: dict, loop: AbstractEventLoop) -> None:
    """Envia evento para todos os clientes WebSocket registrados."""
    if not _voice_listeners:
        return
    dead: set[Callable] = set()
    for cb in list(_voice_listeners):
        try:
            await cb(event)
        except Exception:
            dead.add(cb)
    for cb in dead:
        _voice_listeners.discard(cb)


def broadcast_sync(event: dict, loop: AbstractEventLoop) -> None:
    """Agenda broadcast no event loop asyncio a partir de thread síncrona."""
    if loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast(event, loop), loop)


# ── Gravação pós-wake-word ─────────────────────────────────────────────────────


def _record_until_silence() -> np.ndarray | None:
    """
    Grava áudio do microfone até detectar silêncio prolongado ou tempo máximo.

    Fluxo:
      - Fase 1 (MIN_SPEECH_DURATION): grava sem checar silêncio — dá tempo para
        o usuário começar a falar após o wake word.
      - Fase 2: checa silêncio contínuo >= SILENCE_DURATION para encerrar.

    Returns:
        Array numpy com samples PCM float32, ou None se nada capturado.
    """
    chunks: list[np.ndarray] = []
    silence_start: float | None = None
    started = time.time()

    block_size = 1024  # ~64 ms por bloco a 16kHz

    def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:
        nonlocal silence_start
        chunks.append(indata.copy())
        elapsed = time.time() - started
        # Só começa a checar silêncio após fase 1
        if elapsed < MIN_SPEECH_DURATION:
            silence_start = None
            return
        rms = float(np.sqrt(np.mean(indata**2)))
        if rms < SILENCE_THRESHOLD:
            if silence_start is None:
                silence_start = time.time()
        else:
            silence_start = None  # Reset: detectou fala

    stop_event = threading.Event()

    def _monitor() -> None:
        while not stop_event.is_set():
            elapsed = time.time() - started
            if elapsed > MAX_RECORD_DURATION:
                logger.debug("Gravação atingiu tempo máximo")
                stop_event.set()
                break
            # Só encerra por silêncio após fase 1
            if elapsed >= MIN_SPEECH_DURATION:
                if (
                    silence_start is not None
                    and (time.time() - silence_start) >= SILENCE_DURATION
                ):
                    stop_event.set()
                    break
            time.sleep(0.05)

    logger.info(
        f"Gravando... (espera mínima {MIN_SPEECH_DURATION}s, "
        f"silêncio de {SILENCE_DURATION}s encerra, máx {MAX_RECORD_DURATION}s)"
    )

    monitor_thread = threading.Thread(target=_monitor, daemon=True)
    monitor_thread.start()

    with sd.InputStream(
        samplerate=RECORD_SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=block_size,
        callback=_callback,
    ):
        stop_event.wait(timeout=MAX_RECORD_DURATION + 2)

    if not chunks:
        return None

    audio = np.concatenate(chunks, axis=0).flatten()
    duration = len(audio) / RECORD_SAMPLE_RATE
    rms_medio = float(np.sqrt(np.mean(audio**2)))
    logger.info(f"Gravação concluída: {duration:.2f}s (RMS médio: {rms_medio:.4f})")

    return audio


def _save_wav(audio: np.ndarray) -> Path:
    """Salva array numpy como WAV temporário e retorna o path."""
    path = Path("/tmp") / f"pulsar_voice_{uuid.uuid4().hex}.wav"
    sf.write(str(path), audio, RECORD_SAMPLE_RATE, subtype="PCM_16")
    return path


def _extrair_frases_tts(
    buffer: str,
    min_chars: int = 18,
) -> tuple[list[str], str]:
    """
    Extrai frases já prontas para TTS incremental.

    Args:
        buffer: Texto acumulado.
        min_chars: Tamanho mínimo para frases curtas.

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


# ── Pipeline completa pós-wake-word ───────────────────────────────────────────


async def _run_voice_pipeline(session_id: str, loop: AbstractEventLoop) -> None:
    """
    Pipeline assíncrona: grava → STT → Agente → TTS → broadcast.
    Executada no event loop principal após wake word detectado.

    Mantém histórico próprio da sessão de voz separado do chat de texto.
    """
    from backend.agent.agent import agent, get_loaded_agent
    from backend.agent.memory import schedule_conversation_persistence, session_memory
    from backend.audio.stt import get_stt
    from backend.audio.tts import get_tts

    token = start_request_metrics()
    started_at = time.perf_counter()
    modelo_usado = "erro"
    wav_path: Path | None = None

    try:
        # 1. Gravar em thread para não bloquear o event loop
        logger.info("Iniciando gravação de voz...")
        audio = await asyncio.get_event_loop().run_in_executor(
            None, _record_until_silence
        )

        if audio is None:
            logger.warning("Nenhum áudio capturado após wake word")
            await _broadcast({"type": "voice_idle"}, loop)
            return

        # 2. Salvar WAV temporário
        wav_path = await asyncio.get_event_loop().run_in_executor(
            None, _save_wav, audio
        )

        # 3. STT
        logger.info(f"Transcrevendo: {wav_path}")
        stt = get_stt(model_size="small")
        transcricao = await stt.transcrever(str(wav_path))

        if not transcricao.strip():
            logger.warning("STT retornou vazio")
            await _broadcast({"type": "voice_idle"}, loop)
            return

        transcricao = transcricao.strip()
        logger.info(f"Transcrição: {transcricao}")
        await _broadcast({"type": "transcricao", "texto": transcricao}, loop)

        # 4. Agente + TTS incremental.
        resposta_completa = ""
        frase_buffer = ""
        audio_chunk_urls: list[str] = []
        tts = get_tts()
        phrase_queue: asyncio.Queue[str | None] = asyncio.Queue()

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
                    set_request_metric("tts_chunks", float(len(audio_chunk_urls)))
                    await _broadcast({"type": "audio_chunk", "url": audio_url}, loop)
                except Exception as exc:
                    logger.warning(
                        "Wake word falhou ao sintetizar frase para TTS incremental: {}",
                        exc,
                    )
                finally:
                    phrase_queue.task_done()

        tts_task = asyncio.create_task(
            tts_worker(),
            name=f"pulsar-voice-tts-{session_id}",
        )

        try:
            fast_path_response = await agent.try_fast_path(transcricao)  # type: ignore[attr-defined]
            if fast_path_response is not None:
                modelo_usado = fast_path_response.modelo_usado
                resposta_completa = fast_path_response.resposta.strip()
                if resposta_completa:
                    await _broadcast(
                        {"type": "resposta_chunk", "texto": resposta_completa},
                        loop,
                    )
                    frase_buffer += resposta_completa
                    frases_prontas, frase_buffer = _extrair_frases_tts(frase_buffer)
                    for frase in frases_prontas:
                        await phrase_queue.put(frase)
            else:
                async for chunk in agent.processar_stream(
                    transcricao,
                    [],
                    session_id=session_id,
                ):
                    resposta_completa += chunk
                    frase_buffer += chunk
                    await _broadcast({"type": "resposta_chunk", "texto": chunk}, loop)
                    frases_prontas, frase_buffer = _extrair_frases_tts(frase_buffer)
                    for frase in frases_prontas:
                        await phrase_queue.put(frase)

                loaded_agent = get_loaded_agent()
                modelo_usado = (
                    loaded_agent.llm.__class__.__name__
                    if loaded_agent is not None
                    else "lazy"
                )

            logger.info(
                "Resposta do agente ({}): {}",
                modelo_usado,
                repr(resposta_completa[:80]),
            )

            # 5. Salvar histórico de voz (separado do chat de texto)
            session_memory.add_message(session_id, "user", transcricao)
            session_memory.add_message(session_id, "assistant", resposta_completa)
            schedule_conversation_persistence(
                session_id,
                session_memory.get_history(session_id),
                transcricao,
                resposta_completa,
            )

            if not resposta_completa:
                logger.warning("Agente retornou resposta vazia, pulando TTS")
                await _broadcast({"type": "voice_idle"}, loop)
                return

            if frase_buffer.strip():
                await phrase_queue.put(frase_buffer.strip())
            await phrase_queue.put(None)
            await phrase_queue.join()
            await tts_task
        finally:
            if not tts_task.done():
                with suppress(asyncio.QueueFull):
                    await phrase_queue.put(None)
                tts_task.cancel()
                with suppress(asyncio.CancelledError):
                    await tts_task
        await _broadcast(
            {
                "type": "audio_ready",
                "url": audio_chunk_urls[0] if audio_chunk_urls else "",
            },
            loop,
        )

        logger.success(
            "Pipeline de voz concluída: audio_chunks={}",
            len(audio_chunk_urls),
        )

    except Exception as e:
        logger.error(f"Erro na pipeline de voz: {e}")
        logger.exception(e)
        await _broadcast({"type": "erro", "mensagem": str(e)}, loop)
    finally:
        set_request_metric("total_ms", (time.perf_counter() - started_at) * 1000)
        logger.info(
            "Voice pipeline metrics: session_id={} | metrics={} | modelo_usado={}",
            session_id,
            {
                name: round(value, 2)
                for name, value in sorted(get_request_metrics().items())
            },
            modelo_usado,
        )
        finish_request_metrics(token)
        try:
            if wav_path is not None:
                wav_path.unlink(missing_ok=True)
        except Exception:
            pass


# ── Wake Word Listener (thread principal) ─────────────────────────────────────


class WakeWordListener:
    """
    Escuta o microfone continuamente via Porcupine em background thread.
    Ao detectar "Pulsar", dispara o pipeline de voz no event loop asyncio.
    """

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: AbstractEventLoop | None = None
        # session_id persistente para toda a sessão de voz
        self._session_id = str(uuid.uuid4())

    def start(self, loop: AbstractEventLoop) -> None:
        """Inicia a thread de escuta em background."""
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._listen, daemon=True, name="porcupine-listener"
        )
        self._thread.start()
        logger.info("WakeWordListener iniciado (aguardando 'Pulsar'...)")

    def stop(self) -> None:
        """Sinaliza parada e aguarda a thread terminar."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("WakeWordListener encerrado")

    def _listen(self) -> None:
        """Loop principal da thread: Porcupine lê frames do microfone."""
        import pvporcupine

        access_key = os.getenv("PORCUPINE_ACCESS_KEY", "")
        if not access_key:
            logger.error("PORCUPINE_ACCESS_KEY não definida; wake word desativado")
            return

        if not PPN_PATH.exists():
            logger.error(f"Arquivo .ppn não encontrado: {PPN_PATH}")
            return

        if not MODEL_PATH.exists():
            logger.error(f"Arquivo model .pv não encontrado: {MODEL_PATH}")
            return

        try:
            porcupine = pvporcupine.create(
                access_key=access_key,
                keyword_paths=[str(PPN_PATH)],
                model_path=str(MODEL_PATH),
                sensitivities=[0.6],
            )
        except Exception as e:
            logger.error(f"Erro ao inicializar Porcupine: {e}")
            return

        audio_queue: queue.Queue[np.ndarray] = queue.Queue()

        def _sd_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            audio_queue.put(indata.copy())

        logger.info(
            f"Porcupine escutando (sample_rate={porcupine.sample_rate}, "
            f"frame_length={porcupine.frame_length})"
        )

        try:
            with sd.InputStream(
                samplerate=porcupine.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=porcupine.frame_length,
                callback=_sd_callback,
            ):
                while not self._stop_event.is_set():
                    try:
                        frame = audio_queue.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    pcm = frame.flatten().astype(np.int16)
                    result = porcupine.process(pcm)  # type: ignore

                    if result >= 0:
                        logger.success("Wake word 'Pulsar' detectada!")
                        # Notifica frontend
                        broadcast_sync({"type": "wake_word"}, self._loop)  # type: ignore
                        # Roda pipeline de voz no event loop asyncio
                        asyncio.run_coroutine_threadsafe(
                            _run_voice_pipeline(self._session_id, self._loop),  # type: ignore
                            self._loop,  # type: ignore
                        )
                        # Limpa fila para descartar áudio acumulado durante o pipeline
                        with audio_queue.mutex:
                            audio_queue.queue.clear()

        except Exception as e:
            logger.error(f"Erro no listener Porcupine: {e}")
        finally:
            porcupine.delete()
            logger.info("Porcupine finalizado")


# ── Instância global ───────────────────────────────────────────────────────────

_listener: WakeWordListener | None = None


def get_wake_word_listener() -> WakeWordListener:
    global _listener
    if _listener is None:
        _listener = WakeWordListener()
    return _listener
