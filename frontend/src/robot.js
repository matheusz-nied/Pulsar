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
  bg:      '#0a0a0a',
  dim:     '#2a2a2a',
  primary: '#00ff88',
  blue:    '#00aaff',
  yellow:  '#ffaa00',
  orange:  '#ff6600',
  red:     '#ff0000',
  white:   '#ffffff',
  face:    '#141428',
  outline: '#1e1e3a',
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

    this._running = true;
    this._raf = requestAnimationFrame((ts) => this._loop(ts));
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
        break;
      case ESTADOS.ACORDANDO:
        this.eyeOpenness = 0;
        this.targetEyeOpenness = 1;
        break;
      case ESTADOS.SUCESSO:
        this._spawnStars(12);
        break;
      case ESTADOS.ERRO:
        this.shakeX = 8;
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

    ctx.save();
    ctx.translate(this.headOffsetX * BLOCK, this.headOffsetY * BLOCK);

    this._drawFace(ctx);
    this._drawEyes(ctx);
    this._drawMouth(ctx);

    ctx.restore();

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
    // Head outline (rounded rect in pixel blocks)
    const x = 8, y = 10, w = 34, h = 28;
    this._rect(x + 1, y, w - 2, h, COLORS.outline);
    this._rect(x, y + 1, w, h - 2, COLORS.outline);

    // Face fill
    this._rect(x + 2, y + 1, w - 4, h - 2, COLORS.face);
    this._rect(x + 1, y + 2, w - 2, h - 4, COLORS.face);

    // Antenna
    const antX = 25;
    this._rect(antX, y - 4, 1, 4, COLORS.outline);

    // Antenna tip glow
    const glowColor = this._getEyeColor();
    this._px(antX - 1, y - 5, glowColor);
    this._px(antX, y - 5, glowColor);
    this._px(antX + 1, y - 5, glowColor);
    this._px(antX, y - 6, glowColor);

    // Cheek accents
    if (this.estado === ESTADOS.SUCESSO || this.estado === ESTADOS.ESCUTANDO) {
      ctx.globalAlpha = 0.15;
      this._rect(11, 27, 4, 2, '#ff6688');
      this._rect(35, 27, 4, 2, '#ff6688');
      ctx.globalAlpha = 1;
    }
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
    // Eye background
    this._rect(ex, ey, ew, eh, color);

    // Pupil
    if (eh >= 2) {
      let px = ex + Math.floor(ew / 2) - 1;
      let py = ey + Math.floor(eh / 2);
      const ps = this.estado === ESTADOS.ESCUTANDO ? 3 : 2;

      if (pupilPos === 'up-right') { px += 1; py -= 1; }

      this._rect(px, py - 1, ps, ps, COLORS.face);

      // Highlight
      this._px(px, py - 1, COLORS.white);
    }
  }

  _drawXEye(ex, ey, ew, eh, color) {
    const cx = ex + Math.floor(ew / 2);
    const cy = ey + Math.floor(eh / 2);
    for (let i = -2; i <= 2; i++) {
      this._px(cx + i, cy + i, color);
      this._px(cx + i, cy - i, color);
    }
  }

  _drawHappyEye(ex, ey, ew, eh, color) {
    const w = ew;
    const baseY = ey + 1;
    for (let i = 0; i < w; i++) {
      const curve = (i === 0 || i === w - 1) ? 0 : (i === 1 || i === w - 2) ? -1 : -2;
      this._px(ex + i, baseY - curve, color);
      if (curve < -1) this._px(ex + i, baseY - curve + 1, color);
    }
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
    const cx = 25, my = 30;

    switch (this.estado) {
      case ESTADOS.DORMINDO:
        this._rect(cx - 2, my, 5, 1, COLORS.dim);
        break;

      case ESTADOS.OCIOSO:
      case ESTADOS.ACORDANDO:
        // Slight smile
        this._rect(cx - 3, my, 7, 1, COLORS.primary);
        this._px(cx - 4, my - 1, COLORS.primary);
        this._px(cx + 4, my - 1, COLORS.primary);
        break;

      case ESTADOS.ESCUTANDO:
        // Slightly open
        this._rect(cx - 2, my, 5, 1, COLORS.blue);
        this._rect(cx - 1, my + 1, 3, 1, COLORS.blue);
        break;

      case ESTADOS.PENSANDO:
        // Wavy / skeptical
        for (let i = -3; i <= 3; i++) {
          const wave = Math.round(Math.sin(i * 1.5) * 0.6);
          this._px(cx + i, my + wave, COLORS.yellow);
        }
        break;

      case ESTADOS.FALANDO: {
        // Animated open/close: 0=closed, 1=half, 2=open, 3=half
        const openings = [1, 2, 3, 2];
        const mh = openings[this.mouthFrame];
        this._rect(cx - 3, my, 7, 1, COLORS.white);
        if (mh >= 2) this._rect(cx - 2, my + 1, 5, 1, COLORS.white);
        if (mh >= 3) this._rect(cx - 1, my + 2, 3, 1, COLORS.white);
        // Inner mouth darkness
        if (mh >= 2) this._rect(cx - 1, my + 1, 3, Math.min(mh - 1, 2), COLORS.face);
        break;
      }

      case ESTADOS.EXECUTANDO:
        // Concentrated straight line
        this._rect(cx - 3, my, 7, 1, COLORS.orange);
        break;

      case ESTADOS.ERRO:
        // Frown
        this._rect(cx - 3, my + 1, 7, 1, COLORS.red);
        this._px(cx - 4, my, COLORS.red);
        this._px(cx + 4, my, COLORS.red);
        break;

      case ESTADOS.SUCESSO:
        // Big smile
        this._rect(cx - 4, my, 9, 1, COLORS.primary);
        this._px(cx - 5, my - 1, COLORS.primary);
        this._px(cx + 5, my - 1, COLORS.primary);
        this._px(cx - 5, my - 2, COLORS.primary);
        this._px(cx + 5, my - 2, COLORS.primary);
        break;
    }
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
