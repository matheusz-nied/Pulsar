/**
 * app.js — Lógica principal do Pulsar.
 *
 * Gerencia views (chat / robô), WebSocket para streaming de áudio,
 * gravação de microfone, reprodução de TTS e sincronização
 * com o motor de animação do robô.
 */

const API_URL      = 'http://localhost:8000';
const WS_URL_AUDIO = 'ws://localhost:8000/ws/audio';
const WS_URL_VOICE = 'ws://localhost:8000/ws/voice';

class PulsarApp {
  constructor() {
    this.currentView = 'chat';
    this.sessionId = this._loadSessionId();
    this.messages = [];

    // WebSocket para streaming de áudio manual (botão mic)
    this.ws = null;
    this.wsReconnectDelay = 1000;

    // WebSocket para eventos de voz do backend (wake word / pipeline)
    this.wsVoice = null;
    this.wsVoiceReconnectDelay = 1000;

    // Streaming de chunks do agente via wsVoice
    this._voiceStreamingDiv = null;

    this.mediaRecorder = null;
    this.audioChunks = [];
    this.isRecording = false;

    this.idleTimer = null;
    this.idleTimeout = 5 * 60 * 1000;

    this.robot = null;
    this.settings = null;
    this.isProcessing = false;

    this._init();
  }

  async _init() {
    this._cacheElements();

    this.robot = new RobotAnimator(document.getElementById('robot-canvas'));
    this.settings = new SettingsManager(this);

    this._bindEvents();
    this._connectWebSocket();
    this._connectVoiceWebSocket();
    this._loadHistory();
    this._resetIdleTimer();
    this._setupTitlebar();

    if (this.settings.get('startInRobotView')) {
      this.switchView('robot');
    }

    this.robot.setEstado(ESTADOS.OCIOSO);
  }

  /* ---- DOM Caching ---- */

  _cacheElements() {
    this.chatView     = document.getElementById('chat-view');
    this.robotView    = document.getElementById('robot-view');
    this.chatMessages = document.getElementById('chat-messages');
    this.chatHistory  = document.getElementById('chat-history');
    this.messageInput = document.getElementById('message-input');
    this.sendBtn      = document.getElementById('send-btn');
    this.micBtn       = document.getElementById('mic-btn');
    this.statusDot    = document.getElementById('status-indicator');
    this.modelLabel   = document.getElementById('model-label');
  }

  /* ---- Event Binding ---- */

  _bindEvents() {
    this.sendBtn.addEventListener('click', () => this._sendMessage());

    this.messageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._sendMessage();
      }
    });

    // Auto-resize textarea
    this.messageInput.addEventListener('input', () => {
      this.messageInput.style.height = 'auto';
      this.messageInput.style.height = Math.min(this.messageInput.scrollHeight, 100) + 'px';
    });

    this.micBtn.addEventListener('click', () => this._toggleRecording());

    document.getElementById('robot-mode-btn').addEventListener('click', () => this.switchView('robot'));
    document.getElementById('chat-mode-btn').addEventListener('click', () => this.switchView('chat'));
    document.getElementById('settings-btn').addEventListener('click', () => this.settings.open());
    document.getElementById('clear-history-btn').addEventListener('click', () => this._clearHistory());

    // Idle detection
    ['mousemove', 'keydown', 'click', 'touchstart'].forEach(evt => {
      document.addEventListener(evt, () => this._resetIdleTimer());
    });
  }

  _setupTitlebar() {
    document.getElementById('btn-close').addEventListener('click', async () => {
      try {
        if (window.__TAURI__) {
          const { getCurrentWindow } = window.__TAURI__.window;
          await getCurrentWindow().close();
        } else {
          window.close();
        }
      } catch { window.close(); }
    });

    document.getElementById('btn-minimize').addEventListener('click', async () => {
      try {
        if (window.__TAURI__) {
          const { getCurrentWindow } = window.__TAURI__.window;
          await getCurrentWindow().minimize();
        }
      } catch { /* ignore */ }
    });
  }

  /* ---- Views ---- */

  switchView(view) {
    this.currentView = view;
    this.chatView.classList.toggle('active', view === 'chat');
    this.robotView.classList.toggle('active', view === 'robot');
  }

  /* ---- WebSocket (áudio manual via botão mic) ---- */

  _connectWebSocket() {
    this._setStatus('connecting');

    try {
      this.ws = new WebSocket(WS_URL_AUDIO);
    } catch {
      this._setStatus('offline');
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.wsReconnectDelay = 1000;
      // Status fica "online" quando o ws/voice também conectar
      if (this.wsVoice && this.wsVoice.readyState === WebSocket.OPEN) {
        this._setStatus('online');
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this._handleWSAudioMessage(data);
      } catch { /* non-JSON */ }
    };

    this.ws.onclose = () => {
      this._setStatus('offline');
      this._scheduleReconnect();
    };

    this.ws.onerror = () => {
      this._setStatus('offline');
    };
  }

  _scheduleReconnect() {
    setTimeout(() => {
      this.wsReconnectDelay = Math.min(this.wsReconnectDelay * 1.5, 10000);
      this._connectWebSocket();
    }, this.wsReconnectDelay);
  }

  // Eventos do WebSocket de áudio manual (botão mic → /ws/audio)
  _handleWSAudioMessage(data) {
    switch (data.type) {
      case 'transcricao':
        this.robot.onUserSpeaking();
        if (data.texto) this._addMessage('user', data.texto);
        break;
      case 'resposta_chunk':
        this.robot.onProcessing();
        if (data.texto) this._appendAssistantChunk(data.texto);
        break;
      case 'audio_ready':
        if (data.url) this._playAudio(data.url);
        break;
      case 'erro':
        this.robot.onError();
        this.isProcessing = false;
        this._removeTypingIndicator();
        this._addMessage('assistant', `Erro: ${data.mensagem || 'Erro desconhecido'}`);
        break;
    }
  }

  /* ---- WebSocket de voz (wake word + pipeline backend → /ws/voice) ---- */

  _connectVoiceWebSocket() {
    try {
      this.wsVoice = new WebSocket(WS_URL_VOICE);
    } catch {
      this._scheduleVoiceReconnect();
      return;
    }

    this.wsVoice.onopen = () => {
      this.wsVoiceReconnectDelay = 1000;
      this._setStatus('online');
      // Keep-alive: envia ping a cada 25s
      this._voicePingInterval = setInterval(() => {
        if (this.wsVoice && this.wsVoice.readyState === WebSocket.OPEN) {
          this.wsVoice.send('ping');
        }
      }, 25000);
    };

    this.wsVoice.onmessage = (event) => {
      if (event.data === 'pong') return;
      try {
        const data = JSON.parse(event.data);
        this._handleVoiceEvent(data);
      } catch { /* non-JSON */ }
    };

    this.wsVoice.onclose = () => {
      clearInterval(this._voicePingInterval);
      this._setStatus('offline');
      this._scheduleVoiceReconnect();
    };

    this.wsVoice.onerror = () => {
      this._setStatus('offline');
    };
  }

  _scheduleVoiceReconnect() {
    setTimeout(() => {
      this.wsVoiceReconnectDelay = Math.min(this.wsVoiceReconnectDelay * 1.5, 10000);
      this._connectVoiceWebSocket();
    }, this.wsVoiceReconnectDelay);
  }

  // Eventos do pipeline de voz backend (Porcupine → STT → Agente → TTS)
  _handleVoiceEvent(data) {
    switch (data.type) {
      case 'ping':
        // keep-alive do servidor, ignorar
        break;

      case 'wake_word':
        // Acorda o robô e muda para view robô
        this.robot.onWakeWord();
        this.switchView('robot');
        this._resetIdleTimer();
        break;

      case 'transcricao':
        // Mostra o que o usuário disse
        this.robot.onUserSpeaking();
        if (data.texto) {
          this._addMessage('user', data.texto);
          // Muda para chat para o usuário ver a conversa
          this.switchView('chat');
        }
        this.robot.onProcessing();
        // Prepara div de streaming para a resposta
        this._voiceStreamingDiv = null;
        break;

      case 'resposta_chunk':
        // Acumula resposta do agente em streaming
        if (data.texto) this._appendVoiceChunk(data.texto);
        break;

      case 'audio_ready':
        // Finaliza streaming e reproduz áudio
        this._finalizeVoiceStream();
        if (data.url) this._playAudio(data.url);
        break;

      case 'voice_idle':
        // Nenhum áudio detectado após wake word
        this.robot.onIdle();
        break;

      case 'erro':
        this.robot.onError();
        this._finalizeVoiceStream();
        this._addMessage('assistant', `Erro: ${data.mensagem || 'Erro desconhecido'}`);
        break;
    }
  }

  // Acumula chunks de resposta vindos do pipeline de voz (streaming)
  _appendVoiceChunk(text) {
    if (!this._voiceStreamingDiv) {
      const now = new Date();
      const timeStr = now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      this._voiceStreamingDiv = document.createElement('div');
      this._voiceStreamingDiv.className = 'message assistant streaming';
      this._voiceStreamingDiv.innerHTML =
        `<span class="msg-text"></span><span class="msg-time">${timeStr}</span>`;
      this.chatMessages.appendChild(this._voiceStreamingDiv);
    }
    const span = this._voiceStreamingDiv.querySelector('.msg-text');
    span.textContent += text;
    this._scrollToBottom();
  }

  _finalizeVoiceStream() {
    if (this._voiceStreamingDiv) {
      this._voiceStreamingDiv.classList.remove('streaming');
      const text = this._voiceStreamingDiv.querySelector('.msg-text').textContent;
      const timeStr = this._voiceStreamingDiv.querySelector('.msg-time').textContent;
      this.messages.push({ role: 'assistant', text, time: timeStr, timestamp: new Date().toISOString() });
      this._saveHistory();
      this._voiceStreamingDiv = null;
    }
  }

  _setStatus(status) {
    this.statusDot.className = 'status-dot ' + status;
    this.statusDot.title = {
      online: 'Conectado',
      offline: 'Desconectado',
      connecting: 'Conectando...',
    }[status] || status;
  }

  /* ---- Sending Messages ---- */

  async _sendMessage() {
    const text = this.messageInput.value.trim();
    if (!text || this.isProcessing) return;

    this.isProcessing = true;
    this.messageInput.value = '';
    this.messageInput.style.height = 'auto';

    this._addMessage('user', text);
    this._showTypingIndicator();
    this.robot.onProcessing();
    this._resetIdleTimer();

    try {
      const res = await fetch(`${API_URL}/conversar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mensagem: text,
          session_id: this.sessionId,
        }),
      });

      this._removeTypingIndicator();

      if (res.ok) {
        const data = await res.json();
        this.sessionId = data.session_id || this.sessionId;
        this._saveSessionId();

        this._addMessage('assistant', data.resposta);

        // Update model badge
        if (data.modelo_usado) {
          this.modelLabel.textContent = data.modelo_usado;
        }

        this.robot.onSuccess();

        // Play TTS if voice is active
        if (this.settings.get('voiceActive') && data.audio_url) {
          this._playAudio(data.audio_url);
        }
      } else {
        this.robot.onError();
        this._addMessage('assistant', 'Erro ao obter resposta do servidor.');
      }
    } catch (err) {
      this._removeTypingIndicator();
      this.robot.onError();
      this._addMessage('assistant', 'Erro de conexão com o backend.');
    }

    this.isProcessing = false;
  }

  /* ---- Audio Recording ---- */

  async _toggleRecording() {
    if (this.isRecording) {
      this._stopRecording();
    } else {
      await this._startRecording();
    }
  }

  async _startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      this.audioChunks = [];

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
          const reader = new FileReader();
          reader.onloadend = () => {
            const base64 = reader.result.split(',')[1];
            this.ws.send(JSON.stringify({
              type: 'audio_chunk',
              data: base64,
              session_id: this.sessionId,
            }));
          };
          reader.readAsDataURL(e.data);
        }
      };

      this.mediaRecorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({
            type: 'audio_end',
            session_id: this.sessionId,
          }));
        }
      };

      this.mediaRecorder.start(250);
      this.isRecording = true;
      this.micBtn.classList.add('recording');
      this.robot.onUserSpeaking();
    } catch {
      console.error('Microphone access denied');
    }
  }

  _stopRecording() {
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    this.isRecording = false;
    this.micBtn.classList.remove('recording');
    this.robot.onProcessing();
  }

  /* ---- Audio Playback ---- */

  _playAudio(url) {
    const fullUrl = url.startsWith('http') ? url : `${API_URL}${url}`;
    const audio = new Audio(fullUrl);

    this.robot.onAssistantSpeaking(audio);

    audio.play().catch(() => {
      this.robot.onIdle();
    });
  }

  /* ---- Chat Messages ---- */

  _addMessage(role, text) {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

    const msg = { role, text, time: timeStr, timestamp: now.toISOString() };
    this.messages.push(msg);
    this._saveHistory();

    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `<span class="msg-text">${this._escapeHTML(text)}</span><span class="msg-time">${timeStr}</span>`;

    this.chatMessages.appendChild(div);
    this._scrollToBottom();
  }

  _appendAssistantChunk(text) {
    // If there's a partial assistant message being built, append to it
    const lastMsg = this.chatMessages.querySelector('.message.assistant.streaming');
    if (lastMsg) {
      const span = lastMsg.querySelector('.msg-text');
      span.textContent += text;
      this._scrollToBottom();
      return;
    }

    this._removeTypingIndicator();

    const now = new Date();
    const timeStr = now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

    const div = document.createElement('div');
    div.className = 'message assistant streaming';
    div.innerHTML = `<span class="msg-text">${this._escapeHTML(text)}</span><span class="msg-time">${timeStr}</span>`;

    this.chatMessages.appendChild(div);
    this._scrollToBottom();
  }

  _showTypingIndicator() {
    this._removeTypingIndicator();
    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.id = 'typing-indicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';
    this.chatMessages.appendChild(indicator);
    this._scrollToBottom();
  }

  _removeTypingIndicator() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
  }

  _scrollToBottom() {
    this.chatHistory.scrollTop = this.chatHistory.scrollHeight;
  }

  _clearHistory() {
    if (!confirm('Limpar todo o histórico de conversas?')) return;
    this.messages = [];
    this.chatMessages.innerHTML = '';
    this._saveHistory();
    this.sessionId = crypto.randomUUID();
    this._saveSessionId();
  }

  _escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /* ---- Persistence ---- */

  _saveHistory() {
    try {
      const recent = this.messages.slice(-200);
      localStorage.setItem('pulsar_messages', JSON.stringify(recent));
    } catch { /* quota exceeded */ }
  }

  _loadHistory() {
    try {
      const stored = localStorage.getItem('pulsar_messages');
      if (stored) {
        this.messages = JSON.parse(stored);
        this.messages.forEach(msg => {
          const div = document.createElement('div');
          div.className = `message ${msg.role}`;
          div.innerHTML = `<span class="msg-text">${this._escapeHTML(msg.text)}</span><span class="msg-time">${msg.time}</span>`;
          this.chatMessages.appendChild(div);
        });
        this._scrollToBottom();
      }
    } catch { /* corrupted data */ }
  }

  _saveSessionId() {
    localStorage.setItem('pulsar_session_id', this.sessionId);
  }

  _loadSessionId() {
    return localStorage.getItem('pulsar_session_id') || crypto.randomUUID();
  }

  /* ---- Idle Detection ---- */

  _resetIdleTimer() {
    clearTimeout(this.idleTimer);
    if (this.robot && this.robot.estado === ESTADOS.DORMINDO) {
      this.robot.onWakeWord();
    }
    this.idleTimer = setTimeout(() => {
      if (this.robot) this.robot.onSleep();
    }, this.idleTimeout);
  }
}

// Boot
document.addEventListener('DOMContentLoaded', () => {
  window.pulsarApp = new PulsarApp();
});
