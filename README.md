<div align="center">

# ⚡ Pulsar

### Local AI assistant with voice I/O, task automation and persistent memory

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.1-FF6B35?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![Claude](https://img.shields.io/badge/Claude-Sonnet_4-CC785C?style=flat-square)](https://anthropic.com)
[![License](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)

</div>

---

**Pulsar** is a fully local AI assistant that listens, thinks, and acts. It combines a voice pipeline (STT → LLM → TTS), an agentic decision graph, and OS-level automation — all running on your machine, with no mandatory cloud dependency.

```
You: "Schedule a meeting tomorrow at 3pm and play some jazz while I work"
Pulsar: *creates Google Calendar event* + *starts YouTube Music* + "Done. Meeting set for tomorrow at 3pm."
```

---

## ✦ What it does

- 🎙️ **Voice I/O** — Speaks and listens via Whisper STT + Edge TTS, activated by wake word
- 🧠 **Persistent memory** — Remembers past conversations and user preferences via ChromaDB semantic search
- 🤖 **Agentic tools** — Executes real tasks: open apps, set alarms, search the web, control music, manage calendar
- 📱 **Mobile integration** — Send and receive commands from your phone via Telegram Bot
- 🔌 **Offline fallback** — Routes to local LLaMA 3.1 (Ollama) when Claude API is unavailable
- 🔒 **Secure by design** — Sandboxed command execution, app whitelist, verbal confirmation for critical actions

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        PULSAR                           │
│                                                         │
│  Voice Input      Backend (FastAPI)      Voice Output   │
│  ───────────  →  ──────────────────  →  ────────────    │
│  Porcupine        WebSocket /ws/audio    edge-tts        │
│  faster-whisper   POST /conversar        audio cache     │
│                   POST /voice                            │
│                         │                               │
│                   ┌─────┴──────┐                        │
│                   │  LangGraph │                        │
│                   │   Agent    │                        │
│                   └─────┬──────┘                        │
│                         │                               │
│         ┌───────────────┼───────────────┐               │
│         ▼               ▼               ▼               │
│    Claude API       Tools Layer      Memory Layer       │
│    (+ Ollama        web, system,     ChromaDB +         │
│     fallback)       calendar,        SQLite +           │
│                     music, alarm     session buffer     │
│                         │                               │
│                   Telegram Bot  ←──────────────────     │
│                   (mobile I/O)                          │
└─────────────────────────────────────────────────────────┘
```

---

## 🛠️ Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| AI Agent | LangGraph + Claude Sonnet (Anthropic) |
| Offline LLM | Ollama + LLaMA 3.1 8B |
| Voice STT | faster-whisper (OpenAI Whisper) |
| Voice TTS | edge-tts (Microsoft Neural Voices) |
| Wake Word | Porcupine (Picovoice) |
| Long-term Memory | ChromaDB + sentence-transformers |
| Structured Storage | SQLite (aiosqlite) |
| Browser Automation | Playwright |
| Scheduler | APScheduler |
| Mobile | Telegram Bot API |
| Desktop UI | Tauri (Rust + HTML/JS) |
| Logging | Loguru |

---

## 🚀 Getting started

**Prerequisites:** Python 3.11+, Node.js 18+, Rust (for Tauri)

```bash
# 1. Clone and install
git clone https://github.com/yourusername/pulsar.git && cd pulsar
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt && playwright install chromium

# 2. Configure
cp .env.example .env
# Edit .env — only ANTHROPIC_API_KEY is required to run

# 3. Run
uvicorn backend.main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at `/docs`.

> **Optional:** Run `python scripts/setup_google_auth.py` to enable Google Calendar integration.

---

## ⚙️ Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude API key |
| `TELEGRAM_BOT_TOKEN` | ○ | Telegram bot for mobile integration |
| `TELEGRAM_OWNER_ID` | ○ | Your Telegram user ID for notifications |
| `GOOGLE_CALENDAR_CREDENTIALS_PATH` | ○ | Path to Google OAuth2 credentials JSON |
| `SPOTIFY_CLIENT_ID` / `SECRET` | ○ | Spotify API for music control |
| `PORCUPINE_ACCESS_KEY` | ○ | Wake word detection (falls back to energy threshold) |
| `OLLAMA_BASE_URL` | ○ | Local LLM endpoint (default: `http://localhost:11434`) |

---

## 🗺️ Roadmap

- [x] Phase 1 — Text conversation with session memory
- [x] Phase 2 — Voice pipeline + first tools (web search, open apps, alarms)
- [ ] Phase 3 — Semantic memory (ChromaDB) + Google Calendar + music control
- [ ] Phase 4 — Tauri UI + Telegram Bot + Ollama offline fallback

---

## 📁 Project structure

```
pulsar/
├── backend/
│   ├── agent/          # LangGraph graph, memory, tool registry
│   ├── audio/          # STT (Whisper), TTS (edge-tts), wake word
│   ├── tools/          # web, system, calendar, music, alarms
│   ├── memory/         # ChromaDB + SQLite persistence
│   ├── security/       # Sandbox + confirmation manager
│   └── main.py         # FastAPI app + WebSocket endpoints
├── frontend/           # Tauri desktop app
├── telegram_bot/       # Mobile integration
├── scripts/            # Setup and utility scripts
└── tests/              # pytest test suite
```

---

## API endpoints

| Method | Route | Description |
|---|---|---|
| `POST` | `/conversar` | Send a text message, get a response |
| `POST` | `/voice` | Send audio file, get transcription + audio response |
| `WS` | `/ws/audio` | Real-time streaming voice pipeline |
| `GET` | `/health` | System status and component availability |
| `GET` | `/memoria` | List saved memories and preferences |
| `GET` | `/agendamentos` | List active scheduled tasks |

---

<div align="center">

MIT License · Built by [your name](https://github.com/yourusername)

</div>