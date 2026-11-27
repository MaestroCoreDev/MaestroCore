/* MaestroCore 灵动岛（全站共用一份）
 *
 * 用法：页面里 <script src="assets/island.js"></script>，脚本自己插 DOM。
 * 对外：
 *   MC.island.getBpm() / setBpm(n)
 *   MC.island.getMeter() / setMeter('4/4')
 *   MC.island.setRunning(bool)          运行时呼吸那个小点
 *   MC.island.setMeasure(text)         练习模式显示「第 N 小节」，传空就隐藏
 *   MC.island.onBpm(cb) / onMeter(cb)   数值变化回调（节拍器用它）
 */
(function () {
  "use strict";

  const LS = {
    bpm: "mc.bpm",
    meter: "mc.meter",
    glass: "mc.glass",
    anim: "mc.anim",
  };

  const METERS = ["2/4", "3/4", "4/4", "3/8", "6/8", "9/8", "12/8"];
  const MIN_BPM = 40, MAX_BPM = 208;

  const state = {
    bpm: clamp(parseInt(localStorage.getItem(LS.bpm) || "100", 10) || 100, MIN_BPM, MAX_BPM),
    meter: localStorage.getItem(LS.meter) || "4/4",
    glass: localStorage.getItem(LS.glass) || "frosted",
    anim: localStorage.getItem(LS.anim) !== "off",
  };
  const bpmSubs = [];
  const meterSubs = [];
  const playSubs = [];
  state.playing = false;

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  /* ---------------- 液态玻璃用的位移滤镜 ---------------- */
  function injectFilter() {
    if (document.getElementById("mc-liquid-filter")) return;
    const holder = document.createElement("div");
    holder.innerHTML = `
      <svg id="mc-liquid-filter" width="0" height="0" aria-hidden="true" style="position:absolute">
        <filter id="mc-liquid" x="-20%" y="-20%" width="140%" height="140%">
          <feTurbulence type="fractalNoise" baseFrequency="0.006 0.014"
                        numOctaves="2" seed="7" result="noise"/>
          <feGaussianBlur in="noise" stdDeviation="1.2" result="soft"/>
          <feDisplacementMap in="SourceGraphic" in2="soft" scale="14"
                             xChannelSelector="R" yChannelSelector="G"/>
        </filter>
      </svg>`;
    document.body.appendChild(holder.firstElementChild);
  }

  /* ---------------- DOM ---------------- */
  function build() {
    const el = document.createElement("div");
    el.className = "island";
    el.id = "mc-island";
    el.innerHTML = `
      <div class="play" title="开始 / 暂停">
        <svg class="ico-play" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5l12 7-12 7z"/></svg>
        <svg class="ico-pause" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="5" width="3.4" height="14"/><rect x="13.6" y="5" width="3.4" height="14"/></svg>
      </div>
      <div class="meter" title="点击切换拍号">
        <span class="m-text"></span><span class="caret">▾</span>
        <div class="meter-pop"></div>
      </div>
      <div class="step minus" title="减慢（长按连续减）">−</div>
      <div class="bpm-wrap">
        <div class="bpm"><span class="num"></span><small>BPM</small></div>
      </div>
      <div class="step plus" title="加快（长按连续加）">+</div>
      <div class="gear" title="节拍器设置">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.2a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.54 15a1.7 1.7 0 0 0-1.56-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.8 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.54a1.7 1.7 0 0 0 1-1.56V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.46 9c.14.35.5.66 1.56 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1z"/>
        </svg>
      </div>
    `;

    // 拍号小面板
    const pop = el.querySelector(".meter-pop");
    pop.onclick = (e) => e.stopPropagation();
    METERS.forEach((m) => {
      const b = document.createElement("button");
      b.textContent = m;
      b.onclick = () => { setMeter(m); pop.classList.remove("open"); };
      pop.appendChild(b);
    });

    el.querySelector(".meter").onclick = (e) => {
      e.stopPropagation();
      pop.classList.toggle("open");      el.querySelectorAll(".meter-pop button").forEach((b) => {
        b.classList.toggle("on", b.textContent === state.meter);
      });
    };
    document.addEventListener("click", (e) => {
      if (!el.contains(e.target)) pop.classList.remove("open");
    });

    el.querySelector(".minus").title = "减慢（长按连续减）";
    el.querySelector(".plus").title = "加快（长按连续加）";
    holdStep(el.querySelector(".minus"), -1);
    holdStep(el.querySelector(".plus"), +1);

    // 播放键：节拍器页面就控制引擎，其它页面直接跳过去
    el.querySelector(".play").onclick = (e) => {
      e.stopPropagation();
      if (playSubs.length) {
        playSubs.forEach((cb) => cb(!state.playing));
      } else {
        location.href = "metronome.html";
      }
    };

    // 点数字只负责看，不再变输入框

    el.querySelector(".gear").onclick = (e) => {
      e.stopPropagation();
      let href = "metronome.html#metro-settings";
      if (window.MC_PREVIEW) {
        if (MC.savePreviewState) MC.savePreviewState();
        href = MC.previewHrefTheme
          ? MC.previewHrefTheme(href)
          : "metronome.html?t=" + encodeURIComponent(localStorage.getItem("mc.theme") || "默认") + "#metro-settings";
      }
      location.href = href;
    };

    document.body.appendChild(el);
    applyGlass();
    render();
    return el;
  }

  function editNumber(el) {
    const wrap = el.querySelector(".bpm-wrap");
    if (wrap.querySelector("input")) return;
    const show = wrap.querySelector(".bpm");
    const input = document.createElement("input");
    input.type = "number";
    input.className = "bpm-input";
    input.min = MIN_BPM; input.max = MAX_BPM;
    input.value = state.bpm;
    show.style.visibility = "hidden";
    wrap.appendChild(input);
    input.focus();
    input.select();

    const finish = (commit) => {
      if (commit) {
        const v = parseInt(input.value, 10);
        if (!isNaN(v)) setBpm(v);
      }
      input.remove();
      show.style.visibility = "";
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    };
    input.onblur = () => finish(true);
  }

  /* 加减键：按下立刻走一格；按住 0.3 秒才开始连发（85ms → 38ms）。
     抬手用 window 捕获 + 鼠标按键位双重兜底，松手绝不会继续加。 */
  let holding = false;
  function holdStep(el, delta) {
    let delayTimer = null;
    let repeatTimer = null;
    let alive = false;
    let speed = 85;

    const step = () => setBpm(state.bpm + delta);

    const stop = () => {
      alive = false;
      holding = false;   // 松手后恢复单点动画
      clearTimeout(delayTimer);
      clearTimeout(repeatTimer);
      delayTimer = null;
      repeatTimer = null;
    };

    const loop = () => {
      if (!alive) return;
      step();
      speed = Math.max(38, speed - 4);
      repeatTimer = setTimeout(loop, speed);
    };

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      e.preventDefault();
      stop();
      step();               // 单击只加这一格，后面没有第二次点击回调
      speed = 85;
      delayTimer = setTimeout(() => {
        alive = true;
        holding = true;     // 进入连发：数字不再做任何动画，只安静地变
        loop();
      }, 300);
    });

    // 抬手的三重保险：窗口捕获、document、鼠标移动时检查按键是否已松开
    window.addEventListener("pointerup", stop, true);
    document.addEventListener("mouseup", stop, true);
    window.addEventListener("pointercancel", stop, true);
    window.addEventListener("blur", stop);
    document.addEventListener("pointermove", (ev) => {
      if (alive && ev.buttons === 0) stop();
    }, true);
    el.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  /* ---------------- 渲染 ---------------- */
  function render() {
    const el = document.getElementById("mc-island");
    if (!el) return;
    el.querySelector(".num").textContent = state.bpm;
    el.querySelector(".m-text").textContent = state.meter;
  }

  let bumpTimer = null;
  let lastBump = 0;
  function bump() {
    const el = document.getElementById("mc-island");
    if (!el || !state.anim) return;
    // 长按连发时不闪不跳：数字只安静地滚动，否则 26ms 一次动画会糊成一片
    if (holding) return;
    // 两次动画之间至少隔 200ms，快速点击也不会连闪
    const now = Date.now();
    if (now - lastBump < 200) return;
    lastBump = now;
    const bpmEl = el.querySelector(".bpm");
    // 每次都要重新起一次动画：只加 class 不动，长按连发时数字会“卡住不跳”
    bpmEl.classList.remove("bump");
    void bpmEl.offsetWidth;
    bpmEl.classList.add("bump");
    clearTimeout(bumpTimer);
    bumpTimer = setTimeout(() => bpmEl.classList.remove("bump"), 220);
  }

  /* ---------------- 对外设置 ---------------- */
  function setBpm(v, silent) {
    v = clamp(Math.round(v), MIN_BPM, MAX_BPM);
    if (v === state.bpm) return state.bpm;
    state.bpm = v;
    localStorage.setItem(LS.bpm, String(v));
    render();
    bump();
    if (!silent) bpmSubs.forEach((cb) => cb(v));
    return v;
  }

  function setMeter(m, silent) {
    if (!METERS.includes(m)) return state.meter;
    state.meter = m;
    localStorage.setItem(LS.meter, m);
    render();
    if (!silent) meterSubs.forEach((cb) => cb(m));
    return m;
  }

  function applyGlass() {
    const el = document.getElementById("mc-island");
    const kind = ["none", "frosted", "liquid"].includes(state.glass) ? state.glass : "frosted";
    document.documentElement.setAttribute("data-glass", kind);
    if (!el) return;
    el.classList.remove("glass-none", "glass-frosted", "glass-liquid");
    el.classList.add("glass-" + kind);
    el.classList.toggle("anim-on", state.anim);
  }

  function setGlass(kind) {
    state.glass = kind;
    localStorage.setItem(LS.glass, kind);
    applyGlass();
  }

  function setAnim(on) {
    state.anim = !!on;
    localStorage.setItem(LS.anim, on ? "on" : "off");
    applyGlass();
  }

  function setRunning(on) {
    const el = document.getElementById("mc-island");
    if (el) el.classList.toggle("running", !!on);
  }

  function setPlaying(on) {
    state.playing = !!on;
    const el = document.getElementById("mc-island");
    if (!el) return;
    el.classList.toggle("playing", state.playing);
    const play = el.querySelector(".ico-play");
    const pause = el.querySelector(".ico-pause");
    if (play && pause) {
      play.style.display = state.playing ? "none" : "";
      pause.style.display = state.playing ? "" : "none";
    }
  }

  function setMeasure(text) {
    const el = document.getElementById("mc-island");
    if (!el) return;
    let tag = el.querySelector(".measure-tag");
    if (!text) {
      if (tag) tag.remove();
      return;
    }
    if (!tag) {
      tag = document.createElement("div");
      tag.className = "measure-tag chip";
      tag.style.cssText = "font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(255,255,255,.6)";
      el.insertBefore(tag, el.querySelector(".gear"));
    }
    tag.textContent = text;
  }

  /* ---------------- 全局节拍器：非节拍器页也能直接点响 ---------------- */
  function bootMetronome() {
    if (document.body.dataset.page === "metronome") return; // 那一页有自己的引擎
    if (!window.MC || !window.MC.createMetronome) return;
    const m = window.MC.createMetronome({});
    const get = (k, d) => localStorage.getItem(k) || d;
    m.state.sound = get("mc.sound", "on") !== "off";
    m.state.accent = get("mc.accent", "on") !== "off";
    m.state.accentSound = get("mc.accentSound", "wood");
    m.state.weakSound = get("mc.weakSound", "beep");
    const raw = localStorage.getItem("mc.volume");
    const vol = raw === null ? 0.8 : (parseFloat(raw) > 1 ? parseFloat(raw) / 100 : parseFloat(raw));
    m.setVolume(vol);
    m.setBpm(state.bpm);
    m.setMeter(state.meter);

    bpmSubs.push((v) => m.setBpm(v));
    meterSubs.push((x) => m.setMeter(x));
    playSubs.push(() => {
      m.toggle();
      setPlaying(m.running);
      setRunning(m.running);
    });
    window.addEventListener("mc-sound-change", (e) => {
      const d = e.detail || {};
      m.state.sound = d.sound;
      m.state.accent = d.accent;
      m.state.accentSound = d.accentSound;
      m.state.weakSound = d.weakSound;
      m.setVolume(d.volume);
    });
  }

  /* ---------------- 初始化 ---------------- */
  function boot() {
    injectFilter();
    build();
    applyGlass();          // 进页面就先按存着的档位刷一遍，别等用户去设置页点一次才生效
    bootMetronome();
    document.documentElement.classList.add("mc-island-ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.MC = window.MC || {};
  window.MC.island = {
    getBpm: () => state.bpm,
    setBpm,
    getMeter: () => state.meter,
    setMeter,
    setRunning,
    setPlaying,
    onPlay: (cb) => playSubs.push(cb),
    getPlaying: () => state.playing,
    setMeasure,
    setGlass,
    setAnim,
    getGlass: () => state.glass,
    getAnim: () => state.anim,
    onBpm: (cb) => bpmSubs.push(cb),
    onMeter: (cb) => meterSubs.push(cb),
  };
})();

