/**
 * robot.js — Motor de animação pixel art do robô Pulsar.
 *
 * Canvas 200x200, blocos de 4px (grid 50x50) para mais detalhe
 * mantendo a estética pixel art. Todos os 9 estados implementados
 * com transições suaves e efeitos de partículas.
 */

const BLOCK = 4;
const GRID = 50;
const CANVAS_SIZE = 200;

const COLORS = {
  bg:      '#020205',
  dim:     '#1a1a2e',
  primary: '#00f2ff', // Cyan elétrico
  secondary:'#7000ff', // Roxo tático
  blue:    '#0077ff',
  yellow:  '#fdfd96',
  orange:  '#ff9f1c',
  red:     '#ff4d4d',
  white:   '#ffffff',
  face:    '#080812',
  core:    '#121225',
  glow:    'rgba(0, 242, 255, 0.4)',
};

const ESTADOS = {
  DORMINDO:   'DORMINDO',
  ACORDANDO:  'ACORDANDO',
  OCIOSO:     'OCIOSO',
  ESCUTANDO:  'ESCUTANDO',
  PENSANDO:   'PENSANDO',
  FALANDO:    'FALANDO',
  EXECUTANDO: 'EXECUTANDO',
  ERRO:       'ERRO',
  SUCESSO:    'SUCESSO',
};

const STATUS_TEXT = {
  DORMINDO:   'ZZZ...',
  ACORDANDO:  'ACORDANDO...',
  OCIOSO:     'AGUARDANDO...',
  ESCUTANDO:  'ESCUTANDO...',
  PENSANDO:   'PENSANDO...',
  FALANDO:    'FALANDO...',
  EXECUTANDO: 'EXECUTANDO...',
  ERRO:       'ERRO!',
  SUCESSO:    'SUCESSO!',
};

class RobotAnimator {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.estado = ESTADOS.OCIOSO;
    this.prevEstado = null;
    this.transitionProgress = 1;
    this.transitionDuration = 300;
    this.transitionStart = 0;

    this.t = 0;
    this.frame = 0;
    this.lastTime = 0;

    this.blinkTimer = 0;
    this.blinkDuration = 0;
    this.isBlinking = false;
    this.nextBlink = this._randomBlink();

    this.eyeOpenness = 1;
    this.targetEyeOpenness = 1;

    this.headOffsetX = 0;
    this.headOffsetY = 0;
    this.targetHeadOffsetX = 0;
    this.targetHeadOffsetY = 0;

    this.mouthFrame = 0;
    this.mouthTimer = 0;

    this.particles = [];
    this.soundWaves = [];
    this.dots = { visible: 0, timer: 0 };
    this.gearAngle = 0;
    this.shakeX = 0;

    this.altEyeTimer = 0;
    this.altEyeLeft = true;

    this.sleepZs = [];
    this.sleepZTimer = 0;

    // Sistema de sons de thinking
    this._audioCtx = null;
    this._thinkingOsc = null;
    this._thinkingGain = null;
    this._thinkingInterval = null;
    this._thinkingSounds = [];

    this._running = true;
    this._raf = requestAnimationFrame((ts) => this._loop(ts));
  }

  /* ---- Audio System for Thinking Sounds ---- */
/* ---- Audio System — Robotic Thinking Sounds ---- */

_initAudio() {
  if (this._audioCtx) return;
  this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  this._masterGain = this._audioCtx.createGain();
  this._masterGain.gain.value = 0.6;
  this._masterGain.connect(this._audioCtx.destination);
}

_startThinkingSound() {
  this._initAudio();
  if (this._thinkingInterval) return;

  this._thinkingTick();
  this._thinkingInterval = setInterval(() => {
    if (this.estado !== ESTADOS.PENSANDO && this.estado !== ESTADOS.EXECUTANDO) {
      this._stopThinkingSound();
      return;
    }
    this._thinkingTick();
  }, 180 + Math.random() * 280);
}

_stopThinkingSound() {
  if (this._thinkingInterval) {
    clearInterval(this._thinkingInterval);
    this._thinkingInterval = null;
  }
}

_thinkingTick() {
  const t = Math.random();
  if      (t < 0.25) this._playSweep();
  else if (t < 0.50) this._playDataBurst();
  else if (t < 0.70) this._playTone([523,659,784,1046,1318][Math.floor(Math.random()*5)], 'sine', 0.08 + Math.random()*0.08, 0.12);
  else if (t < 0.85) this._playTone(200 + Math.random()*120, 'triangle', 0.12, 0.1);
  else               this._playGlitch();
}

// Tom simples com envelope rápido
_playTone(freq, type, duration, gainPeak, filterFreq = null) {
  const ctx = this._audioCtx;
  const osc  = ctx.createOscillator();
  const gain = ctx.createGain();

  if (filterFreq) {
    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.value = filterFreq;
    filter.Q.value = 2.5;
    osc.connect(filter);
    filter.connect(gain);
  } else {
    osc.connect(gain);
  }
  gain.connect(this._masterGain);

  osc.type = type;
  osc.frequency.setValueAtTime(freq, ctx.currentTime);

  gain.gain.setValueAtTime(0, ctx.currentTime);
  gain.gain.linearRampToValueAtTime(gainPeak, ctx.currentTime + 0.008);
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);

  osc.start(ctx.currentTime);
  osc.stop(ctx.currentTime + duration + 0.01);
}

// Varredura ascendente ou descendente — sensação de scan/análise
_playSweep() {
  const ctx  = this._audioCtx;
  const osc  = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.connect(gain);
  gain.connect(this._masterGain);

  osc.type = 'sawtooth';
  const up = Math.random() > 0.5;
  osc.frequency.setValueAtTime(up ? 300 : 2400, ctx.currentTime);
  osc.frequency.exponentialRampToValueAtTime(up ? 2400 : 300, ctx.currentTime + 0.18);

  gain.gain.setValueAtTime(0, ctx.currentTime);
  gain.gain.linearRampToValueAtTime(0.18, ctx.currentTime + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.18);

  osc.start(ctx.currentTime);
  osc.stop(ctx.currentTime + 0.2);
}

// Rajada de notas rápidas — sensação de processamento de dados
_playDataBurst() {
  const steps = 5 + Math.floor(Math.random() * 5);
  const freqs = [440, 523, 659, 784, 1047, 1319];
  for (let i = 0; i < steps; i++) {
    setTimeout(() => {
      const f = freqs[Math.floor(Math.random() * freqs.length)];
      this._playTone(f, 'square', 0.04, 0.12, f * 1.5);
    }, i * (18 + Math.random() * 22));
  }
}

// Ruído filtrado curto — glitch / falha de leitura
_playGlitch() {
  const ctx    = this._audioCtx;
  const len    = Math.floor(ctx.sampleRate * 0.12);
  const buf    = ctx.createBuffer(1, len, ctx.sampleRate);
  const data   = buf.getChannelData(0);

  for (let i = 0; i < len; i++) {
    const env = i < len * 0.1
      ? i / (len * 0.1)
      : Math.exp(-(i - len * 0.1) / (len * 0.3));
    data[i] = (Math.random() * 2 - 1) * env;
  }

  const src    = ctx.createBufferSource();
  const gain   = ctx.createGain();
  const filter = ctx.createBiquadFilter();
  filter.type = 'highpass';
  filter.frequency.value = 800;

  src.buffer = buf;
  src.connect(filter);
  filter.connect(gain);
  gain.connect(this._masterGain);
  gain.gain.value = 0.35;
  src.start();
}

  /* ---- Public API ---- */

  setEstado(estado) {
    if (estado === this.estado) return;
    this.prevEstado = this.estado;
    this.estado = estado;
    this.transitionProgress = 0;
    this.transitionStart = performance.now();
    this._onEnterState(estado);

    const statusEl = document.getElementById('robot-status');
    if (statusEl) statusEl.textContent = STATUS_TEXT[estado] || '';
  }

  onWakeWord() {
    this.setEstado(ESTADOS.ACORDANDO);
    setTimeout(() => {
      if (this.estado === ESTADOS.ACORDANDO) this.setEstado(ESTADOS.ESCUTANDO);
    }, 800);
  }

  onUserSpeaking()   { this.setEstado(ESTADOS.ESCUTANDO); }
  onProcessing()     { this.setEstado(ESTADOS.PENSANDO); }
  onToolExecution()  { this.setEstado(ESTADOS.EXECUTANDO); }

  onAssistantSpeaking(audioElement) {
    this.setEstado(ESTADOS.FALANDO);
    if (audioElement) {
      audioElement.addEventListener('ended', () => {
        if (this.estado === ESTADOS.FALANDO) this.setEstado(ESTADOS.OCIOSO);
      }, { once: true });
    }
  }

  onSuccess() {
    this.setEstado(ESTADOS.SUCESSO);
    setTimeout(() => {
      if (this.estado === ESTADOS.SUCESSO) this.setEstado(ESTADOS.OCIOSO);
    }, 1500);
  }

  onError() {
    this.setEstado(ESTADOS.ERRO);
    setTimeout(() => {
      if (this.estado === ESTADOS.ERRO) this.setEstado(ESTADOS.OCIOSO);
    }, 2000);
  }

  onIdle() { this.setEstado(ESTADOS.OCIOSO); }

  onSleep() { this.setEstado(ESTADOS.DORMINDO); }

  destroy() {
    this._running = false;
    cancelAnimationFrame(this._raf);
  }

  /* ---- State enter callbacks ---- */

  _onEnterState(state) {
    switch (state) {
      case ESTADOS.DORMINDO:
        this.targetEyeOpenness = 0;
        this._stopThinkingSound();
        break;
      case ESTADOS.ACORDANDO:
        this.eyeOpenness = 0;
        this.targetEyeOpenness = 1;
        break;
      case ESTADOS.PENSANDO:
      case ESTADOS.EXECUTANDO:
        this._startThinkingSound();
        break;
      case ESTADOS.SUCESSO:
        this._stopThinkingSound();
        this._spawnStars(12);
        break;
      case ESTADOS.ERRO:
        this._stopThinkingSound();
        this.shakeX = 8;
        break;
      case ESTADOS.OCIOSO:
      case ESTADOS.FALANDO:
        this._stopThinkingSound();
        this.targetEyeOpenness = 1;
        break;
      default:
        this.targetEyeOpenness = 1;
        break;
    }
  }

  /* ---- Main Loop ---- */

  _loop(timestamp) {
    if (!this._running) return;
    const dt = Math.min(timestamp - (this.lastTime || timestamp), 50);
    this.lastTime = timestamp;
    this.t += dt;
    this.frame++;

    this._update(dt);
    this._render();

    this._raf = requestAnimationFrame((ts) => this._loop(ts));
  }

  /* ---- Update ---- */

  _update(dt) {
    if (this.transitionProgress < 1) {
      this.transitionProgress = Math.min(1, (performance.now() - this.transitionStart) / this.transitionDuration);
    }

    this.eyeOpenness += (this.targetEyeOpenness - this.eyeOpenness) * 0.1;

    // Blinking (for OCIOSO and ESCUTANDO)
    if (this.estado === ESTADOS.OCIOSO || this.estado === ESTADOS.ESCUTANDO ||
        this.estado === ESTADOS.FALANDO) {
      this.blinkTimer += dt;
      if (!this.isBlinking && this.blinkTimer > this.nextBlink) {
        this.isBlinking = true;
        this.blinkTimer = 0;
        this.blinkDuration = 200;
      }
      if (this.isBlinking) {
        if (this.blinkTimer < this.blinkDuration * 0.5) {
          this.targetEyeOpenness = 0;
        } else if (this.blinkTimer < this.blinkDuration) {
          this.targetEyeOpenness = 1;
        } else {
          this.isBlinking = false;
          this.targetEyeOpenness = 1;
          this.blinkTimer = 0;
          this.nextBlink = this._randomBlink();
        }
      }
    }

    // Slow blink for DORMINDO
    if (this.estado === ESTADOS.DORMINDO) {
      this.sleepZTimer += dt;
      if (this.sleepZTimer > 3000) {
        this.sleepZTimer = 0;
        this.eyeOpenness = 0.3;
        setTimeout(() => { this.eyeOpenness = 0; }, 400);
        this.sleepZs.push({ x: 30, y: 10, opacity: 1, size: 0.5 });
      }
      this.targetHeadOffsetX = Math.sin(this.t / 2000) * 1;
    }

    // Sleep Zs
    this.sleepZs = this.sleepZs.filter(z => {
      z.y -= dt * 0.008;
      z.opacity -= dt * 0.0004;
      z.size += dt * 0.0003;
      return z.opacity > 0;
    });

    // Head offset
    if (this.estado === ESTADOS.ESCUTANDO) {
      this.targetHeadOffsetX = 2;
    } else if (this.estado === ESTADOS.PENSANDO) {
      this.targetHeadOffsetX = Math.sin(this.t / 800) * 1.5;
    } else if (this.estado !== ESTADOS.DORMINDO) {
      this.targetHeadOffsetX = 0;
    }
    this.headOffsetX += (this.targetHeadOffsetX - this.headOffsetX) * 0.08;

    // Shake for ERRO
    if (this.shakeX > 0.2) {
      this.shakeX *= 0.85;
      this.headOffsetX += Math.sin(this.t / 30) * this.shakeX;
    }

    // Mouth animation for FALANDO
    if (this.estado === ESTADOS.FALANDO) {
      this.mouthTimer += dt;
      if (this.mouthTimer > 120) {
        this.mouthTimer = 0;
        this.mouthFrame = (this.mouthFrame + 1) % 4;
      }
    }

    // Sound waves for ESCUTANDO / FALANDO
    if (this.estado === ESTADOS.ESCUTANDO || this.estado === ESTADOS.FALANDO) {
      if (this.frame % 15 === 0) {
        this.soundWaves.push({ radius: 2, opacity: 0.6, side: this.estado === ESTADOS.FALANDO ? 'mouth' : 'both' });
      }
    }
    this.soundWaves = this.soundWaves.filter(w => {
      w.radius += dt * 0.02;
      w.opacity -= dt * 0.001;
      return w.opacity > 0;
    });

    // Dots for PENSANDO
    if (this.estado === ESTADOS.PENSANDO) {
      this.dots.timer += dt;
      if (this.dots.timer > 400) {
        this.dots.timer = 0;
        this.dots.visible = (this.dots.visible + 1) % 4;
      }
    }

    // Gear for EXECUTANDO
    if (this.estado === ESTADOS.EXECUTANDO) {
      this.gearAngle += dt * 0.003;
      this.altEyeTimer += dt;
      if (this.altEyeTimer > 300) {
        this.altEyeTimer = 0;
        this.altEyeLeft = !this.altEyeLeft;
      }
    }

    // Particles
    this.particles = this.particles.filter(p => {
      p.x += p.vx * dt * 0.06;
      p.y += p.vy * dt * 0.06;
      p.life -= dt;
      p.opacity = Math.max(0, p.life / p.maxLife);
      return p.life > 0;
    });
  }

  /* ---- Render ---- */

  _render() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);

    this._drawFace(ctx);
    this._drawEffects(ctx);
  }

  /* ---- Drawing primitives ---- */

  _px(gx, gy, color) {
    this.ctx.fillStyle = color;
    this.ctx.fillRect(gx * BLOCK, gy * BLOCK, BLOCK, BLOCK);
  }

  _rect(gx, gy, gw, gh, color) {
    this.ctx.fillStyle = color;
    this.ctx.fillRect(gx * BLOCK, gy * BLOCK, gw * BLOCK, gh * BLOCK);
  }

  /* ---- Face ---- */

  _drawFace(ctx) {
    const cx = CANVAS_SIZE / 2;
    const cy = CANVAS_SIZE / 2;
    const time = this.t / 1000;
    const stateColor = this._getEyeColor();

    // 1. Aura Volumétrica (Bloom)
    const auraPulse = 0.4 + Math.sin(time * 2) * 0.1;
    const auraGrad = ctx.createRadialGradient(cx, cy, 40, cx, cy, 95);
    auraGrad.addColorStop(0, 'rgba(0, 0, 0, 0)');
    auraGrad.addColorStop(0.5, stateColor + '10'); // Transparência hex
    auraGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = auraGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, 100, 0, Math.PI * 2);
    ctx.fill();

    // 2. Esfera Central (O "Core")
    ctx.save();
    ctx.translate(cx, cy);
    
    // Efeito de flutuação orgânica
    const floatX = Math.sin(time * 1.5) * 3;
    const floatY = Math.cos(time * 1.2) * 4;
    ctx.translate(floatX, floatY);

    // Corpo esférico metálico/vidro
    const bodyGrad = ctx.createRadialGradient(-15, -20, 5, 0, 0, 60);
    bodyGrad.addColorStop(0, '#2a2a4a');
    bodyGrad.addColorStop(0.5, COLORS.face);
    bodyGrad.addColorStop(1, '#050508');
    
    ctx.shadowBlur = 30;
    ctx.shadowColor = stateColor + '40';
    ctx.fillStyle = bodyGrad;
    ctx.beginPath();
    ctx.arc(0, 0, 55, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    // 3. Anéis Orbitais (Personalidade Doida)
    ctx.rotate(time * 0.5);
    for (let i = 0; i < 2; i++) {
        ctx.beginPath();
        ctx.ellipse(0, 0, 75 + i * 5, 25, (i * Math.PI / 2) + time * 0.2, 0, Math.PI * 2);
        ctx.strokeStyle = stateColor;
        ctx.lineWidth = 0.5;
        ctx.globalAlpha = 0.2 + Math.sin(time + i) * 0.1;
        ctx.stroke();
        
        // Pequenos nós de energia nos anéis
        const nodePos = time * (1 + i * 0.5);
        const nx = Math.cos(nodePos) * (75 + i * 5);
        const ny = Math.sin(nodePos) * 25;
        ctx.fillStyle = COLORS.white;
        ctx.globalAlpha = 0.8;
        ctx.beginPath();
        ctx.arc(nx, ny, 1.5, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.restore();

    // 4. Interface Holográfica (Sobreposta ao Core)
    this._drawHolographicFace(ctx, cx + floatX, cy + floatY);
  }

  _drawHolographicFace(ctx, x, y) {
    const time = this.t / 1000;
    const color = this._getEyeColor();
    
    ctx.save();
    ctx.translate(x, y);

    // Linhas de varredura tática dentro da esfera
    ctx.strokeStyle = color;
    ctx.lineWidth = 0.5;
    ctx.globalAlpha = 0.1;
    for(let i = -40; i <= 40; i += 8) {
        ctx.beginPath();
        ctx.moveTo(-45, i);
        ctx.lineTo(45, i);
        ctx.stroke();
    }
    ctx.globalAlpha = 1;

    this._drawDeepEyes(ctx, color);
    this._drawEnergyMouth(ctx, color);
    
    ctx.restore();
  }

  _drawDeepEyes(ctx, color) {
    const time = this.t / 1000;
    const eyeY = -5;
    const eyeSpacing = 18;

    [-1, 1].forEach(dir => {
        const ex = dir * eyeSpacing;
        
        // Camada 1: Brilho de profundidade (Holograma)
        const eyeGrad = ctx.createRadialGradient(ex, eyeY, 0, ex, eyeY, 12);
        eyeGrad.addColorStop(0, color);
        eyeGrad.addColorStop(0.4, color + '40');
        eyeGrad.addColorStop(1, 'rgba(0,0,0,0)');
        
        ctx.fillStyle = eyeGrad;
        ctx.beginPath();
        ctx.arc(ex, eyeY, 12, 0, Math.PI * 2);
        ctx.fill();

        // Camada 2: A íris "tecnológica"
        ctx.strokeStyle = COLORS.white;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.6;
        ctx.beginPath();
        ctx.arc(ex, eyeY, 6 * this.eyeOpenness, 0, Math.PI * 2);
        ctx.stroke();

        // Camada 3: Pupila reativa (Micro-vibração)
        const pupSize = 2 + Math.sin(time * 20) * 0.3;
        ctx.fillStyle = COLORS.white;
        ctx.beginPath();
        ctx.arc(ex, eyeY, pupSize * this.eyeOpenness, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
    });
  }

  _drawEnergyMouth(ctx, color) {
    const time = this.t / 1000;
    const my = 20;
    
    ctx.shadowBlur = 10;
    ctx.shadowColor = color;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;

    ctx.beginPath();
    if (this.estado === ESTADOS.FALANDO) {
        // Visualizador de espectro circular
        for(let a = 0; a < Math.PI * 2; a += 0.2) {
            const r = 8 + Math.abs(Math.sin(a * 2 + time * 10)) * 6;
            const x = Math.cos(a) * r;
            const y = my + Math.sin(a) * r * 0.5;
            if (a === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
    } else if (this.estado === ESTADOS.ESCUTANDO) {
        // Pulso de escuta (Sinewave de energia)
        for(let i = -20; i <= 20; i += 2) {
            const v = Math.sin(i * 0.2 + time * 15) * 5;
            if (i === -20) ctx.moveTo(i, my + v);
            else ctx.lineTo(i, my + v);
        }
    } else {
        // Ocioso: Linha de energia estável com partículas
        ctx.moveTo(-15, my);
        ctx.bezierCurveTo(-5, my + 2, 5, my + 2, 15, my);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  /* ---- Eyes ---- */

  _drawEyes(ctx) {
    const eyeColor = this._getEyeColor();
    const lx = 14, rx = 30, ey = 18;
    const ew = 6, eh = 4;

    if (this.estado === ESTADOS.ERRO) {
      this._drawXEye(lx, ey, ew, eh, COLORS.red);
      this._drawXEye(rx, ey, ew, eh, COLORS.red);
      return;
    }

    if (this.estado === ESTADOS.SUCESSO) {
      this._drawHappyEye(lx, ey, ew, eh, eyeColor);
      this._drawHappyEye(rx, ey, ew, eh, eyeColor);
      return;
    }

    const openH = Math.max(1, Math.round(eh * this.eyeOpenness));
    const yOff = Math.round((eh - openH) / 2);

    // EXECUTANDO: alternating blink
    if (this.estado === ESTADOS.EXECUTANDO) {
      const leftOpen = this.altEyeLeft ? openH : Math.max(1, Math.round(openH * 0.3));
      const rightOpen = this.altEyeLeft ? Math.max(1, Math.round(openH * 0.3)) : openH;

      this._drawSingleEye(lx, ey + yOff, ew, leftOpen, eyeColor, 'center');
      this._drawSingleEye(rx, ey + yOff, ew, rightOpen, eyeColor, 'center');
      return;
    }

    // Pupil position
    let pupilPos = 'center';
    if (this.estado === ESTADOS.PENSANDO) pupilPos = 'up-right';
    if (this.estado === ESTADOS.ESCUTANDO) pupilPos = 'center';

    // Enlarged eyes for ESCUTANDO
    let extraSize = 0;
    if (this.estado === ESTADOS.ESCUTANDO) extraSize = 1;

    this._drawSingleEye(lx - extraSize, ey + yOff - extraSize, ew + extraSize, openH + extraSize, eyeColor, pupilPos);
    this._drawSingleEye(rx, ey + yOff - extraSize, ew + extraSize, openH + extraSize, eyeColor, pupilPos);
  }

  _drawSingleEye(ex, ey, ew, eh, color, pupilPos) {
    const ctx = this.ctx;
    const time = this.t / 1000;

    // Eye Glow
    ctx.shadowBlur = 10;
    ctx.shadowColor = color;
    
    // Outer glass of the eye
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.8;
    ctx.beginPath();
    ctx.roundRect(ex * BLOCK, ey * BLOCK, ew * BLOCK, eh * BLOCK, 4);
    ctx.fill();
    ctx.globalAlpha = 1;

    // Pupil (Retina scanner look)
    if (eh >= 2) {
      let px = (ex + ew / 2) * BLOCK;
      let py = (ey + eh / 2) * BLOCK;
      
      if (pupilPos === 'up-right') { px += BLOCK; py -= BLOCK; }
      
      // Pupil Core
      ctx.shadowBlur = 5;
      ctx.fillStyle = COLORS.face;
      ctx.beginPath();
      ctx.arc(px, py, (BLOCK * 0.8), 0, Math.PI * 2);
      ctx.fill();

      // Laser scan line (futuristic effect)
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.globalAlpha = 0.5;
      const scanY = ey * BLOCK + (Math.sin(time * 5) * 0.5 + 0.5) * (eh * BLOCK);
      ctx.beginPath();
      ctx.moveTo(ex * BLOCK, scanY);
      ctx.lineTo((ex + ew) * BLOCK, scanY);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.shadowBlur = 0;
  }

  _drawXEye(ex, ey, ew, eh, color) {
    const ctx = this.ctx;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.shadowBlur = 15;
    ctx.shadowColor = color;
    
    [-1, 1].forEach(dir => {
      const x = dir * 18;
      const y = -5;
      ctx.beginPath();
      ctx.moveTo(x - 8, y - 8);
      ctx.lineTo(x + 8, y + 8);
      ctx.moveTo(x + 8, y - 8);
      ctx.lineTo(x - 8, y + 8);
      ctx.stroke();
    });
    ctx.shadowBlur = 0;
  }

  _drawHappyEye(ex, ey, ew, eh, color) {
    const ctx = this.ctx;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.shadowBlur = 15;
    ctx.shadowColor = color;

    [-1, 1].forEach(dir => {
      const x = dir * 18;
      const y = -2;
      ctx.beginPath();
      ctx.arc(x, y, 10, Math.PI, 0, false);
      ctx.stroke();
    });
    ctx.shadowBlur = 0;
  }

  _getEyeColor() {
    switch (this.estado) {
      case ESTADOS.DORMINDO:   return COLORS.dim;
      case ESTADOS.ACORDANDO:  return COLORS.dim;
      case ESTADOS.OCIOSO:     return COLORS.primary;
      case ESTADOS.ESCUTANDO:  return COLORS.blue;
      case ESTADOS.PENSANDO:   return COLORS.yellow;
      case ESTADOS.FALANDO:    return COLORS.white;
      case ESTADOS.EXECUTANDO: return COLORS.orange;
      case ESTADOS.ERRO:       return COLORS.red;
      case ESTADOS.SUCESSO:    return COLORS.primary;
      default:                 return COLORS.primary;
    }
  }

  /* ---- Mouth ---- */

  _drawMouth(ctx) {
    const cx = 25 * BLOCK, my = 30 * BLOCK;
    const time = this.t / 1000;
    const color = this._getEyeColor();

    ctx.shadowBlur = 8;
    ctx.shadowColor = color;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;

    switch (this.estado) {
      case ESTADOS.DORMINDO:
        ctx.beginPath();
        ctx.moveTo(cx - 10, my);
        ctx.lineTo(cx + 10, my);
        ctx.stroke();
        break;

      case ESTADOS.OCIOSO:
      case ESTADOS.ACORDANDO:
        // Pulsing Bio-line
        ctx.lineWidth = 2 + Math.sin(time * 3) * 0.5;
        ctx.beginPath();
        ctx.moveTo(cx - 15, my);
        ctx.bezierCurveTo(cx - 5, my + 5, cx + 5, my + 5, cx + 15, my);
        ctx.stroke();
        break;

      case ESTADOS.ESCUTANDO:
        // Waveform mouth
        ctx.beginPath();
        for (let i = -20; i <= 20; i += 2) {
            const wave = Math.sin(time * 10 + i * 0.2) * 4;
            if (i === -20) ctx.moveTo(cx + i, my + wave);
            else ctx.lineTo(cx + i, my + wave);
        }
        ctx.stroke();
        break;

      case ESTADOS.PENSANDO:
        // Loading dots/pulse
        for (let i = -1; i <= 1; i++) {
            const alpha = 0.3 + Math.abs(Math.sin(time * 4 + i)) * 0.7;
            ctx.globalAlpha = alpha;
            ctx.beginPath();
            ctx.arc(cx + i * 12, my, 3, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.globalAlpha = 1;
        break;

      case ESTADOS.EXECUTANDO:
        // Core em sobrecarga de processamento
        ctx.beginPath();
        for (let i = 0; i < 8; i++) {
            const angle = (i / 8) * Math.PI * 2 + time * 10;
            const r = 10 + Math.sin(time * 20) * 5;
            const px = cx + Math.cos(angle) * r;
            const py = my + Math.sin(angle) * r * 0.5;
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.stroke();
        break;

      case ESTADOS.FALANDO: {
        // Dynamic Speech Aperture
        const volume = 5 + Math.abs(Math.sin(time * 15)) * 10;
        ctx.beginPath();
        ctx.ellipse(cx, my, 15, volume, 0, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = COLORS.face;
        ctx.fill();
        break;
      }

      case ESTADOS.SUCESSO:
        ctx.beginPath();
        ctx.moveTo(cx - 18, my - 5);
        ctx.bezierCurveTo(cx - 10, my + 10, cx + 10, my + 10, cx + 18, my - 5);
        ctx.stroke();
        break;
        
      case ESTADOS.ERRO:
        ctx.beginPath();
        ctx.moveTo(cx - 15, my + 5);
        ctx.bezierCurveTo(cx - 5, my - 5, cx + 5, my - 5, cx + 15, my + 5);
        ctx.stroke();
        break;
    }
    ctx.shadowBlur = 0;
  }

  /* ---- Effects ---- */

  _drawEffects(ctx) {
    // Sound waves
    this.soundWaves.forEach(w => {
      ctx.strokeStyle = this.estado === ESTADOS.FALANDO ? COLORS.white : COLORS.blue;
      ctx.globalAlpha = w.opacity;
      ctx.lineWidth = BLOCK;

      if (w.side === 'mouth') {
        const cx = 25 * BLOCK, cy = 31 * BLOCK;
        ctx.beginPath();
        ctx.arc(cx, cy, w.radius * BLOCK, -0.4, 0.4);
        ctx.stroke();
      } else {
        // Both sides of head
        const cy = 22 * BLOCK;
        [-1, 1].forEach(dir => {
          const sx = dir < 0 ? 8 * BLOCK : 42 * BLOCK;
          ctx.beginPath();
          ctx.arc(sx, cy, w.radius * BLOCK,
            dir < 0 ? Math.PI * 0.7 : -Math.PI * 0.3,
            dir < 0 ? Math.PI * 1.3 : Math.PI * 0.3
          );
          ctx.stroke();
        });
      }
      ctx.globalAlpha = 1;
    });

    // Thinking dots
    if (this.estado === ESTADOS.PENSANDO) {
      const dx = 30, dy = 7;
      for (let i = 0; i < this.dots.visible; i++) {
        this._rect(dx + i * 3, dy, 2, 2, COLORS.yellow);
      }
    }

    // Gear for EXECUTANDO
    if (this.estado === ESTADOS.EXECUTANDO) {
      this._drawGear(ctx, 40 * BLOCK, 8 * BLOCK, 10, this.gearAngle);
    }

    // Sleep Zs
    this.sleepZs.forEach(z => {
      ctx.globalAlpha = z.opacity;
      ctx.fillStyle = COLORS.dim;
      ctx.font = `${Math.round(8 + z.size * 10)}px "Press Start 2P", monospace`;
      ctx.fillText('Z', z.x * BLOCK, z.y * BLOCK);
      ctx.globalAlpha = 1;
    });

    // Particles (stars for SUCESSO)
    this.particles.forEach(p => {
      ctx.globalAlpha = p.opacity;
      this._rect(Math.round(p.x), Math.round(p.y), 1, 1, p.color);
      ctx.globalAlpha = 1;
    });
  }

  _drawGear(ctx, cx, cy, radius, angle) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);
    ctx.fillStyle = COLORS.orange;

    const teeth = 6;
    for (let i = 0; i < teeth; i++) {
      const a = (i / teeth) * Math.PI * 2;
      const bx = Math.cos(a) * radius;
      const by = Math.sin(a) * radius;
      ctx.fillRect(bx - BLOCK, by - BLOCK, BLOCK * 2, BLOCK * 2);
    }

    // Center
    ctx.fillRect(-BLOCK * 1.5, -BLOCK * 1.5, BLOCK * 3, BLOCK * 3);
    ctx.fillStyle = COLORS.face;
    ctx.fillRect(-BLOCK * 0.5, -BLOCK * 0.5, BLOCK, BLOCK);

    ctx.restore();
  }

  /* ---- Particles ---- */

  _spawnStars(count) {
    const cx = 25, cy = 22;
    for (let i = 0; i < count; i++) {
      const angle = (i / count) * Math.PI * 2 + Math.random() * 0.5;
      const speed = 0.5 + Math.random() * 1.5;
      this.particles.push({
        x: cx, y: cy,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 600 + Math.random() * 400,
        maxLife: 1000,
        opacity: 1,
        color: [COLORS.primary, COLORS.yellow, COLORS.white][Math.floor(Math.random() * 3)],
      });
    }
  }

  /* ---- Helpers ---- */

  _randomBlink() {
    return 2000 + Math.random() * 3000;
  }
}
