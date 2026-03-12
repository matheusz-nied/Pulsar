|<p>**ASSISTENTE VIRTUAL LOCAL**</p><p>Plano Final de Projeto</p><p>Arquitetura • Tecnologias • Funcionalidades • Roadmap de Implementação</p>|
| :-: |

|*Este documento consolida todas as versões de planejamento em um plano definitivo: tecnologias selecionadas, funcionalidades completas e um passo a passo detalhado para construção do assistente, da fase MVP até o produto final.*|
| :- |

# **1. Visão Geral do Projeto**
O Assistente Virtual Local é uma aplicação desktop-first que combina inteligência artificial, processamento de voz e automação do sistema operacional. O objetivo é um assistente conversacional completo que rode predominantemente offline, com integrações externas pontuais.

## **Objetivos Centrais**
- Conversa por voz (input e output) com baixa latência
- Memória persistente de conversas e preferências do usuário
- Execução de tarefas no sistema operacional com segurança
- Agentes especializados para domínios específicos (música, agenda, pesquisa)
- Integração com celular para notificações e comandos remotos
- Funcionamento offline para componentes críticos


# **2. Stack Tecnológico Definitivo**
## **2.1 Backend e Orquestração**

|**Componente**|**Tecnologia Escolhida**|**Justificativa**|
| :- | :- | :- |
|Backend/API|FastAPI (Python)|Alta performance, suporte nativo a async, WebSockets e documentação automática|
|Agente de IA|LangGraph|Grafo de decisões robusto, suporte nativo a Function Calling e multi-agent|
|LLM Principal|Claude API (claude-sonnet-4-20250514)|Melhor custo-benefício, excelente raciocínio e segurança na execução de tools|
|LLM Local (fallback)|Ollama + LLaMA 3.1 8B|Funcionamento offline para tarefas simples sem dependência de API|
|Agendador|APScheduler|Gerencia tarefas agendadas, alarmes e lembretes com confiabilidade|

## **2.2 Voz (STT e TTS)**

|**Componente**|**Tecnologia**|**Detalhes**|
| :- | :- | :- |
|STT Principal|Whisper (OpenAI) — modelo medium|Reconhecimento offline de alta precisão, suporta português|
|STT Streaming|faster-whisper|Versão otimizada do Whisper com transcrição em tempo real|
|TTS Principal|edge-tts|Vozes neurais da Microsoft, gratuito, offline após cache|
|TTS Alternativo|Coqui-TTS|Vozes customizáveis, 100% local, maior controle sobre o output|
|Ativação por voz|porcupine (Picovoice)|Detecção de wake word local e leve ("Hey Assistente")|

## **2.3 Memória e Armazenamento**

|**Tipo de Memória**|**Tecnologia**|**Uso**|
| :- | :- | :- |
|Memória de curto prazo|Buffer em memória (Python dict)|Contexto da sessão atual (últimas 20 trocas)|
|Memória de longo prazo|ChromaDB + embeddings|Busca semântica em conversas anteriores e fatos do usuário|
|Embeddings|sentence-transformers (all-MiniLM-L6-v2)|Modelo leve e eficiente, 100% local|
|Dados estruturados|SQLite|Tarefas agendadas, preferências, histórico de ações|
|Cache de áudio|Sistema de arquivos local (.mp3)|Evita re-gerar TTS para respostas repetidas|

## **2.4 Segurança e Automação**

|**Componente**|**Tecnologia**|**Finalidade**|
| :- | :- | :- |
|Sandbox|Firejail (Linux) / AppContainer (Win)|Isola execução de comandos do SO|
|Automação web|Playwright (preferência) + Selenium|Controle de navegador para pesquisa e YouTube Music|
|Comunicação com celular|Telegram Bot API|Envio de notificações e recebimento de comandos|
|Comunicação em tempo real|WebSockets (via FastAPI)|Streaming de áudio e respostas sem polling|
|Interface|Tauri (Rust + HTML/CSS/JS)|App desktop nativo e leve, consome menos recursos que Electron|


# **3. Funcionalidades Completas**
## **3.1 Núcleo do Assistente**
- Conversa por voz com wake word (“Hey Assistente” ou personalizável)
- Conversa por texto via interface gráfica ou terminal
- Histórico de conversa persistência com busca semântica
- Memória de preferências pessoais (nome, rotinas, gostos)
- Resumo automático de contexto longo para economizar tokens
- Modo offline com fallback para LLM local (Ollama)

## **3.2 Ferramentas (Tools) do Agente**
**Controle do Sistema**

- Abrir aplicativos por nome ou categoria
- Fechar processos específicos
- Desligar, reiniciar ou colocar em suspenso o PC (com confirmação verbal)
- Ajustar volume e brilho
- Criar, mover e excluir arquivos (dentro de diretórios autorizados)

**Agenda e Produtividade**

- Criar e listar eventos no Google Calendar
- Definir lembretes e alarmes via APScheduler
- Integração com Google Tasks para to-do lists
- Leitura de e-mails (Gmail API — somente leitura por padrão)

**Mídia e Entretenimento**

- Tocar, pausar, avançar música no YouTube Music via Playwright
- Controlar Spotify via Spotify API oficial
- Abrir vídeos específicos no YouTube

**Pesquisa e Informação**

- Pesquisa na web com whitelist de domínios confiáveis
- Resumo automático de páginas web
- Consulta de clima, notícias e conversões (APIs públicas)
- Resposta a perguntas gerais via LLM

**Celular e Notificações**

- Envio de notificações para o celular via Telegram Bot
- Recebimento de comandos do celular para o PC
- Alertas de tarefas agendadas no celular


# **4. Arquitetura do Sistema**
## **4.1 Estrutura de Pastas**

|<p>**/assistente\_local/**</p><p>├── /backend/</p><p>│   ├── /agent/          # LangGraph: agent.py, memory.py, tools.py</p><p>│   ├── /audio\_cache/    # .mp3/.wav gerados pelo TTS</p><p>│   ├── /tools/          # Módulos: calendar.py, music.py, system.py...</p><p>│   ├── /memory/         # ChromaDB data + SQLite DB</p><p>│   └── main.py          # FastAPI app + WebSocket endpoints</p><p>├── /frontend/           # Tauri app (HTML/CSS/JS)</p><p>├── /telegram\_bot/       # Bot para integração com celular</p><p>├── .env                 # Chaves de API</p><p>├── requirements.txt</p><p>└── docker-compose.yml   # Orquestração (opcional)</p>|
| :- |

## **4.2 Rotas da API (FastAPI)**

|**Método**|**Rota**|**Descrição**|
| :- | :- | :- |
|POST|/conversar|Recebe texto, retorna resposta em texto|
|POST|/voice|Recebe áudio, retorna transcrição + áudio de resposta|
|WS|/ws/audio|WebSocket para streaming de voz em tempo real|
|GET|/health|Status do sistema e componentes ativos|
|GET|/memoria|Lista memórias e preferências salvas|
|DELETE|/memoria/{id}|Remove uma memória específica|
|GET|/agendamentos|Lista tarefas agendadas ativas|


# **5. Roadmap de Implementação**
O projeto é dividido em 4 fases progressivas. Cada fase entrega um produto funcional antes de avançar para a próxima.

|<p>**FASE 1**</p><p>Semanas 1–2</p>|**Esqueleto Funcional (MVP de Texto)**|
| :-: | :- |
|**1**|Configurar ambiente Python + FastAPI com rota POST /conversar e GET /health|
|**2**|Integrar Claude API com LangChain/LangGraph básico (sem tools ainda)|
|**3**|Implementar memória de sessão simples (lista Python com as últimas 20 mensagens)|
|**4**|Salvar histórico em arquivo JSON como persistência temporária|
|**5**|Testar o loop completo: usuário envia texto → Claude responde com contexto|
|**6**|Objetivo: ter um chatbot de texto funcional rodando localmente|

|<p>**FASE 2**</p><p>Semanas 3–5</p>|**Voz Completa + Primeiras Tools**|
| :-: | :- |
|**1**|Integrar faster-whisper para STT na rota POST /voice|
|**2**|Integrar edge-tts para TTS (retornar áudio mp3 na resposta)|
|**3**|Testar o loop de voz completo: fala → texto → LLM → voz|
|**4**|Implementar WebSocket (/ws/audio) para streaming em tempo real|
|**5**|Criar as primeiras tools no LangGraph: busca\_web(), abrir\_app(), definir\_alarme()|
|**6**|Configurar APScheduler para lembretes e tarefas agendadas|
|**7**|Adicionar wake word com Porcupine (“Hey Assistente”)|
|**8**|Objetivo: assistente de voz básico com 3 a 5 comandos funcionando|

|<p>**FASE 3**</p><p>Semanas 6–9</p>|**Memória Persistente + Tools Avançadas**|
| :-: | :- |
|**1**|Substituir JSON por ChromaDB com embeddings (sentence-transformers)|
|**2**|Implementar busca semântica no histórico de conversas|
|**3**|Migrar dados estruturados (agendamentos, preferências) para SQLite|
|**4**|Adicionar tool de Google Calendar (OAuth2 + leitura/criação de eventos)|
|**5**|Adicionar tool de controle de músia via Playwright (YouTube Music)|
|**6**|Adicionar Spotify API como alternativa de músia|
|**7**|Implementar tools de controle do sistema (volume, brilho, fechar apps)|
|**8**|Adicionar sandboxing (Firejail) para execução segura de comandos|
|**9**|Implementar confirmação verbal para ações críticas (desligar PC, deletar arquivo)|
|**10**|Objetivo: assistente completo com memória e automação real|

|<p>**FASE 4**</p><p>Semanas 10–13</p>|**Interface, Celular e Polimento**|
| :-: | :- |
|**1**|Desenvolver interface Tauri (janela flutuante, histórico visual, botão de voz)|
|**2**|Criar Telegram Bot para integração com celular (envio e recebimento de comandos)|
|**3**|Configurar Ollama + LLaMA 3.1 8B como fallback offline|
|**4**|Implementar lógica de roteamento: decisão automática entre API vs. local|
|**5**|Implementar sistema de logs estruturado (loguru + arquivo rotativo)|
|**6**|Adicionar painel de configurações na UI (voz, LLM, preferências)|
|**7**|Testes de integração ponta a ponta e correção de bugs|
|**8**|Documentar APIs internas e criar README completo|


# **6. Riscos e Mitigações**

|**Risco**|**Impacto**|**Mitigação**|
| :- | :- | :- |
|Latência alta no pipeline voz-to-voz|Alto|WebSockets para streaming; faster-whisper; cache de TTS|
|Custo de API (Claude/OpenAI)|Médio|Fallback para Ollama local; resumo de contexto para reduzir tokens|
|Segurança na execução de comandos|Alto|Sandboxing (Firejail), whitelist de comandos, confirmação verbal|
|Automação GUI frágil (pyautogui)|Médio|Preferência por APIs oficiais; usar Playwright ao invés de simulação de mouse|
|Contexto longo extrapolando limite de tokens|Médio|Resumo automático de conversas antigas; ChromaDB para recuperação seletiva|
|Privacidade (dados de voz/conversa)|Alto|Todos os componentes críticos rodam localmente; sem cloud de terceiros por padrão|

# **7. Dependências Python (requirements.txt)**

|<p># Core  fastapi uvicorn python-dotenv</p><p># LLM e Agente  langchain langgraph anthropic openai</p><p># Voz  faster-whisper edge-tts sounddevice pvporcupine</p><p># Memória  chromadb sentence-transformers sqlite3</p><p># Agendamento  apscheduler</p><p># Automação  playwright selenium</p><p># Integrações  google-api-python-client spotipy python-telegram-bot</p><p># Logs  loguru</p>|
| :- |

|*Próximo passo recomendado: Comece pela Fase 1 — crie o FastAPI básico e o loop texto-to-texto com Claude API funcionando. Isso valida toda a arquitetura antes de adicionar complexidade de voz e automação.*|
| :- |

Assistente Virtual Local  |  Plano Final de Projeto  |  Página 
