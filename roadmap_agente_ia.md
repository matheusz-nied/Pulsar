# 🤖 Roadmap para Agente de IA — Assistente Virtual Local
> Instruções otimizadas para execução por agente de IA em IDE (Cursor / Windsurf / Copilot Workspace)
> Cada tarefa é atômica, autocontida e tem critério de conclusão verificável.

---

## 📋 CONTEXTO GLOBAL DO PROJETO
> Cole este bloco no início de cada sessão com o agente.

```
Você está construindo um Assistente Virtual Local em Python.
Stack: FastAPI + LangGraph + Claude API + faster-whisper + edge-tts + ChromaDB + SQLite + APScheduler + Playwright + Telegram Bot + Tauri.
Estrutura de pastas raiz:
  /assistente_local/
    /backend/
      /agent/       → agent.py, memory.py, tools.py
      /audio_cache/ → arquivos .mp3/.wav gerados pelo TTS
      /tools/       → calendar.py, music.py, system.py, web.py
      /memory/      → dados do ChromaDB e SQLite
      main.py       → FastAPI app principal
    /frontend/      → Tauri app
    /telegram_bot/  → bot.py
    .env            → chaves de API
    requirements.txt

Regras gerais:
- Todo código deve ser async quando possível
- Usar tipagem estrita (type hints) em todas as funções
- Cada arquivo deve ter docstring explicando seu propósito
- Erros devem ser tratados com try/except e logados via loguru
- Nunca hardcodar chaves de API — sempre usar os.getenv()
- Executavel em /home/kaizen/Documents/Dev/Projetos/Jarvis/assistente_local/.conda_env/bin/python 
```

---

# Feita - FASE 1 — Esqueleto Funcional (MVP de Texto)
**Meta:** Loop texto → Claude → texto funcionando localmente.
**Duração estimada:** 2 semanas

---

## TAREFA Feita - 1.1 — Estrutura de pastas e ambiente

**Prompt para o agente:**
```
Crie a estrutura completa de pastas do projeto conforme abaixo.
Em cada pasta, crie um arquivo __init__.py vazio.
Crie também o arquivo .env.example com as variáveis necessárias.

Estrutura:
assistente_local/
├── backend/
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── memory.py
│   │   └── tools.py
│   ├── audio_cache/
│   │   └── .gitkeep
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── web.py
│   │   ├── system.py
│   │   ├── calendar_tool.py
│   │   └── music.py
│   ├── memory/
│   │   └── .gitkeep
│   └── main.py
├── frontend/
├── telegram_bot/
│   └── bot.py
├── .env.example
├── .gitignore
└── requirements.txt

O .env.example deve conter:
ANTHROPIC_API_KEY=
GOOGLE_CALENDAR_CREDENTIALS_PATH=
TELEGRAM_BOT_TOKEN=
PORCUPINE_ACCESS_KEY=
OLLAMA_BASE_URL=http://localhost:11434
BRAVE_SEARCH_API_KEY=
NEWS_API_KEY=
ALPHA_VANTAGE_KEY=
GNEWS_API_KEY=

O .gitignore deve ignorar: .env, __pycache__, *.pyc, /backend/audio_cache/*.mp3, /backend/memory/
```

**Critério de conclusão:** `find assistente_local -type f | sort` mostra todos os arquivos listados.

---

## Feita - TAREFA 1.2 — requirements.txt

**Prompt para o agente:**
```
Crie o arquivo requirements.txt com as dependências abaixo.
Mantenha os comentários de seção e pin das versões onde indicado.

# Core
fastapi==0.111.0
uvicorn[standard]==0.29.0
python-dotenv==1.0.1
pydantic==2.7.1

# LLM e Agente
langchain==0.2.0
langchain-anthropic==0.1.15
langgraph==0.1.5
anthropic==0.28.0

# Voz
faster-whisper==1.0.1
edge-tts==6.1.9
sounddevice==0.4.6
pvporcupine==3.0.0

# Memória
chromadb==0.5.0
sentence-transformers==3.0.1

# Agendamento
apscheduler==3.10.4

# Automação
playwright==1.44.0

# Integrações
google-api-python-client==2.130.0
google-auth-httplib2==0.2.0
google-auth-oauthlib==1.2.0
python-telegram-bot==21.3
feedparser==6.0.11

# Logs
loguru==0.7.2

# Dev
pytest==8.2.2
httpx==0.27.0
```

**Critério de conclusão:** `pip install -r requirements.txt` executa sem erros.

---

## Feita - TAREFA 1.3 — main.py (FastAPI base)

**Prompt para o agente:**
```
Crie o arquivo backend/main.py com as seguintes especificações:

1. FastAPI app com título "Assistente Virtual Local" e versão "0.1.0"
2. Configurar loguru para logar em console e em arquivo logs/app.log com rotação diária
3. Carregar variáveis de ambiente do arquivo .env na raiz do projeto
4. Implementar as seguintes rotas:
   - GET /health → retorna {"status": "ok", "version": "0.1.0", "components": {"llm": "online", "memory": "online"}}
   - POST /conversar → recebe {"mensagem": str, "session_id": str | None} e retorna {"resposta": str, "session_id": str}
     Por enquanto, a rota /conversar deve chamar uma função placeholder que retorna "Processando: {mensagem}"
5. Adicionar middleware CORS liberado para localhost
6. Incluir tratamento de exceções global que loga o erro e retorna HTTP 500 com mensagem amigável
7. No bloco if __name__ == "__main__": iniciar com uvicorn na porta 8000

Use type hints e docstrings em todas as funções.
```

**Critério de conclusão:** `uvicorn backend.main:app --reload` sobe sem erros. `GET /health` retorna 200.

---

## Feita - TAREFA 1.4 — Integração Claude API no agente

**Prompt para o agente:**
```
Crie o arquivo backend/agent/agent.py com as seguintes especificações:

1. Criar uma classe ConversationAgent com:
   - __init__(self): inicializa o cliente Anthropic usando ANTHROPIC_API_KEY(construir de maneira que permita trocar facilmente os provedores de IA e ate mesmo usar local) do ambiente
   - async def processar(self, mensagem: str, historico: list[dict]) -> str:
     → Chama a API do Claude (modelo: claude-sonnet-4-20250514, max_tokens: 1024)
     → Passa o histórico como messages anteriores
     → Retorna apenas o texto da resposta
     → Em caso de erro de API, loga e lança RuntimeError com mensagem amigável

2. O system prompt deve ser:
   "Você é um assistente virtual local chamado Jarvis. Você é direto, eficiente e responde em português brasileiro. Quando não souber algo, diz claramente."

3. O histórico deve seguir o formato: [{"role": "user"/"assistant", "content": str}]

4. Criar instância global: agent = ConversationAgent()

Não use LangGraph ainda — apenas o cliente Anthropic diretamente.
```

**Critério de conclusão:** Importar e instanciar `ConversationAgent` sem erros. Testar com `asyncio.run(agent.processar("Olá", []))` retorna string.

---

## Feita TAREFA 1.5 — Memória de sessão simples

**Prompt para o agente:**
```
Crie o arquivo backend/agent/memory.py com as seguintes especificações:

1. Classe SessionMemory:
   - Armazena histórico de conversas por session_id em um dict em memória
   - MAX_HISTORY = 20 mensagens por sessão (remove as mais antigas quando exceder)
   - Métodos:
     → get_history(session_id: str) -> list[dict]: retorna histórico da sessão
     → add_message(session_id: str, role: str, content: str) -> None: adiciona mensagem
     → clear_session(session_id: str) -> None: limpa sessão
     → list_sessions() -> list[str]: lista session_ids ativos

2. Classe PersistentMemory:
   - Salva e carrega histórico em arquivo JSON em backend/memory/sessions.json
   - Método save(session_id: str, history: list[dict]) -> None
   - Método load(session_id: str) -> list[dict]
   - Criar o diretório backend/memory/ se não existir

3. Criar instâncias globais:
   session_memory = SessionMemory()
   persistent_memory = PersistentMemory()
```

**Critério de conclusão:** Importar, adicionar 3 mensagens, recuperar histórico correto, salvar e recarregar do JSON.

---

## Feita - TAREFA 1.6 — Conectar tudo na rota /conversar

**Prompt para o agente:**
```
Atualize backend/main.py para conectar o agente e a memória na rota POST /conversar:

1. Importar ConversationAgent de backend.agent.agent
2. Importar session_memory e persistent_memory de backend.agent.memory
3. Se session_id não for fornecido, gerar um UUID novo com uuid.uuid4()
4. Fluxo da rota:
   a. Carregar histórico da sessão via session_memory.get_history(session_id)
   b. Chamar agent.processar(mensagem, historico)
   c. Adicionar mensagem do usuário E resposta do agente ao session_memory
   d. Persistir histórico atualizado via persistent_memory.save()
   e. Retornar {"resposta": resposta, "session_id": session_id}
5. A rota deve ser async

Mantenha o resto do arquivo intacto.
```

**Critério de conclusão:** `POST /conversar` com `{"mensagem": "Qual é a capital do Brasil?"}` retorna resposta coerente do Claude com session_id.

---

## Feita - TAREFA 1.7 — Testes da Fase 1

**Prompt para o agente:**
```
Crie o arquivo tests/test_fase1.py com testes usando pytest e httpx:

1. Fixture: client = TestClient(app) do FastAPI
2. test_health(): GET /health retorna 200 e status "ok"
3. test_conversar_sem_session(): POST /conversar sem session_id retorna resposta e gera session_id
4. test_conversar_com_contexto(): Duas mensagens na mesma sessão — segunda resposta demonstra que o contexto foi mantido
5. test_memory_limit(): Adicionar 25 mensagens → SessionMemory mantém apenas 20
6. test_persistent_memory(): Salvar e recarregar histórico do JSON

Mock da API do Claude usando unittest.mock para não gastar tokens nos testes.
```

**Critério de conclusão:** `pytest tests/test_fase1.py -v` passa todos os testes.

---

# Feita - FASE 2 — Voz Completa + Primeiras Tools
**Meta:** Fala → texto → Claude → voz funcionando. 3-5 tools ativas.
**Duração estimada:** 3 semanas

---

## Feita - TAREFA 2.1 — STT com faster-whisper

**Prompt para o agente:**
```
Crie o arquivo backend/audio/stt.py com as seguintes especificações:

1. Classe WhisperSTT:
   - __init__(self, model_size: str = "medium"): carrega o modelo faster-whisper
     Use device="cuda" se disponível, senão "cpu". compute_type="int8" para CPU.
   - async def transcrever(self, audio_path: str) -> str:
     → Transcreve o arquivo de áudio
     → language="pt" para forçar português
     → Retorna o texto concatenado de todos os segmentos
     → Loga tempo de transcrição
   - def transcrever_sync(self, audio_path: str) -> str: versão síncrona

2. Criar instância global: stt = WhisperSTT()
3. Tratar ImportError do faster-whisper com mensagem clara de instalação
```

**Critério de conclusão:** Transcrever um arquivo .wav de teste em português retorna texto correto.

---

## Feita - TAREFA 2.2 — TTS com edge-tts

**Prompt para o agente:**
```
Crie o arquivo backend/audio/tts.py com as seguintes especificações:

1. Classe EdgeTTS:
   - VOICE_PT = "pt-BR-FranciscaNeural"  (voz feminina padrão)
   - VOICE_PT_MALE = "pt-BR-AntonioNeural"
   - CACHE_DIR = "backend/audio_cache/"
   
   - async def sintetizar(self, texto: str, voice: str = None) -> str:
     → Gerar hash MD5 do texto+voice como nome do arquivo de cache
     → Se arquivo já existir no cache, retornar o path direto (sem re-gerar)
     → Gerar áudio com edge-tts e salvar como .mp3 no CACHE_DIR
     → Retornar o path do arquivo gerado
   
   - async def limpar_cache(self, max_files: int = 100) -> int:
     → Remove os arquivos mais antigos se cache tiver mais de max_files itens
     → Retorna quantidade de arquivos removidos

2. Criar instância global: tts = EdgeTTS()
```

**Critério de conclusão:** `await tts.sintetizar("Olá, tudo bem?")` cria arquivo .mp3 válido. Segunda chamada com mesmo texto retorna cache.

---

## Feita - TAREFA 2.3 — Rota POST /voice

**Prompt para o agente:**
```
Adicione a rota POST /voice no backend/main.py:

1. Recebe um arquivo de áudio via multipart/form-data (campo "audio") e campo opcional "session_id"
2. Salva o arquivo temporariamente em /tmp/input_{uuid}.wav
3. Chama stt.transcrever() para obter o texto
4. Chama agent.processar() com o texto transcrito e histórico da sessão
5. Chama tts.sintetizar() para gerar o áudio de resposta
6. Retorna JSON: {"transcricao": str, "resposta": str, "audio_url": str, "session_id": str}
7. O audio_url deve apontar para a rota GET /audio/{filename}
8. Adicionar rota GET /audio/{filename} que serve o arquivo .mp3 do cache

Limpar o arquivo temporário de input após processamento.
Toda a rota deve ser async.
```

**Critério de conclusão:** `curl -X POST /voice -F "audio=@teste.wav"` retorna JSON com transcrição, resposta e URL de áudio válida.

---

## Feita - Muito difícil (Opus 4.6) TAREFA 2.4 — WebSocket /ws/audio (streaming)

**Prompt para o agente:**
```
Adicione endpoint WebSocket em backend/main.py na rota /ws/audio:

Protocolo de mensagens (JSON):
- Cliente envia: {"type": "audio_chunk", "data": "<base64>", "session_id": "<id>"}
- Cliente envia: {"type": "audio_end", "session_id": "<id>"}  ← sinaliza fim do áudio
- Servidor responde: {"type": "transcricao", "texto": str}
- Servidor responde: {"type": "resposta_chunk", "texto": str}  ← streaming da resposta
- Servidor responde: {"type": "audio_ready", "url": str}
- Servidor responde: {"type": "erro", "mensagem": str}

Fluxo:
1. Receber chunks de áudio em base64 e acumular em buffer
2. Ao receber audio_end: decodificar e salvar como arquivo temporário
3. Transcrever com STT e enviar evento "transcricao"
4. Processar com Claude usando stream=True e enviar chunks via "resposta_chunk"
5. Gerar TTS da resposta completa e enviar "audio_ready"

Usar asyncio e websockets do FastAPI.
```

**Critério de conclusão:** Conexão WebSocket estabelece. Envio de audio_end dispara pipeline completo.

---

## Feita - TAREFA 2.5 — Tool: busca_web() com arquitetura trocável

**Prompt para o agente:**
```
Crie o arquivo backend/tools/web.py com arquitetura de provider pattern para busca:

1. Interface base SearchProvider (classe abstrata):
   from abc import ABC, abstractmethod
   
   class SearchProvider(ABC):
       @abstractmethod
       async def buscar(self, query: str, max_resultados: int) -> list[dict]:
           """Retorna lista de dicts com campos: title, url, description"""
           pass

2. Implementar BraveSearchProvider(SearchProvider):
   - Usar BRAVE_SEARCH_API_KEY do .env (os.getenv com fallback None)
   - Endpoint: https://api.search.brave.com/res/v1/web/search
   - Headers: {"Accept": "application/json", "X-Subscription-Token": API_KEY}
   - Params: {"q": query, "count": max_resultados}
   - try/except para capturar erros de API (loga e retorna lista vazia se falhar)
   - Retornar lista de dicts: [{"title": ..., "url": ..., "description": ...}]

3. Implementar DuckDuckGoProvider(SearchProvider) como fallback gratuito:
   - Sem necessidade de chave de API
   - URL: https://api.duckduckgo.com/?q={query}&format=json&no_html=1
   - Parser a resposta e retornar formato padronizado
   - try/except para garantir que não quebra o app

4. Criar SearchService:
   class SearchService:
       def __init__(self):
           # Detecta automaticamente qual provider usar
           brave_key = os.getenv("BRAVE_SEARCH_API_KEY")
           if brave_key:
               self.provider = BraveSearchProvider(brave_key)
               logger.info("SearchService usando BraveSearchProvider")
           else:
               self.provider = DuckDuckGoProvider()
               logger.info("SearchService usando DuckDuckGoProvider (fallback gratuito)")
       
       def trocar_provider(self, provider: SearchProvider) -> None:
           """Permite trocar provider em runtime"""
           self.provider = provider
           logger.info(f"Provider alterado para {provider.__class__.__name__}")
       
       async def buscar(self, query: str, max_resultados: int = 3) -> str:
           """Retorna resultados formatados como string para o LLM"""
           try:
               resultados = await self.provider.buscar(query, max_resultados)
               if not resultados:
                   return "Nenhum resultado encontrado."
               
               # Formatar para texto
               texto = "\n\n".join([
                   f"**{r['title']}**\n{r['url']}\n{r.get('description', '')}" 
                   for r in resultados
               ])
               return texto
           except Exception as e:
               logger.error(f"Erro na busca web: {e}")
               return f"Erro ao buscar: {str(e)}"

5. WHITELIST_DOMINIOS = [
     "wikipedia.org", "g1.globo.com", "bbc.com", "reuters.com",
     "weather.com", "openweathermap.org", "google.com/search"
   ]

6. async def resumir_pagina(url: str) -> str:
   - Verifica se domínio está na WHITELIST antes de acessar
   - Faz fetch do HTML com httpx
   - Extrai texto relevante (sem scripts/CSS) usando BeautifulSoup
   - Retorna os primeiros 2000 caracteres do conteúdo limpo
   - try/except para não quebrar se página não carregar

7. Criar instância global para uso nas tools:
   search_service = SearchService()
   
   async def buscar_web(query: str, max_resultados: int = 3) -> str:
       return await search_service.buscar(query, max_resultados)

Adicionar ao requirements.txt: beautifulsoup4 (httpx já presente)
```

**Critério de conclusão:** 
- Com BRAVE_SEARCH_API_KEY configurada: `await buscar_web("capital do Brasil")` usa Brave e retorna resultados
- Sem a chave: usa DuckDuckGo automaticamente sem erro
- Trocar para outro provider no futuro requer apenas criar nova classe que herda SearchProvider
- App não quebra se ambos os serviços falharem (retorna mensagem de erro amigável)

---

## Feita - Difícil (Opus 4.6) TAREFA 2.6 — Tool: buscar_noticias()

**Prompt para o agente:**
```
Crie o arquivo backend/tools/news.py com arquitetura de provider pattern para notícias:

1. Interface base NewsProvider (classe abstrata):
   from abc import ABC, abstractmethod
   
   class NewsProvider(ABC):
       @abstractmethod
       async def buscar(self, query: str, categoria: str, max_resultados: int) -> list[dict]:
           """Retorna lista de dicts com campos: title, description, url, source, published_at"""
           pass

2. Implementar NewsApiProvider(NewsProvider):
   - Usar NEWS_API_KEY do .env (os.getenv com fallback None)
   - Endpoint: https://newsapi.org/v2/everything
   - Fontes fixadas por categoria:
       CATEGORIAS_FONTES = {
           "ia_tech": "techcrunch,the-verge,wired,ars-technica,hacker-news",
           "financas": "bloomberg,financial-times,the-wall-street-journal",
           "economia": "reuters,bbc-news,associated-press",
           "software": "techcrunch,hacker-news,ars-technica"
       }
   - Params: {"apiKey": key, "sources": fontes, "q": query, "pageSize": max_resultados}
   - Fallback: se fonte não disponível no plano gratuito, busca por keyword apenas
   - try/except para capturar erros (retorna lista vazia se falhar)
   - Retornar lista padronizada com campos: title, description, url, source, published_at

3. Implementar RSSProvider(NewsProvider) para fontes brasileiras:
   - Usar feedparser (sem necessidade de chave de API)
   - Feeds por categoria:
       FEEDS_BR = {
           "financas_br": "https://valor.globo.com/rss/home",
           "economia_br": "https://exame.com/feed",
           "tech_br": "https://olhardigital.com.br/feed"
       }
   - Parser os feeds e retornar formato padronizado
   - try/except para garantir que não quebra se feed estiver offline

4. Implementar AlphaVantageProvider(NewsProvider) para finanças com sentiment:
   - Usar ALPHA_VANTAGE_KEY do .env (os.getenv com fallback None)
   - Endpoint: https://www.alphavantage.co/query?function=NEWS_SENTIMENT
   - Params: {"apikey": key, "topics": "finance", "limit": max_resultados}
   - Retornar campos extras: sentiment_score, sentiment_label (Bullish/Bearish/Neutral)
   - try/except para não quebrar se API falhar

5. Criar NewsService:
   class NewsService:
       def __init__(self):
           # Detecta automaticamente providers disponíveis
           self.providers = {}
           
           news_api_key = os.getenv("NEWS_API_KEY")
           if news_api_key:
               self.providers["newsapi"] = NewsApiProvider(news_api_key)
               logger.info("NewsApiProvider disponível")
           
           alpha_key = os.getenv("ALPHA_VANTAGE_KEY")
           if alpha_key:
               self.providers["alphavantage"] = AlphaVantageProvider(alpha_key)
               logger.info("AlphaVantageProvider disponível")
           
           # RSS sempre disponível (gratuito)
           self.providers["rss"] = RSSProvider()
           logger.info("RSSProvider disponível")
       
       async def buscar_por_categoria(self, categoria: str, query: str = "", max_resultados: int = 5) -> list[dict]:
           """Roteia para o provider apropriado baseado na categoria"""
           resultados = []
           
           try:
               if categoria in ["ia", "tech", "software"]:
                   if "newsapi" in self.providers:
                       resultados = await self.providers["newsapi"].buscar(query, categoria, max_resultados)
               
               elif categoria == "financas":
                   # Prefere Alpha Vantage se disponível (tem sentiment)
                   if "alphavantage" in self.providers:
                       resultados = await self.providers["alphavantage"].buscar(query, categoria, max_resultados)
                   elif "newsapi" in self.providers:
                       resultados = await self.providers["newsapi"].buscar(query, categoria, max_resultados)
               
               elif categoria == "economia":
                   # Mescla NewsAPI + RSS
                   if "newsapi" in self.providers:
                       news_api_results = await self.providers["newsapi"].buscar(query, categoria, max_resultados // 2)
                       resultados.extend(news_api_results)
                   
                   rss_results = await self.providers["rss"].buscar(query, "economia_br", max_resultados // 2)
                   resultados.extend(rss_results)
               
               elif categoria == "brasil":
                   # Apenas RSS (fontes brasileiras)
                   resultados = await self.providers["rss"].buscar(query, "tech_br", max_resultados)
               
               else:  # "geral"
                   # Tenta qualquer provider disponível
                   for provider_name, provider in self.providers.items():
                       try:
                           results = await provider.buscar(query, categoria, max_resultados)
                           if results:
                               resultados = results
                               break
                       except Exception as e:
                           logger.warning(f"Provider {provider_name} falhou: {e}")
                           continue
           
           except Exception as e:
               logger.error(f"Erro ao buscar notícias: {e}")
           
           return resultados[:max_resultados]
       
       def formatar_para_llm(self, noticias: list[dict]) -> str:
           """Formata as notícias como texto estruturado para injetar no contexto do LLM"""
           if not noticias:
               return "Nenhuma notícia encontrada."
           
           linhas = []
           for noticia in noticias:
               sentiment = ""
               if "sentiment_label" in noticia:
                   sentiment = f" [{noticia['sentiment_label']}]"
               
               linha = f"📰 [{noticia['source']}] {noticia['title']}{sentiment}\n   {noticia.get('description', '')}\n   {noticia.get('published_at', '')}\n"
               linhas.append(linha)
           
           return "\n".join(linhas)

6. Registrar como tool no LangGraph (em backend/agent/tools.py ou agent.py):
   news_service = NewsService()
   
   async def buscar_noticias(categoria: str = "geral", query: str = "") -> str:
       """Busca notícias recentes.
       
       Args:
           categoria: Uma de: ia, tech, financas, economia, software, brasil, geral
           query: Termo de busca opcional
       
       Returns:
           String formatada com as notícias encontradas
       """
       try:
           noticias = await news_service.buscar_por_categoria(categoria, query)
           return news_service.formatar_para_llm(noticias)
       except Exception as e:
           logger.error(f"Erro na tool buscar_noticias: {e}")
           return f"Não foi possível buscar notícias no momento: {str(e)}"

Adicionar ao requirements.txt: feedparser==6.0.11
```

**Critério de conclusão:**
- "Quais as notícias de IA hoje?" → retorna lista formatada de notícias tech sem quebrar
- "Como está o mercado financeiro?" → retorna notícias com sentiment quando Alpha Vantage configurado
- "Notícias do Brasil" → retorna feeds RSS brasileiros sem necessidade de chave
- Trocar ou adicionar provider no futuro requer apenas criar nova classe que herda NewsProvider
- **App não quebra se nenhum serviço de notícias estiver configurado ou se todos falharem** (retorna mensagem amigável)

---

## Feita - TAREFA 2.7 — Tool: abrir_app()

**Prompt para o agente:**
```
Crie no arquivo backend/tools/system.py as seguintes tools:

1. APP_WHITELIST: dict mapeando nomes amigáveis para executáveis:
   {
     "chrome": ["google-chrome", "chromium-browser", "chrome.exe"],
     "firefox": ["firefox", "firefox.exe"],
     "vscode": ["code", "code.exe"],
     "terminal": ["gnome-terminal", "xterm", "cmd.exe"],
     "calculadora": ["gnome-calculator", "calc.exe"],
   }

2. async def abrir_app(nome: str) -> str:
   - Normaliza o nome para minúsculas
   - Verifica se está na whitelist — se não estiver, retorna erro explicando
   - Tenta cada executável da lista até um funcionar (subprocess.Popen)
   - Detecta SO automaticamente (platform.system())
   - Retorna mensagem de sucesso ou erro

3. async def fechar_app(nome: str) -> str:
   - Usa psutil para encontrar processos pelo nome
   - Pede confirmação antes de fechar (retorna mensagem pedindo confirmação)
   - Método confirmar_fechar(nome: str) -> str que efetivamente fecha

4. async def ajustar_volume(nivel: int) -> str:
   - nivel: 0-100
   - Linux: usa pactl ou amixer
   - Windows: usa pycaw ou nircmd
   - Retorna nível atual após ajuste

Adicionar ao requirements.txt: psutil
```

**Critério de conclusão:** `await abrir_app("firefox")` abre o Firefox. App fora da whitelist retorna erro claro.

---

## Feito - TAREFA 2.8 — Tool: definir_alarme()

**Prompt para o agente:**
```
Crie no arquivo backend/tools/system.py (adicionar às funções existentes):

1. Inicializar APScheduler:
   from apscheduler.schedulers.asyncio import AsyncIOScheduler
   scheduler = AsyncIOScheduler()
   scheduler.start()  ← chamar no startup do FastAPI

2. async def definir_alarme(horario: str, mensagem: str) -> str:
   - horario: formato "HH:MM" ou "HH:MM DD/MM/YYYY"
   - Parsear horario para datetime
   - Agendar job único que:
     → Loga a mensagem
     → Chama tts.sintetizar(mensagem) e toca o áudio
     → Envia notificação via Telegram se configurado
   - Retorna confirmação com horário e ID do job

3. async def listar_alarmes() -> str:
   - Retorna lista formatada dos jobs agendados ativos com ID, horário e mensagem

4. async def cancelar_alarme(job_id: str) -> str:
   - Remove o job pelo ID
   - Retorna confirmação ou erro se não encontrado

Adicionar evento startup no FastAPI para iniciar o scheduler.
Adicionar evento shutdown para parar o scheduler graciosamente.
```

**Critério de conclusão:** Definir alarme para 2 minutos no futuro, `listar_alarmes()` mostra o job, alarme dispara no horário.

---

## Muito difícil (Opus 4.6) TAREFA 2.9 — Registrar tools no LangGraph

**Prompt para o agente:**
```
Atualize backend/agent/agent.py para usar LangGraph com as tools criadas:

1. Importar as tools: buscar_web, buscar_noticias, abrir_app, definir_alarme de seus módulos

2. Criar as definições de tool para o LangGraph:
   tools = [
     StructuredTool.from_function(buscar_web, name="buscar_web", description="Busca informações na web. Use quando o usuário pedir para pesquisar algo."),
     StructuredTool.from_function(buscar_noticias, name="buscar_noticias", description="Busca notícias recentes por categoria (ia, tech, financas, economia, software, brasil). Use quando o usuário pedir notícias ou informações sobre mercado/economia."),
     StructuredTool.from_function(abrir_app, name="abrir_app", description="Abre um aplicativo no computador. Use quando o usuário pedir para abrir um programa."),
     StructuredTool.from_function(definir_alarme, name="definir_alarme", description="Define um alarme ou lembrete. Use quando o usuário pedir para ser lembrado de algo.")
   ]

3. Construir grafo LangGraph com:
   - Nó "llm": chama Claude com as tools disponíveis
   - Nó "tools": executa a tool selecionada
   - Condicional: se LLM retornou tool_call → vai para "tools", senão → END
   - Após executar tool, volta para "llm" com resultado

4. Manter a interface pública: async def processar(self, mensagem: str, historico: list[dict]) -> str

Use langchain_anthropic.ChatAnthropic como LLM base.
```

**Critério de conclusão:** "Pesquisa sobre Python" aciona `buscar_web`. "Quais as notícias de tecnologia?" aciona `buscar_noticias`. "Abra o Firefox" aciona `abrir_app`. "Me lembre às 15h de tomar água" aciona `definir_alarme`.

---

## Difícil (Opus 4.6) TAREFA 2.10 — Wake word com Porcupine

**Prompt para o agente:**
```
Crie o arquivo backend/audio/wake_word.py:

1. Classe WakeWordDetector:
   - __init__(self): inicializa Porcupine com PORCUPINE_ACCESS_KEY do ambiente
     keyword: "jarvis" (ou "hey google" como fallback gratuito)
   - def iniciar(self, callback: callable) -> None:
     → Inicia thread daemon que escuta microfone continuamente via sounddevice
     → Quando wake word detectada: chama callback() e loga detecção
   - def parar(self) -> None: para a thread de escuta

2. Modo de fallback sem Porcupine:
   - Se PORCUPINE_ACCESS_KEY não estiver configurada, usar detecção simples por energia:
     → Monitorar nível de áudio e disparar quando ultrapassar threshold por 0.5s
     → Loga aviso de que está usando modo fallback

3. Integrar com main.py:
   - No startup: iniciar WakeWordDetector com callback que seta flag global "escutando = True"
   - Quando escutando=True: iniciar gravação por 5 segundos e enviar para /voice

Adicionar ao requirements.txt: pyaudio
```

**Critério de conclusão:** Dizer "Jarvis" (ou fazer barulho no fallback) aciona o pipeline de voz.

---

# FASE 3 — Memória Persistente + Tools Avançadas
**Meta:** ChromaDB ativo, Google Calendar, música e controle do sistema com segurança.
**Duração estimada:** 4 semanas

---

## Feita - Muito difícil (Opus 4.6) TAREFA 3.1 — ChromaDB + embeddings

**Prompt para o agente:**
```
Atualize backend/agent/memory.py adicionando a classe VectorMemory:

1. class VectorMemory:
   PERSIST_DIR = "backend/memory/chroma"
   COLLECTION_NAME = "conversas"
   EMBEDDING_MODEL = "all-MiniLM-L6-v2"
   
   - __init__(self): inicializa ChromaDB persistente e modelo de embeddings sentence-transformers
   
   - async def salvar_conversa(self, session_id: str, user_msg: str, assistant_msg: str) -> None:
     → Cria documento: f"Usuário: {user_msg}\nAssistente: {assistant_msg}"
     → Gera embedding e armazena no ChromaDB com metadata: {session_id, timestamp, tipo: "conversa"}
   
   - async def buscar_contexto(self, query: str, n_resultados: int = 5) -> list[str]:
     → Busca semanticamente no ChromaDB
     → Retorna lista de conversas relevantes como strings
   
   - async def salvar_fato(self, fato: str, categoria: str = "geral") -> None:
     → Armazena fato sobre o usuário (ex: "usuário prefere respostas curtas")
     → metadata: {tipo: "fato", categoria, timestamp}
   
   - async def buscar_fatos(self, query: str) -> list[str]:
     → Retorna fatos relevantes para a query

2. Atualizar ConversationAgent.processar() para:
   - Antes de chamar o LLM: buscar contexto relevante no VectorMemory
   - Injetar contexto encontrado no system prompt: "Contexto de conversas anteriores: ..."
   - Após resposta: salvar o par user/assistant no VectorMemory

3. Criar instância global: vector_memory = VectorMemory()
```

**Critério de conclusão:** Dizer um fato em uma sessão, iniciar nova sessão e perguntar sobre o fato — o agente recorda via busca semântica.

---

## Feita - TAREFA 3.2 — SQLite para dados estruturados

**Prompt para o agente:**
```
Crie o arquivo backend/memory/database.py:

1. Usar aiosqlite para operações assíncronas
2. DB_PATH = "backend/memory/assistente.db"

3. Criar as tabelas no startup (CREATE TABLE IF NOT EXISTS):

   alarmes(
     id TEXT PRIMARY KEY,
     horario TEXT NOT NULL,
     mensagem TEXT NOT NULL,
     criado_em TEXT NOT NULL,
     disparado INTEGER DEFAULT 0
   )
   
   preferencias(
     chave TEXT PRIMARY KEY,
     valor TEXT NOT NULL,
     atualizado_em TEXT NOT NULL
   )
   
   historico_acoes(
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     tipo TEXT NOT NULL,
     descricao TEXT NOT NULL,
     resultado TEXT,
     timestamp TEXT NOT NULL
   )

4. Classe Database com métodos async para cada tabela:
   - Alarmes: salvar_alarme(), buscar_alarmes_ativos(), marcar_disparado()
   - Preferências: set_preferencia(), get_preferencia(), listar_preferencias()
   - Histórico: registrar_acao(), buscar_acoes_recentes(limite=50)

5. Criar instância global: db = Database()
6. Chamar db.inicializar() no startup do FastAPI
```

**Critério de conclusão:** Salvar alarme, buscar alarmes ativos, registrar ação — tudo persistindo entre reinicializações.

---

## DEPOIS - Difícil (Opus 4.6?) TAREFA 3.3 — Tool: Google Calendar

**Prompt para o agente:**
```
Crie o arquivo backend/tools/calendar_tool.py:

1. Classe GoogleCalendarTool:
   - __init__(self): inicializa com credenciais OAuth2
     Arquivo de credenciais: caminho em GOOGLE_CALENDAR_CREDENTIALS_PATH do .env
     Token salvo em backend/memory/google_token.json
   
   - def autenticar(self) -> None:
     → Fluxo OAuth2 completo com google-auth-oauthlib
     → Scopes: ["https://www.googleapis.com/auth/calendar"]
     → Se token expirado, renovar automaticamente
   
   - async def criar_evento(self, titulo: str, data_hora: str, duracao_min: int = 60, descricao: str = "") -> str:
     → data_hora formato: "DD/MM/YYYY HH:MM"
     → Cria evento no calendário primário
     → Retorna link do evento criado
   
   - async def listar_eventos(self, dias: int = 7) -> str:
     → Lista próximos eventos dos próximos N dias
     → Retorna string formatada: "📅 [data] - [título] ([horário])"
   
   - async def deletar_evento(self, evento_id: str) -> str:
     → Pede confirmação antes (retorna mensagem de confirmação)

2. Registrar como tool no LangGraph em agent.py

Criar script separado: scripts/setup_google_auth.py que executa o fluxo OAuth2 uma vez.
```

**Critério de conclusão:** "Crie um evento amanhã às 14h chamado Reunião" → evento aparece no Google Calendar.

---

## Feita - Difícil (Opus 4.6?) TAREFA 3.4 — Tool: controle de música (YouTube Music)

**Prompt para o agente:**
```
Crie o arquivo backend/tools/music.py:

1. Classe YoutubeMusicController (usando Playwright):
   - async def iniciar_browser(self) -> None:
     → Inicia Playwright em modo headed (visível)
     → Abre YouTube Music (music.youtube.com)
     → Aguarda carregamento
     → try/except para capturar erros de inicialização
   
   - async def tocar(self, query: str) -> str:
     → Busca a música/artista na barra de pesquisa
     → Clica no primeiro resultado
     → Retorna nome do que está tocando
     → try/except para tratar falhas (ex: sem conexão, página mudou)
   
   - async def pausar(self) -> str:
     → Encontra e clica no botão de pause
     → try/except para capturar se botão não encontrado
   
   - async def proximo(self) -> str:
     → Clica no botão next track
     → try/except para tratar erros
   
   - async def volume(self, nivel: int) -> str:
     → Ajusta volume via slider da página
     → try/except para garantir que não quebra

2. Criar função principal de controle:
   youtube_controller = YoutubeMusicController()
   
   async def controlar_musica(acao: str, query: str = "") -> str:
       """Controla reprodução de música via YouTube Music.
       
       Args:
           acao: Uma de: tocar, pausar, proximo, volume
           query: Nome da música/artista (para acao=tocar) ou nível 0-100 (para acao=volume)
       
       Returns:
           Mensagem de status da ação
       """
       try:
           if acao == "tocar":
               return await youtube_controller.tocar(query)
           elif acao == "pausar":
               return await youtube_controller.pausar()
           elif acao == "proximo":
               return await youtube_controller.proximo()
           elif acao.startswith("volume"):
               nivel = int(query) if query else 50
               return await youtube_controller.volume(nivel)
           else:
               return f"Ação '{acao}' não reconhecida. Use: tocar, pausar, proximo, volume"
       except Exception as e:
           logger.error(f"Erro ao controlar música: {e}")
           return f"Não foi possível controlar a música: {str(e)}"

3. Registrar como tool no LangGraph
```

**Critério de conclusão:** 
- "Toca uma música do Coldplay" → música toca no YouTube Music
- **App não quebra se YouTube Music falhar ou Playwright não estiver instalado** (retorna mensagem de erro amigável)

---

## Muito difícil (Opus 4.6) TAREFA 3.5 — Sandboxing e confirmação verbal

**Prompt para o agente:**
```
Crie o arquivo backend/security/sandbox.py:

1. ACOES_CRITICAS = ["fechar_app", "deletar_arquivo", "desligar_pc", "reiniciar_pc"]

2. class SecurityManager:
   - confirmacoes_pendentes: dict[str, dict] = {}  ← {token: {acao, params, expira_em}}
   
   - def requer_confirmacao(self, acao: str, params: dict) -> str:
     → Gera token UUID único
     → Armazena em confirmacoes_pendentes com expiração de 30 segundos
     → Retorna mensagem: "⚠️ Ação crítica: {descricao}. Confirme dizendo 'confirmar {token[:4]}' ou 'cancelar'."
   
   - def confirmar(self, token_parcial: str) -> tuple[bool, dict | None]:
     → Busca token que começa com token_parcial
     → Verifica se não expirou
     → Remove das pendentes e retorna (True, params) se válido
   
   - def is_critica(self, nome_tool: str) -> bool:
     → Verifica se a tool está em ACOES_CRITICAS

3. Integrar no LangGraph em agent.py:
   - Antes de executar qualquer tool em ACOES_CRITICAS:
     → Chamar security_manager.requer_confirmacao()
     → Retornar a mensagem de confirmação ao usuário (não executar ainda)
   - Detectar quando usuário diz "confirmar XXXX" → executar ação pendente
   - Detectar "cancelar" → limpar pendentes e confirmar cancelamento

4. Criar instância global: security_manager = SecurityManager()
```

**Critério de conclusão:** "Desligue o PC" → retorna pedido de confirmação. "Confirmar XXXX" → executa. Sem confirmação em 30s → expira.

---

# FASE 4 — Interface, Celular e Polimento
**Meta:** UI funcional, Telegram Bot, Ollama offline, logs e documentação.
**Duração estimada:** 4 semanas

---

## Difícil (Sonnet 4.6 Thinking) - TAREFA 4.1 — Telegram Bot

**Prompt para o agente:**
```
Crie o arquivo telegram_bot/bot.py:

1. Usar python-telegram-bot v21+ com asyncio
2. TELEGRAM_BOT_TOKEN do .env

3. Handlers:
   - /start → mensagem de boas-vindas + instrução de uso
   - /status → chama GET /health do backend e exibe status dos componentes
   - /alarmes → chama GET /agendamentos e lista os ativos
   - Mensagem de texto qualquer → encaminha para POST /conversar e retorna resposta
   - Documento/áudio → encaminha para POST /voice
   
4. Função send_notification(mensagem: str) → envia mensagem pro chat do dono
   - OWNER_CHAT_ID = variável de ambiente TELEGRAM_OWNER_ID
   - Chamada por alarmes e eventos agendados

5. O bot deve rodar em processo separado (não bloquear o FastAPI)
   - Criar script de inicialização: scripts/start_bot.py
   - Ou adicionar como task assíncrona no startup do FastAPI

6. Adicionar endpoint POST /notify no FastAPI:
   → Recebe {"mensagem": str} e chama send_notification() do bot
```

**Critério de conclusão:** Mandar mensagem no Telegram → recebe resposta do assistente. Alarme disparado → notificação chega no celular.

---

## Difícil (Sonnet 4.6 Thinking) - TAREFA 4.2 — Fallback Ollama (modo offline)

**Prompt para o agente:**
```
Atualize backend/agent/agent.py para suportar fallback offline com Ollama:

1. Adicionar classe OllamaAgent:
   - OLLAMA_BASE_URL do .env (default: http://localhost:11434)
   - MODEL = "llama3.1:8b"
   - async def processar(self, mensagem: str, historico: list[dict]) -> str:
     → Chama API local do Ollama: POST /api/chat
     → Mesmo formato de histórico
     → Timeout de 30 segundos

2. Lógica de roteamento em ConversationAgent.processar():
   - Tentar Claude API primeiro
   - Se anthropic.APIConnectionError ou anthropic.RateLimitError:
     → Loga warning: "Claude indisponível, usando Ollama local"
     → Tenta OllamaAgent.processar()
     → Se Ollama também falhar: retorna mensagem de erro amigável
   - Adicionar método check_ollama() → bool que testa conectividade

3. Adicionar campo "modelo_usado" na resposta do /conversar:
   {"resposta": str, "session_id": str, "modelo_usado": "claude" | "ollama" | "erro"}

4. Atualizar GET /health para incluir status do Ollama:
   {"components": {"llm_claude": "online/offline", "llm_ollama": "online/offline", ...}}
```

**Critério de conclusão:** Desativar rede → assistente responde via Ollama. Reativar rede → volta a usar Claude.

---

## Moderado (Codex) - TAREFA 4.3 — Sistema de logs estruturado

**Prompt para o agente:**
```
Crie o arquivo backend/core/logging_config.py:

1. Configurar loguru com:
   - Console: nível INFO, formato colorido com timestamp
   - Arquivo logs/app.log: nível DEBUG, rotação diária, retenção 7 dias, compressão "zip"
   - Arquivo logs/errors.log: somente erros (nível ERROR), retenção 30 dias

2. Criar decorador @log_tool_call para as tools:
   - Loga: nome da tool, parâmetros (sem dados sensíveis), resultado, tempo de execução
   - Salva no SQLite via db.registrar_acao()

3. Criar decorador @log_api_call para chamadas externas:
   - Loga: endpoint, tokens usados (se Claude), tempo de resposta

4. Aplicar @log_tool_call em todas as tools existentes:
   buscar_web, abrir_app, definir_alarme, controlar_musica, criar_evento, listar_eventos

5. Adicionar rota GET /logs?tipo=erros&limite=50 no FastAPI:
   → Lê as últimas N linhas do arquivo de log correspondente
   → Retorna como lista de strings

Substituir todos os print() do projeto por logger.info/debug/error.
```

**Critério de conclusão:** Executar 5 comandos → `GET /logs?tipo=acoes&limite=10` mostra histórico detalhado.

---

## Muito difícil (Opus 4.6) - TAREFA 4.4 — Frontend Tauri (interface desktop)

**Prompt para o agente:**
```
Inicialize o projeto Tauri em /frontend/:

1. Estrutura do frontend/src/:
   - index.html: janela principal (400x600px, sempre no topo)
   - styles.css: tema escuro minimalista
   - app.js: lógica principal

2. Componentes visuais em index.html:
   - Header: nome "Jarvis" + indicador de status (verde/vermelho) + modelo em uso
   - Área de histórico: lista de mensagens (user=direita, assistant=esquerda)
   - Barra de input: campo de texto + botão microfone + botão enviar
   - Footer: botão configurações + botão limpar histórico

3. Funcionalidades em app.js:
   - Conectar ao WebSocket ws://localhost:8000/ws/audio
   - Botão microfone: gravar com MediaRecorder API, enviar chunks via WebSocket
   - Enviar texto via POST http://localhost:8000/conversar
   - Reproduzir áudio de resposta via Audio API do browser
   - Persistir histórico visual no localStorage

4. tauri.conf.json:
   - window: título "Jarvis", width: 400, height: 600, alwaysOnTop: true, decorations: false
   - Permissões: http (localhost:8000), websocket, audio

Criar também scripts/start_all.sh que inicia backend + bot + frontend em paralelo.
```

**Critério de conclusão:** `./scripts/start_all.sh` → janela flutuante aparece. Conversa por texto e voz funciona pela UI.

---

##  Moderado (Sonnet 4.6 Thinking) - TAREFA 4.5 — Documentação e README

**Prompt para o agente:**
```
Crie o arquivo README.md completo com:

1. Badges: Python version, FastAPI, LangGraph, licença

2. Seções:
   - Visão Geral (2 parágrafos)
   - Pré-requisitos (Python 3.11+, Node.js, Rust, Ollama opcional)
   - Instalação passo a passo:
     1. Clone do repositório
     2. python -m venv venv && source venv/bin/activate
     3. pip install -r requirements.txt
     4. playwright install chromium
     5. Copiar .env.example para .env e preencher variáveis
     6. python scripts/setup_google_auth.py (opcional)
     7. uvicorn backend.main:app --reload
   - Comandos de voz suportados (tabela com exemplos)
   - Arquitetura (diagrama ASCII do fluxo de dados)
   - Variáveis de ambiente (tabela com descrição e obrigatoriedade)
   - Contribuição e Licença (MIT)

3. Criar também docs/ARCHITECTURE.md com:
   - Diagrama de componentes em ASCII art
   - Descrição de cada módulo
   - Fluxo de uma requisição de voz ponta a ponta
```

**Critério de conclusão:** README renderiza corretamente no GitHub. Novo desenvolvedor consegue rodar o projeto seguindo apenas o README.

---

# 📊 RESUMO DO ROADMAP

| Fase | Tarefas | Entregável | Semanas |
|------|---------|-----------|---------|
| Fase 1 | 1.1 → 1.7 | Chatbot de texto funcional com memória de sessão | 1–2 |
| Fase 2 | 2.1 → 2.9 | Assistente de voz com 5 tools ativas | 3–5 |
| Fase 3 | 3.1 → 3.5 | Memória semântica + Calendar + Música + Segurança | 6–9 |
| Fase 4 | 4.1 → 4.5 | UI desktop + Telegram + Offline + Logs + Docs | 10–13 |

---

# ⚡ ORDEM DE EXECUÇÃO RECOMENDADA

```
1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7
                ↓
2.1 → 2.2 → 2.3 → 2.5 → 2.6 → 2.7 → 2.8 → 2.9 → 2.4 → 2.10
                ↓
3.2 → 3.1 → 3.3 → 3.4 → 3.5
                ↓
4.2 → 4.3 → 4.1 → 4.4 → 4.5
```

> **Regra de ouro:** Nunca avance para a próxima tarefa sem passar no critério de conclusão da atual.
> Se uma tarefa falhar, use o critério de conclusão como prompt de debug para o agente.
