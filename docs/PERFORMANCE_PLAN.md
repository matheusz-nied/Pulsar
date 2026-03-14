# Plano de Otimizacao de Performance — Pulsar

## Resumo executivo

Analisei os arquivos de runtime do projeto (`backend`, `frontend/src`, `telegram_bot`) com foco no caminho critico de voz:

`wake word -> gravacao -> STT -> LLM/tools -> TTS -> audio_ready -> play`

Latencia estimada atual (com base no codigo e nos logs recentes):
- **Wake detectado -> inicio gravacao:** ~40-120 ms
- **Fim da fala -> STT pronto:** ~0.6-1.6 s (hoje quase sempre em CPU fallback)
- **LLM + tools:** ~1.5-6 s (pior quando ha tools externas, ex.: musica)
- **TTS:** ~0.05-0.2 s em cache / ~0.7-2 s sem cache
- **Fim da fala -> primeiro audio:** **~3.5-8 s** (podendo passar de 10 s em `controlar_musica`)

Meta recomendada (hardware atual i5 + GTX 970 4GB):
- **Fim da fala -> primeiro audio (sem tool externa):** **<= 2.5-3.0 s (P50)**
- **Fim da fala -> primeiro audio (com tool externa):** **<= 4.5-5.5 s (P50)**
- **Cold start (primeira interacao):** eliminar picos > 5 s com pre-warm no startup.

---

## Problemas encontrados por severidade

### 🔴 Critico (impacto alto, corrigir primeiro)

#### 1) STT com estrategia de `compute_type` que frequentemente cai para CPU
- **Arquivo:** `backend/audio/stt.py` (linhas 57-74, 82-86)
- **Problema:** a selecao inicial usa `cuda + int8`, que pode ser invalida para parte das placas/driver e faz fallback para CPU.
- **Impacto estimado:** +300 ms ate +1.5 s por transcricao em falas curtas; maior em falas longas.
- **Solucao:** tentar explicitamente `cuda` com `int8_float16` e `float16` antes de CPU, sem depender apenas de `torch.cuda.is_available()`.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\n# backend/audio/stt.py\nif has_cuda:\n    self.device = \"cuda\"\n    self.compute_type = \"int8\"\n...\nconfigs_to_try = [\n    (self.device, self.compute_type),\n    (\"cpu\", \"int8\"),\n    (\"cpu\", \"default\"),\n]\n```|```python\n# tentar configs CUDA compativeis primeiro\nconfigs_to_try = [\n    (\"cuda\", \"int8_float16\"),\n    (\"cuda\", \"float16\"),\n    (\"cpu\", \"int8\"),\n    (\"cpu\", \"default\"),\n]\n```|

#### 2) Cold start no pipeline de voz (STT/TTS sem pre-warm no startup)
- **Arquivo:** `backend/main.py` (linhas 113-128), `backend/audio/stt.py` (linhas 223-225), `backend/audio/tts.py` (linhas 205-208)
- **Problema:** STT e TTS sao lazy; a primeira requisicao de voz paga carga de modelo e setup de rede.
- **Impacto estimado:** +2 ate +8 s na primeira interacao.
- **Solucao:** preaquecer no `lifespan` com `asyncio.to_thread(get_stt, "base")` e `get_tts()`, opcionalmente pre-gerar frases frequentes no cache.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\n# backend/main.py\nawait db.inicializar()\niniciar_scheduler()\n# wake word...\n```|```python\n# backend/main.py\nawait db.inicializar()\niniciar_scheduler()\n\nfrom backend.audio.stt import get_stt\nfrom backend.audio.tts import get_tts\n\nawait asyncio.gather(\n    asyncio.to_thread(get_stt, \"base\"),\n    asyncio.to_thread(get_tts),\n)\n```|

#### 3) Persistencia de sessao em JSON bloqueando event loop e regravando arquivo inteiro
- **Arquivo:** `backend/agent/memory.py` (linhas 120-131), `backend/main.py` (linhas 286, 383, 665), `backend/audio/wake_word.py` (linha 230)
- **Problema:** `PersistentMemory.save()` faz read+write completo do JSON a cada mensagem e de forma sincrona.
- **Impacto estimado:** +20-250 ms por turno; cresce conforme `sessions.json` aumenta; risco de corrida em escrita concorrente.
- **Solucao:** usar fila de escrita assicrona (write-behind) com lock; ou mover essa persistencia para SQLite (ja no stack).

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\n# backend/agent/memory.py\nif self.storage_path.exists():\n    with open(self.storage_path, \"r\") as f:\n        data = json.load(f)\n...\nwith open(self.storage_path, \"w\") as f:\n    json.dump(data, f)\n```|```python\n# proposta: writer async em background\nself._save_queue.put_nowait((session_id, history))\n\n# worker unico: agrega e escreve em lote a cada 200ms\nasync def _writer_loop():\n    ...\n```|

#### 4) SQLite com conexao por operacao e sem WAL
- **Arquivo:** `backend/memory/database.py` (linhas 59-62, 121, 145, 170, 194, 227, 256, 276, 299, 341, 370, 404, 438), `backend/core/logging_config.py` (linhas 143-150)
- **Problema:** cada metodo abre nova conexao; `PRAGMA journal_mode=WAL` nao e configurado; tool logging no SQLite amplifica custo.
- **Impacto estimado:** +10-80 ms por operacao e maior contencao sob concorrencia.
- **Solucao:** manter conexao unica em `self._conn`, ativar WAL + `synchronous=NORMAL` + `busy_timeout`.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\n# backend/memory/database.py\nasync with aiosqlite.connect(self.db_path) as conn:\n    await conn.execute(...)\n    await conn.commit()\n```|```python\n# conexao persistente no startup\nself._conn = await aiosqlite.connect(self.db_path)\nawait self._conn.execute(\"PRAGMA journal_mode=WAL\")\nawait self._conn.execute(\"PRAGMA synchronous=NORMAL\")\nawait self._conn.execute(\"PRAGMA busy_timeout=5000\")\n\n# metodos reutilizam self._conn + asyncio.Lock\n```|

#### 5) Tool de musica com `wait_for_timeout` fixo (latencia artificial alta)
- **Arquivo:** `backend/tools/music.py` (linhas 88, 158, 166, 217)
- **Problema:** esperas fixas de 3s/4s/5s/3s tornam acao de tocar musica lenta mesmo quando pagina ja carregou.
- **Impacto estimado:** +6 a +12 s por comando `tocar`.
- **Solucao:** trocar waits fixos por waits orientados a evento (`wait_for_selector`, `locator.wait_for`, timeout menor).

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\nawait page.goto(search_url, ...)\nawait page.wait_for_timeout(4000)\n...\nawait page.goto(watch_link, ...)\nawait page.wait_for_timeout(5000)\n```|```python\nawait page.goto(search_url, wait_until=\"domcontentloaded\")\nawait page.locator(\"ytmusic-responsive-list-item-renderer\").first.wait_for(timeout=4000)\n...\nawait page.goto(watch_link, wait_until=\"domcontentloaded\")\nawait page.locator(\"ytmusic-player-bar\").first.wait_for(timeout=4000)\n```|

#### 6) Pipeline de wake word sem trava anti-reentrancia
- **Arquivo:** `backend/audio/wake_word.py` (linhas 344-352)
- **Problema:** novas deteccoes podem disparar `_run_voice_pipeline()` em paralelo.
- **Impacto estimado:** duplicidade de STT/LLM/TTS, uso extra de CPU/RAM, respostas cruzadas e jitter.
- **Solucao:** guard com lock/flag (`_pipeline_running`) para ignorar wake words enquanto uma pipeline estiver ativa.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\nif result >= 0:\n    asyncio.run_coroutine_threadsafe(\n        _run_voice_pipeline(self._session_id, self._loop),\n        self._loop,\n    )\n```|```python\nif result >= 0 and not self._pipeline_running:\n    self._pipeline_running = True\n    fut = asyncio.run_coroutine_threadsafe(...)\n    fut.add_done_callback(lambda _: setattr(self, \"_pipeline_running\", False))\n```|

### 🟡 Importante (impacto medio)

#### 7) Busca vetorial em serie (pode rodar em paralelo)
- **Arquivo:** `backend/agent/agent.py` (linhas 385-386)
- **Problema:** `buscar_contexto()` e `buscar_fatos()` sao awaits sequenciais.
- **Impacto estimado:** +20-120 ms por chamada ao agente.
- **Solucao:** usar `asyncio.gather()` para as duas buscas.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\ncontexto_conversas = await vector_memory.buscar_contexto(mensagem)\ncontexto_fatos = await vector_memory.buscar_fatos(mensagem)\n```|```python\ncontexto_conversas, contexto_fatos = await asyncio.gather(\n    vector_memory.buscar_contexto(mensagem),\n    vector_memory.buscar_fatos(mensagem),\n)\n```|

#### 8) ChromaDB faz `count()` antes de cada `query()`
- **Arquivo:** `backend/agent/memory.py` (linhas 240-249, 294-303)
- **Problema:** duas chamadas por consulta (`count + query`).
- **Impacto estimado:** +10-40 ms por busca de contexto/fatos.
- **Solucao:** consultar direto com `n_results` fixo e tratar retorno vazio.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\ntotal = await asyncio.to_thread(self._conversas.count)\nif total == 0:\n    return []\nresultados = await asyncio.to_thread(\n    self._conversas.query,\n    query_embeddings=[embedding],\n    n_results=min(n_resultados, total),\n)\n```|```python\nresultados = await asyncio.to_thread(\n    self._conversas.query,\n    query_embeddings=[embedding],\n    n_results=n_resultados,\n)\n# se documents vier vazio -> []\n```|

#### 9) `httpx.AsyncClient()` criado por requisicao (sem pooling persistente)
- **Arquivo:** `backend/tools/web.py` (linhas 92, 138, 255), `backend/tools/news.py` (linhas 101, 162, 257), `telegram_bot/bot.py` (linhas 50, 59, 223), `backend/agent/agent.py` (linhas 661, 695)
- **Problema:** handshake/TLS e criacao de cliente repetidos.
- **Impacto estimado:** +20-150 ms por chamada externa; pior em sequencias.
- **Solucao:** cliente global por modulo com keep-alive e limites.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\nasync with httpx.AsyncClient(timeout=10.0) as client:\n    response = await client.get(...)\n```|```python\n_HTTP = httpx.AsyncClient(\n    timeout=httpx.Timeout(10.0),\n    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),\n)\nresponse = await _HTTP.get(...)\n```|

#### 10) WebSocket de audio manual usa base64 (overhead de CPU e payload)
- **Arquivo:** `frontend/src/app.js` (linhas 417-424), `backend/main.py` (linhas 615-616)
- **Problema:** encode/decode base64 em cada chunk (+33% payload).
- **Impacto estimado:** +10-60 ms em dispositivos mais lentos + uso extra de banda.
- **Solucao:** enviar `ArrayBuffer` binario no WebSocket (frames binarios), remover base64.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```javascript\nconst base64 = reader.result.split(',')[1];\nthis.ws.send(JSON.stringify({ type: 'audio_chunk', data: base64 }));\n```|```javascript\nconst buffer = await e.data.arrayBuffer();\nthis.ws.send(buffer); // frame binario\n```|

#### 11) Escrita de arquivo sincrona dentro de handlers async
- **Arquivo:** `backend/main.py` (linhas 360, 635), `backend/agent/memory.py` (linhas 123, 130)
- **Problema:** `write_bytes()` e `open()` bloqueiam event loop.
- **Impacto estimado:** +5-30 ms por request, aumentando sob concorrencia.
- **Solucao:** usar `aiofiles` ou `asyncio.to_thread` para I/O de disco.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\ntemp_audio_path.write_bytes(content)\n```|```python\nawait asyncio.to_thread(temp_audio_path.write_bytes, content)\n```|

#### 12) Broadcast de eventos de voz para clientes e sequencial
- **Arquivo:** `backend/audio/wake_word.py` (linhas 70-76)
- **Problema:** um cliente lento pode atrasar entrega para os demais.
- **Impacto estimado:** jitter de 50-500+ ms em UI/eventos.
- **Solucao:** `asyncio.gather(..., return_exceptions=True)` com timeout por cliente.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\nfor cb in list(_voice_listeners):\n    await cb(event)\n```|```python\nresults = await asyncio.gather(\n    *(asyncio.wait_for(cb(event), timeout=0.5) for cb in listeners),\n    return_exceptions=True,\n)\n```|

### 🟢 Melhoria (impacto baixo, mas vale fazer)

#### 13) Imports dinamicos em caminhos quentes
- **Arquivo:** `backend/audio/wake_word.py` (linhas 181-184), `backend/agent/agent.py` (linhas 332, 380, 459), `backend/main.py` (linhas 739-740)
- **Problema:** imports dentro de funcoes chamadas frequentemente.
- **Impacto estimado:** baixo por chamada, mas adiciona variabilidade e complexidade.
- **Solucao:** mover imports para escopo de modulo ou cachear referencias no startup.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\nfrom backend.audio.stt import get_stt\nfrom backend.audio.tts import get_tts\n```|```python\n# modulo\nfrom backend.audio.stt import get_stt\nfrom backend.audio.tts import get_tts\n# funcao usa direto\n```|

#### 14) Copias de audio evitaveis no wake word path
- **Arquivo:** `backend/audio/wake_word.py` (linhas 107, 156, 341)
- **Problema:** `indata.copy()`, `flatten()`, `astype()` e `concatenate()` geram copias extras.
- **Impacto estimado:** +5-25 ms e mais pressao de memoria por pipeline.
- **Solucao:** usar buffer pre-alocado ou gravar stream direto em arquivo temporario.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\nchunks.append(indata.copy())\n...\naudio = np.concatenate(chunks, axis=0).flatten()\n```|```python\n# opcoes: bytearray/np.memmap/soundfile stream writer\n# evitando concatenate final de muitos blocos\n```|

#### 15) Janela de historico por quantidade de mensagens, nao por tokens
- **Arquivo:** `backend/agent/memory.py` (linhas 27, 61-63), `backend/agent/agent.py` (linhas 306-315)
- **Problema:** 20 mensagens podem significar muitos tokens em conversas longas.
- **Impacto estimado:** custo e latencia de LLM sobem de forma imprevisivel.
- **Solucao:** aplicar budget por tokens (estimado) e truncar contexto por limite.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\nMAX_HISTORY = 20\n```|```python\n# manter tambem um budget por tokens\nMAX_HISTORY = 20\nMAX_PROMPT_TOKENS = 2500\n```|

#### 16) Falta telemetria de estagios do pipeline de voz
- **Arquivo:** `backend/audio/wake_word.py` (linhas 187-246)
- **Problema:** sem metricas por etapa, fica dificil provar ganhos.
- **Impacto estimado:** ciclo de tuning mais lento e regressao passa despercebida.
- **Solucao:** instrumentar timers por etapa e log estruturado.

| Codigo atual | Codigo corrigido (proposto) |
|---|---|
|```python\nlogger.info(\"Iniciando gravação de voz...\")\n...\nlogger.success(\"Pipeline de voz concluída\")\n```|```python\nt0 = time.perf_counter()\n...\nlogger.info(\"voice.pipeline\", extra={\n  \"stt_ms\": stt_ms,\n  \"llm_ms\": llm_ms,\n  \"tts_ms\": tts_ms,\n  \"total_ms\": total_ms,\n})\n```|

---

## Otimizacoes de startup

Ordem recomendada no `lifespan`:
1. Inicializar DB com conexao persistente + PRAGMAs (WAL, busy_timeout).
2. Inicializar scheduler.
3. Preaquecer STT (`get_stt("base")`) em thread.
4. Preaquecer TTS (`get_tts()`) e opcionalmente pre-gerar frases frequentes:
   - "Nao entendi, pode repetir?"
   - "Certo, executando."
   - "Pronto."
5. Inicializar cliente HTTP global para tools externas.
6. Iniciar wake word listener.

Exemplo de pre-warm:

```python
await asyncio.gather(
    asyncio.to_thread(get_stt, "base"),
    asyncio.to_thread(get_tts),
)
```

---

## Oportunidades de paralelismo

1. **Contexto vetorial em paralelo**
   - `backend/agent/agent.py` (`_buscar_contexto_vetorial`)
   - Trocar 2 awaits sequenciais por `asyncio.gather`.

2. **RSS + NewsAPI em paralelo para categoria economia**
   - `backend/tools/news.py` (linhas 352-359)
   - Hoje faz NewsAPI e depois RSS em serie.

3. **Alarme: TTS e Telegram em paralelo**
   - `backend/tools/system.py` (`_executar_alarme`, linhas 365-385)
   - Sao tarefas independentes; usar `gather(return_exceptions=True)`.

4. **Persistencia nao bloqueante**
   - `persistent_memory.save(...)` e `vector_memory.salvar_conversa(...)`
   - Responder ao usuario primeiro e persistir em background (fila com retry).

---

## Metricas para monitorar

Instrumentar e acompanhar (P50/P95/P99):

1. **Voice pipeline**
   - `voice_wake_to_record_start_ms`
   - `voice_record_duration_ms`
   - `voice_stt_ms`
   - `voice_llm_ms`
   - `voice_tts_ms`
   - `voice_total_after_record_ms` (fim da gravacao -> audio_ready)

2. **Tools**
   - `tool_call_ms{tool_name=...}`
   - `tool_call_fail_total{tool_name=...}`

3. **Memoria/Banco**
   - `persistent_memory_save_ms`
   - `sqlite_write_ms`
   - `vector_query_ms`
   - `vector_embed_ms`

4. **WebSocket**
   - `ws_voice_broadcast_ms`
   - `ws_audio_chunk_decode_ms`
   - `ws_audio_pipeline_ms`

5. **Infra**
   - CPU, RAM, VRAM, I/O de disco durante fala.
   - tamanho do `sessions.json`, quantidade de arquivos em `audio_cache`.

Template de log recomendado:

```python
logger.info(
    "voice.stage timing",
    extra={
        "session_id": session_id,
        "stt_ms": stt_ms,
        "llm_ms": llm_ms,
        "tts_ms": tts_ms,
        "total_ms": total_ms,
    },
)
```

---

## Ordem de execucao recomendada (Sprint 1)

1. STT config de GPU + pre-warm startup.
2. Remover waits fixos da tool de musica.
3. Conexao SQLite persistente + WAL.
4. Persistencia de sessao assicrona (fila).
5. Guard anti-reentrancia no wake word pipeline.
6. Instrumentacao de metricas por etapa.

Com isso, o ganho esperado e reduzir o tempo **fim-da-fala -> audio** em ~30-50% no caso comum e eliminar picos de cold start.
