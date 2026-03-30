# 🤖 AGENTS.md — Pulsar

**Pulsar** é um assistente virtual local (FastAPI + LangGraph + Claude/Ollama + faster-whisper + edge-tts + ChromaDB + SQLite + Tauri + Telegram Bot). Roda predominantemente local; APIs externas têm fallbacks.

---

## ⚙️ Como Rodar

```bash
# Interpretador Python
/home/kaizen/Documents/Dev/Projetos/Pulsar/.conda_env/bin/python

# Ativar ambiente (detectado automaticamente pelo script)
export PATH="/home/kaizen/Documents/Dev/Projetos/Pulsar/.conda_env/bin:$PATH"

# Iniciar tudo (backend + bot + frontend Tauri)
bash scripts/start_all.sh        # logs em logs/backend.log, logs/bot.log, logs/frontend.log

# Só o backend
uvicorn backend.main:app --reload --port 8000

# Testes
pytest tests/ -v
```

> **Config:** `cp .env.example .env` — apenas `ANTHROPIC_API_KEY` é obrigatória.

---

## 🗂️ Estrutura de Pastas

```
backend/
├── agent/        # agent.py (ConversationAgent + LangGraph), memory.py, tools.py
├── audio/        # stt.py (Whisper), tts.py (edge-tts), wake_word.py (Porcupine)
├── audio_cache/  # .mp3 gerados pelo TTS — não versionar
├── core/         # logging_config.py (@log_tool_call, loguru)
├── memory/       # database.py (aiosqlite), assistente.db, chroma/, sessions.json
├── security/     # sandbox.py (SecurityManager, confirmação verbal)
├── tools/        # web.py, news.py, system.py, music.py, calendar_tool.py
└── main.py       # FastAPI — ponto de entrada
frontend/         # Tauri (HTML/CSS/JS + Rust)
telegram_bot/     # bot.py (python-telegram-bot v21+)
scripts/          # start_all.sh, start_bot.py
tests/            # pytest suite
```

---

## 🌐 API Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/health` | Status dos componentes |
| `POST` | `/conversar` | `{mensagem, session_id?}` → `{resposta, session_id, modelo_usado}` |
| `POST` | `/voice` | Áudio multipart → `{transcricao, resposta, audio_url, session_id}` |
| `WS` | `/ws/audio` | Streaming de voz em tempo real |
| `GET` | `/audio/{filename}` | Serve .mp3 do cache TTS |
| `GET` | `/memoria` | Lista memórias ChromaDB/SQLite |
| `GET` | `/agendamentos` | Lista alarmes ativos |
| `POST` | `/notify` | Envia notificação via Telegram |

**WS Protocol:** cliente envia `audio_chunk`/`audio_end` → servidor responde `transcricao` → `resposta_chunk` → `audio_ready`.

---

## 🧠 Fluxo do Agente

```
Usuário → FastAPI → ConversationAgent
    ├── Busca contexto no ChromaDB (VectorMemory)
    ├── LangGraph: nó "llm" (Claude) → se tool_call → nó "tools" → volta ao "llm"
    ├── Fallback automático: Claude falha → OllamaAgent (gemma3:4b-it-qat)
    └── Salva conversa no ChromaDB → retorna resposta
```

**LLM_PROVIDER** (via .env): `claude` | `gemini` | `openai` | `deepseek` | `groq` | `ollama`

---

## 📋 Padrões Obrigatórios

| # | Regra |
|---|-------|
| 1 | **Async por padrão** — todas as funções devem ser `async def` quando possível |
| 2 | **Type hints** em todos os parâmetros e retornos |
| 3 | **Docstring** em todo arquivo e função pública (Args + Returns) |
| 4 | **`loguru`** para logging — nunca `print()` |
| 5 | **`os.getenv()`** — nunca hardcode de chaves ou URLs |
| 6 | **Tools retornam string** — nunca propagam exceção para o LangGraph |
| 7 | **Provider Pattern** para serviços externos (ABC + auto-detecção via .env) |
| 8 | **Ações críticas** (`fechar_app`, `deletar_arquivo`, etc.) exigem confirmação verbal via `SecurityManager` |
| 9 | **Whitelists**: `APP_WHITELIST` (system.py) e `WHITELIST_DOMINIOS` (web.py) |
| 10 | **Instância global** por módulo: `stt`, `tts`, `search_service`, `db`, `security_manager` |

```python
# Exemplo padrão de tool
async def minha_tool(param: str) -> str:
    """Descrição clara para o LLM. Args: param. Returns: str."""
    try:
        return await fazer_algo(param)
    except Exception as e:
        logger.error(f"Erro na tool minha_tool: {e}")
        return f"Não foi possível executar: {str(e)}"
```

---

## 🔑 Variáveis de Ambiente

| Variável | Obrig. | Descrição |
|----------|--------|-----------|
| `LLM_PROVIDER` | ○ | `claude` (padrão), `gemini`, `openai`, `deepseek`, `groq`, `ollama` |
| `ANTHROPIC_API_KEY` | ✅ | Obrigatória se `LLM_PROVIDER=claude` |
| `GROQ_API_KEY` | ○ | Obrigatória se `LLM_PROVIDER=groq` |
| `GROQ_MODEL` | ○ | Default: `llama-3.3-70b-versatile` |
| `OLLAMA_BASE_URL` | ○ | Default: `http://localhost:11434` |
| `OLLAMA_MODEL` | ○ | Default: `gemma3:4b-it-qat` |
| `TELEGRAM_BOT_TOKEN` | ○ | Bot opcional; sem token é ignorado |
| `TELEGRAM_OWNER_ID` | ○ | Chat ID para notificações |
| `GOOGLE_CALENDAR_CREDENTIALS_PATH` | ○ | OAuth2 JSON do Google |
| `PORCUPINE_ACCESS_KEY` | ○ | Wake word; fallback por energia se ausente |
| `BRAVE_SEARCH_API_KEY` | ○ | Fallback: DuckDuckGo gratuito |
| `NEWS_API_KEY` / `ALPHA_VANTAGE_KEY` | ○ | Fallback: RSS gratuito |

---

## 📊 Status do Roadmap

| Fase | Status | Entregável |
|------|--------|------------|
| Fase 1 — MVP Texto | ✅ | Chatbot + memória de sessão |
| Fase 2 — Voz + Tools | ✅ | STT/TTS + WebSocket + 5 tools |
| Fase 3 — Memória + Tools Avançadas | ✅ | ChromaDB + SQLite + Música + Segurança |
| Fase 4 — Interface + Polimento | ✅ | Tauri + Telegram + Ollama + Logs |
| Fase 3.3 — Google Calendar | ⏳ | OAuth2 + criar/listar eventos |

---

## 🚀 Adicionando Nova Tool

1. Criar em `backend/tools/nome_tool.py` seguindo o padrão async + docstring + try/except
2. Registrar em `backend/agent/tools.py` com `StructuredTool.from_function(..., coroutine=fn)`
3. Aplicar `@log_tool_call` de `backend/core/logging_config.py`
4. Se crítica, adicionar nome em `ACOES_CRITICAS` no `backend/security/sandbox.py`
5. Criar `tests/test_nome_tool.py` (mockar Claude com `unittest.mock`)

---

## ⚡ Problemas Comuns

| Problema | Solução |
|----------|---------|
| `ImportError: faster-whisper` | Verificar PATH do Python → usar `.conda_env` |
| Porta 8000 ocupada | `lsof -ti:8000 \| xargs kill -9` |
| ChromaDB corrompido | Deletar `backend/memory/chroma/` e reiniciar |
| Claude erro 400 | Histórico muito longo → checar `MAX_HISTORY=20` |
| Playwright falha no YouTube Music | Atualizar seletores em `backend/tools/music.py` |
