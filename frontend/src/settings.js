/**
 * settings.js — Painel de configurações do Pulsar.
 *
 * Persiste em localStorage e sincroniza com o backend
 * via POST /configuracoes quando aplicável.
 */

const SETTINGS_DEFAULTS = {
  model: 'claude-sonnet-4-20250514',
  temperature: 0.7,
  offlineMode: false,
  voiceActive: true,
  voiceName: 'pt-BR-FranciscaNeural',
  voiceSpeed: 1.0,
  wakeWordActive: false,
  alwaysOnTop: true,
  startInRobotView: false,
  opacity: 100,
};

const STORAGE_KEY = 'pulsar_settings';
const BACKEND_URL = 'http://localhost:8000';

class SettingsManager {
  constructor(app) {
    this.app = app;
    this.values = { ...SETTINGS_DEFAULTS };
    this._load();
    this._cacheElements();
    this._bindEvents();
    this._applyToUI();
    this._applyAppearance();
  }

  /* ---- Public ---- */

  get(key) {
    return this.values[key];
  }

  open() {
    document.getElementById('settings-overlay').classList.remove('hidden');
  }

  close() {
    document.getElementById('settings-overlay').classList.add('hidden');
  }

  /* ---- Persistence ---- */

  _load() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        Object.assign(this.values, JSON.parse(stored));
      }
    } catch { /* first run */ }
  }

  _save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.values));
  }

  async _syncBackend() {
    try {
      await fetch(`${BACKEND_URL}/configuracoes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.values.model,
          temperature: this.values.temperature,
          offline_mode: this.values.offlineMode,
          voice_active: this.values.voiceActive,
          voice_name: this.values.voiceName,
          voice_speed: this.values.voiceSpeed,
          wake_word_active: this.values.wakeWordActive,
        }),
      });
    } catch {
      // Backend may not have /configuracoes yet
    }
  }

  /* ---- UI Binding ---- */

  _cacheElements() {
    this.els = {
      model:       document.getElementById('cfg-model'),
      temperature: document.getElementById('cfg-temperature'),
      tempVal:     document.getElementById('cfg-temperature-val'),
      offline:     document.getElementById('cfg-offline'),
      voiceActive: document.getElementById('cfg-voice-active'),
      voice:       document.getElementById('cfg-voice'),
      speed:       document.getElementById('cfg-speed'),
      speedVal:    document.getElementById('cfg-speed-val'),
      wakeword:    document.getElementById('cfg-wakeword'),
      ontop:       document.getElementById('cfg-ontop'),
      startrobot:  document.getElementById('cfg-startrobot'),
      opacity:     document.getElementById('cfg-opacity'),
      opacityVal:  document.getElementById('cfg-opacity-val'),
    };
  }

  _bindEvents() {
    // Close
    document.getElementById('settings-close-btn').addEventListener('click', () => this.close());
    document.getElementById('settings-overlay').addEventListener('click', (e) => {
      if (e.target.id === 'settings-overlay') this.close();
    });

    // LLM
    this.els.model.addEventListener('change', () => {
      this.values.model = this.els.model.value;
      this._onUpdate(true);
      this._updateModelBadge();
    });

    this.els.temperature.addEventListener('input', () => {
      this.values.temperature = parseFloat(this.els.temperature.value);
      this.els.tempVal.textContent = this.values.temperature.toFixed(1);
      this._onUpdate(true);
    });

    this.els.offline.addEventListener('change', () => {
      this.values.offlineMode = this.els.offline.checked;
      this._onUpdate(true);
    });

    // Voice
    this.els.voiceActive.addEventListener('change', () => {
      this.values.voiceActive = this.els.voiceActive.checked;
      this._onUpdate(true);
    });

    this.els.voice.addEventListener('change', () => {
      this.values.voiceName = this.els.voice.value;
      this._onUpdate(true);
    });

    this.els.speed.addEventListener('input', () => {
      this.values.voiceSpeed = parseFloat(this.els.speed.value);
      this.els.speedVal.textContent = this.values.voiceSpeed.toFixed(1) + 'x';
      this._onUpdate(true);
    });

    this.els.wakeword.addEventListener('change', () => {
      this.values.wakeWordActive = this.els.wakeword.checked;
      this._onUpdate(true);
    });

    // Appearance
    this.els.ontop.addEventListener('change', () => {
      this.values.alwaysOnTop = this.els.ontop.checked;
      this._onUpdate(false);
      this._setAlwaysOnTop(this.values.alwaysOnTop);
    });

    this.els.startrobot.addEventListener('change', () => {
      this.values.startInRobotView = this.els.startrobot.checked;
      this._onUpdate(false);
    });

    this.els.opacity.addEventListener('input', () => {
      this.values.opacity = parseInt(this.els.opacity.value, 10);
      this.els.opacityVal.textContent = this.values.opacity + '%';
      this._onUpdate(false);
      this._applyAppearance();
    });

    // Data actions
    document.getElementById('cfg-clear-memory').addEventListener('click', () => this._clearMemory());
    document.getElementById('cfg-export-history').addEventListener('click', () => this._exportHistory());
    document.getElementById('cfg-view-logs').addEventListener('click', () => this._viewLogs());
  }

  _applyToUI() {
    this.els.model.value = this.values.model;
    this.els.temperature.value = this.values.temperature;
    this.els.tempVal.textContent = this.values.temperature.toFixed(1);
    this.els.offline.checked = this.values.offlineMode;
    this.els.voiceActive.checked = this.values.voiceActive;
    this.els.voice.value = this.values.voiceName;
    this.els.speed.value = this.values.voiceSpeed;
    this.els.speedVal.textContent = this.values.voiceSpeed.toFixed(1) + 'x';
    this.els.wakeword.checked = this.values.wakeWordActive;
    this.els.ontop.checked = this.values.alwaysOnTop;
    this.els.startrobot.checked = this.values.startInRobotView;
    this.els.opacity.value = this.values.opacity;
    this.els.opacityVal.textContent = this.values.opacity + '%';
    this._updateModelBadge();
  }

  _onUpdate(syncBackend) {
    this._save();
    if (syncBackend) this._syncBackend();
  }

  /* ---- Appearance ---- */

  _applyAppearance() {
    document.getElementById('app').style.opacity = this.values.opacity / 100;
  }

  async _setAlwaysOnTop(value) {
    try {
      if (window.__TAURI__) {
        const { getCurrentWindow } = window.__TAURI__.window;
        await getCurrentWindow().setAlwaysOnTop(value);
      }
    } catch { /* not in Tauri context */ }
  }

  _updateModelBadge() {
    const label = document.getElementById('model-label');
    if (!label) return;
    const short = {
      'claude-sonnet-4-20250514': 'claude-sonnet',
      'ollama-llama3.1': 'ollama',
      'deepseek-chat': 'deepseek',
      'gemini': 'gemini',
    };
    label.textContent = short[this.values.model] || this.values.model;
  }

  /* ---- Data Actions ---- */

  async _clearMemory() {
    if (!confirm('Limpar toda a memória vetorial? Esta ação é irreversível.')) return;
    try {
      const res = await fetch(`${BACKEND_URL}/memory/clear`, { method: 'POST' });
      alert(res.ok ? 'Memória limpa com sucesso.' : 'Erro ao limpar memória.');
    } catch {
      alert('Não foi possível conectar ao backend.');
    }
  }

  _exportHistory() {
    const messages = this.app.messages || [];
    const blob = new Blob([JSON.stringify(messages, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pulsar_historico_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async _viewLogs() {
    const overlay = document.getElementById('logs-overlay');
    const content = document.getElementById('logs-content');
    overlay.classList.remove('hidden');
    content.textContent = 'Carregando...';

    document.getElementById('logs-close-btn').addEventListener('click', () => {
      overlay.classList.add('hidden');
    }, { once: true });

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.classList.add('hidden');
    }, { once: true });

    try {
      const res = await fetch(`${BACKEND_URL}/logs`);
      if (res.ok) {
        const data = await res.json();
        content.textContent = (data.logs || data.content || JSON.stringify(data, null, 2))
          .split('\n').slice(-50).join('\n');
      } else {
        content.textContent = 'Erro ao carregar logs (HTTP ' + res.status + ')';
      }
    } catch {
      content.textContent = 'Não foi possível conectar ao backend.';
    }
  }
}
