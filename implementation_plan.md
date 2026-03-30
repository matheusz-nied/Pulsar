# Plano de Otimização de Performance — Pulsar

Objetivo: reduzir a latência percebida de ~8-15s para ~2-4s unindo as melhores soluções das análises anteriores. As mudanças são **backward-compatible** — nenhuma interface pública muda.

---

## Proposed Changes

### Fase 1 — Quick Wins (alto impacto, baixo risco)

---

#### [MODIFY] [stt.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/audio/stt.py)

1. **Mudar `model_size` padrão de `"medium"` → `"small"`** — modelo menor, latência ~2x menor com qualidade suficiente para comandos em PT-BR.
2. **`beam_size=1`** (Greedy Search) — era 5; reduz tempo de transcrição em ~50% sem perda perceptível em PT-BR.
3. **`vad_filter=True`** — reativar; Whisper processa só os pedaços com voz, pulando silêncios e ruído de fundo.

```diff
- self.model = WhisperModel(model_size, device=..., compute_type=...)
+ self.model = WhisperModel(model_size, device=..., compute_type=...)
  # em transcrever_sync:
- beam_size=5,
- vad_filter=False,
+ beam_size=1,
+ vad_filter=True,
```

> [!IMPORTANT]
> O teste [test_stt.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/tests/test_stt.py) verifica `model_size == "medium"` — esse assert será atualizado para `"small"`.

---

#### [MODIFY] [music.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/tools/music.py)

1. **`subprocess.run` → `asyncio.create_subprocess_exec`** no [_abrir_brave()](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/tools/music.py#48-56) — não bloqueia o event loop.
2. **`yt.search()` → `asyncio.to_thread(yt.search, ...)`** — essa chamada HTTP síncrona bloqueava o event loop por 1-3s.

```diff
- subprocess.run(["brave-browser", url], check=False, capture_output=True)
+ await asyncio.create_subprocess_exec(
+     "brave-browser", url,
+     stdout=asyncio.subprocess.DEVNULL,
+     stderr=asyncio.subprocess.DEVNULL,
+ )

- results = yt.search(query, filter="songs")
+ results = await asyncio.to_thread(yt.search, query, filter="songs")
```

---

#### [MODIFY] [system.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/tools/system.py)

1. **`subprocess.run` → `asyncio.create_subprocess_exec`** nas chamadas de `pactl`, `amixer`, `osascript` na função [ajustar_volume()](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/tools/system.py#236-329) — eram síncronas.
2. [run_command()](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/tools/system.py#37-67) fica com `asyncio.create_subprocess_shell` para manter a API atual.

---

#### [MODIFY] [main.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/main.py)

**Eager loading do agente no startup** — adicionar dentro de [_warmup_runtime_components()](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/main.py#189-193):

```python
async def _warmup_runtime_components() -> None:
    warmup_vector_memory()
    _request_stt_warmup()
    # NOVO: pré-inicializar o agente em background
    asyncio.create_task(
        asyncio.to_thread(get_agent),
        name="pulsar-agent-warmup",
    )
```

Elimina o atraso de 5-10s do [LazyConversationAgent](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/agent/agent.py#1233-1291) na primeira mensagem.

---

#### [MODIFY] [agent.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/agent/agent.py) — Novo provider Groq

O Groq oferece latência de **~0.3-0.5s** contra ~2-3s de Claude/OpenAI, usando modelos Llama 3 e Gemma. O projeto já tem o Provider Pattern pronto — basta adicionar um `elif`.

**Instalar dependência:**
```bash
pip install langchain-groq
```

**Em [create_agent_from_config()](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/agent/agent.py#1107-1199) (agent.py ~linha 1175):**
```python
elif provider_name == "groq":
    from langchain_groq import ChatGroq
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY não configurada no .env")
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    llm = ChatGroq(
        model=model,
        api_key=SecretStr(api_key),
        max_tokens=1024,
    )
```

**Em `.env` (ativar Groq):**
```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile  # ou gemma2-9b-it para ainda mais velocidade
```

> [!NOTE]
> Criar conta gratuita em https://console.groq.com — free tier generoso, sem cartão de crédito. Modelos disponíveis: `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` (~1s), `gemma2-9b-it` (~0.5s).

> [!IMPORTANT]
> Groq **suporta tool calling** — funciona 100% com o LangGraph e as tools existentes do Pulsar. Nenhuma outra mudança necessária.

---

### Fase 2 — Maior Impacto UX

---

#### [MODIFY] [memory.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/agent/memory.py)

**Paralelizar os dois embeds do VectorMemory:**

```diff
- contexto_conversas, contexto_fatos = await asyncio.gather(
-     vector_memory.buscar_contexto(mensagem, n_resultados=3),
-     vector_memory.buscar_fatos(mensagem),
- )
```

Já usa `asyncio.gather` — porém internamente cada método faz 2 `to_thread` sequenciais. Refatorar para compartilhar um único embedding calculado uma vez só:

```python
# Calcular embedding 1x e reusar em ambas as buscas
embedding = await asyncio.to_thread(self._embed, query)
conversas_task = asyncio.to_thread(self._conversas.query, ...)
fatos_task    = asyncio.to_thread(self._fatos.query, ...)
res_conv, res_fat = await asyncio.gather(conversas_task, fatos_task)
```

---

#### [MODIFY] [tts.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/audio/tts.py) + [main.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/main.py)

**TTS streaming por frase** — maior impacto de UX.

Em [tts.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/tests/test_tts.py), adicionar método `sintetizar_frase(texto: str) -> str` (idêntico ao atual [sintetizar](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/audio/tts.py#70-139), mas sem limpeza pesada — otimizado para frases curtas).

No WebSocket `/ws/audio` de [main.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/main.py), substituir o fluxo atual:

```python
# ANTES: espera resposta LLM completa → gera TTS → envia URL
audio_path = await tts.sintetizar(resposta_completa)
await ws.send_json({"type": "audio_ready", "url": f"/audio/{audio_filename}"})

# DEPOIS: pipeline streaming frase a frase
frase_buffer = ""
audio_queue: list[str] = []

async for chunk in agent.processar_stream(transcricao, historico):
    resposta_completa += chunk
    frase_buffer += chunk
    await ws.send_json({"type": "resposta_chunk", "texto": chunk})

    # Sintetizar ao detectar fim de frase
    if any(c in chunk for c in ".!?,") and len(frase_buffer.strip()) > 10:
        audio_path = await tts.sintetizar(frase_buffer.strip())
        audio_fname = Path(audio_path).name
        audio_queue.append(audio_fname)
        await ws.send_json({"type": "audio_chunk", "url": f"/audio/{audio_fname}"})
        frase_buffer = ""

# Flush do buffer restante
if frase_buffer.strip():
    audio_path = await tts.sintetizar(frase_buffer.strip())
    audio_fname = Path(audio_path).name
    await ws.send_json({"type": "audio_chunk", "url": f"/audio/{audio_fname}"})

await ws.send_json({"type": "audio_ready", "url": f"/audio/{audio_queue[0] if audio_queue else ''}"})
```

**No frontend [app.js](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/frontend/src/app.js)**: tratar o novo evento `audio_chunk` — enfileirar áudios e reproduzir sequencialmente:

```js
case "audio_chunk":
    this._enqueueAudio(data.url);
    break;
```

---

## Verification Plan

### Automated Tests

**Executar suite existente:**
```bash
cd /home/kaizen/Documents/Dev/Projetos/Pulsar
export PATH="/home/kaizen/Documents/Dev/Projetos/Pulsar/.conda_env/bin:$PATH"
pytest tests/ -v
```

**Testes que cobrem as mudanças:**
- [tests/test_stt.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/tests/test_stt.py) — cobre STT (`model_size` assert será atualizado de `"medium"` → `"small"`)
- [tests/test_tts.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/tests/test_tts.py) — cobre geração de áudio (valida que [sintetizar()](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/backend/audio/tts.py#70-139) ainda funciona)
- [tests/test_fase1.py](file:///home/kaizen/Documents/Dev/Projetos/Pulsar/tests/test_fase1.py) — testa pipeline geral

**Nenhum novo arquivo de teste precisa ser criado** — as mudanças são internas e os testes existentes cobrem as interfaces públicas.

### Manual Verification

1. **Iniciar o backend:**
   ```bash
   cd /home/kaizen/Documents/Dev/Projetos/Pulsar
   uvicorn backend.main:app --reload --port 8000
   ```

2. **Medir latência antes e depois** via logs — o backend já loga métricas por request:
   ```
   Request metrics: route=/conversar/stream | metrics={...llm_ms..., total_ms...}
   ```
   Comparar `total_ms` e `llm_ms` antes e depois.

3. **Testar comando de música:**
   - Dizer "tocar Bohemian Rhapsody" — verificar que o browser abre sem travar o servidor.

4. **Testar primeira mensagem após restart:**
   - Reiniciar o backend e enviar mensagem imediatamente — deve responder em tempo normal (não em 8-10s como antes).

5. **Testar STT** (se usar endpoint `/voice` ou WebSocket de voz):
   - Gravar um comando curto (~3s de áudio)
   - Verificar nos logs `stt_ms` — deve ser < 800ms com o modelo `small` e `beam_size=1`.
