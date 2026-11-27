/* MaestroCore 网页版节拍器引擎（Web Audio API，不依赖任何库）
 *
 * 为什么不用 setInterval 直接发声：浏览器定时器会被卡顿，节奏会抖。
 * 这里用「预排」——每 25ms 看一眼未来 120ms，把拍点提前排进音频时钟，
 * 声音就稳了，跟专业节拍器一个思路。
 *
 * 对外：
 *   const m = MC.createMetronome({ onBeat, onSegment })
 *   m.start() / m.pause() / m.resume() / m.stop()
 *   m.setBpm(n) / m.setMeter('4/4') / m.tap()
 *   m.loadPlan(plan)          plan: [{start_measure,end_measure,bpm,beats,beat_type}]
 *   m.follow = true           跟随谱面：到段末自动换速度/拍号
 */
(function () {
  "use strict";

  const MC = (window.MC = window.MC || {});
  const MIN_BPM = 40, MAX_BPM = 208;

  const SOUNDS = {
    wood: { type: "square", freq: 900, dur: 0.045, gain: 0.9, lp: 2600 },   // 木鱼感：方波短促
    beep: { type: "sine", freq: 1180, dur: 0.075, gain: 0.85 },             // 电子滴
    mech: { type: "triangle", freq: 520, dur: 0.03, gain: 0.95, lp: 4200 }, // 机械咔哒
    strings: { type: "triangle", freq: 660, dur: 0.11, gain: 0.8 },         // 拨弦感
  };

  function parseMeter(text) {
    const m = /^(\d+)\/(\d+)$/.exec((text || "4/4").trim());
    if (!m) return { beats: 4, beatType: 4 };
    return { beats: parseInt(m[1], 10) || 4, beatType: parseInt(m[2], 10) || 4 };
  }

  MC.createMetronome = function (opts) {
    const options = opts || {};
    const state = {
      bpm: 100,
      beats: 4,
      beatType: 4,
      volume: 0.8,
      sound: true,
      accent: true,
      accentSound: "wood",
      weakSound: "beep",
      follow: false,
      plan: [],
      planIndex: 0,
      measure: 1,
      beatInBar: 0,
      running: false,
      paused: false,
      meterMap: {},     // 变拍表：{小节号: {beats, beatType}}
      fermata: {},      // 无限延长：{小节号: 多加几拍}
    };

    let ctx = null, master = null, timer = null;
    let nextNoteTime = 0;
    let beatSerial = 0;
    const lookahead = 0.12;      // 往后排 120ms
    const tickMs = 25;

    function ensureCtx() {
      if (ctx) return ctx;
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      master = ctx.createGain();
      master.gain.value = state.volume;
      master.connect(ctx.destination);
      return ctx;
    }

    /* ---------------- 发声 ---------------- */
    function scheduleClick(time, accent) {
      if (!state.sound) return;
      ensureCtx();
      const spec = SOUNDS[accent ? state.accentSound : state.weakSound] || SOUNDS.beep;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = spec.type;
      osc.frequency.value = accent ? spec.freq : spec.freq * 0.72;

      const peak = (accent ? 1.0 : 0.55) * spec.gain;
      gain.gain.setValueAtTime(0.0001, time);
      gain.gain.exponentialRampToValueAtTime(peak, time + 0.004);
      gain.gain.exponentialRampToValueAtTime(0.0001, time + spec.dur);

      let node = osc;
      if (spec.lp) {
        const lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.value = spec.lp;
        osc.connect(lp);
        node = lp;
      }
      node.connect(gain);
      gain.connect(master);
      osc.start(time);
      osc.stop(time + spec.dur + 0.01);
    }

    /* ---------------- 排下一拍 ---------------- */
    function beatsFor(measure) {
      // 变拍表按小节给拍数；无限延长的小节额外多加几拍
      const extra = Number(state.fermata[measure] || 0);
      return Math.max(1, Number(state.beats) + (isFinite(extra) ? extra : 0));
    }

    function applyMeterFor(measure) {
      const m = state.meterMap[measure];
      if (!m) return;
      if (m.beats) state.beats = Number(m.beats);
      if (m.beatType) state.beatType = Number(m.beatType);
    }

    function scheduleBeat() {
      const interval = 60 / state.bpm;
      const accent = state.beatInBar === 0 && state.accent;

      // 视觉与回调：用音频时间换算成“差不多现在”，够用
      const when = nextNoteTime;
      const beatNo = state.beatInBar + 1;
      const measureNo = state.measure;
      const beatsNow = beatsFor(measureNo);
      const bpmNow = state.bpm;

      scheduleClick(when, accent);

      const delay = Math.max(0, (when - ctx.currentTime) * 1000);
      setTimeout(() => {
        if (options.onBeat) options.onBeat({
          measure: measureNo, beat: beatNo, beats: beatsNow,
          bpm: bpmNow, beatType: state.beatType, accent,
          fermata: Number(state.fermata[measureNo] || 0),
        });
      }, delay);

      nextNoteTime += interval;
      beatSerial++;

      state.beatInBar++;
      if (state.beatInBar >= beatsNow) {
        state.beatInBar = 0;
        state.measure++;
        applyMeterFor(state.measure);
        advancePlan();
      }
    }

    function advancePlan() {
      if (!state.follow || !state.plan.length) return;
      const seg = state.plan[state.planIndex];
      const segEnd = Number(seg.end_measure || seg.start_measure);

      if (state.measure >= segEnd && state.planIndex + 1 < state.plan.length) {
        state.planIndex++;
        applySegment();
        if (options.onSegment) {
          setTimeout(() => options.onSegment({
            index: state.planIndex, total: state.plan.length,
            segment: state.plan[state.planIndex], measure: state.measure,
          }), 0);
        }
      }
    }

    function applySegment() {
      const seg = state.plan[state.planIndex] || {};
      if (seg.bpm) state.bpm = clamp(Number(seg.bpm), MIN_BPM, MAX_BPM);
      if (seg.beats) state.beats = Number(seg.beats);
      if (seg.beat_type) state.beatType = Number(seg.beat_type);
      // 手填的变拍表优先：这一段里有变拍，就按变拍表的拍数走
      applyMeterFor(state.measure);
    }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, Math.round(v))); }

    /* ---------------- 主循环 ---------------- */
    function loop() {
      if (!ctx) return;
      while (nextNoteTime < ctx.currentTime + lookahead) {
        scheduleBeat();
      }
    }

    /* ---------------- 对外 ---------------- */
    const api = {
      state,

      start() {
        ensureCtx();
        if (ctx.state === "suspended") ctx.resume();
        if (state.running && !state.paused) return;
        state.running = true;
        state.paused = false;
        state.beatInBar = 0;
        if (state.follow && state.plan.length) {
          state.planIndex = 0;
          state.measure = Number(state.plan[0].start_measure) || 1;
          applySegment();
        }
        applyMeterFor(state.measure);
        nextNoteTime = ctx.currentTime + 0.06;
        clearInterval(timer);
        timer = setInterval(loop, tickMs);
        loop();
      },

      pause() {
        if (!state.running) return;
        state.paused = true;
        clearInterval(timer);
        timer = null;
      },

      resume() {
        if (!state.running || !state.paused) return;
        ensureCtx();
        state.paused = false;
        nextNoteTime = ctx.currentTime + 0.06;
        clearInterval(timer);
        timer = setInterval(loop, tickMs);
      },

      stop() {
        state.running = false;
        state.paused = false;
        clearInterval(timer);
        timer = null;
        master = null;
        if (ctx) {
          try { ctx.close(); } catch (_) { /* ignore */ }
          ctx = null;
        }
      },

      toggle() {
        if (!state.running) this.start();
        else if (state.paused) this.resume();
        else this.pause();
      },

      get running() { return state.running && !state.paused; },

      setBpm(v) { state.bpm = clamp(Number(v) || 100, MIN_BPM, MAX_BPM); },

      setMeter(text) {
        const { beats, beatType } = parseMeter(text);
        state.beats = beats;
        state.beatType = beatType;
        state.beatInBar = 0;
      },

      setVolume(v) {
        state.volume = Math.max(0, Math.min(1, Number(v)));
        if (master) master.gain.value = state.volume;
      },

      tap() {
        const now = performance.now() / 1000;
        taps = taps.filter((t) => now - t < 3).concat(now);
        if (taps.length >= 2) {
          const gaps = taps.slice(1).map((t, i) => t - taps[i]);
          const avg = gaps.reduce((a, b) => a + b, 0) / gaps.length;
          if (avg > 0) api.setBpm(clamp(60 / avg, MIN_BPM, MAX_BPM));
        }
        return state.bpm;
      },

      loadPlan(plan, { follow } = {}) {
        state.plan = (plan || []).slice().sort((a, b) => (a.start_measure || 0) - (b.start_measure || 0));
        state.planIndex = 0;
        if (typeof follow === "boolean") state.follow = follow;
      },

      /** 变拍表：{小节号: {beats, beatType}}；无限延长：{小节号: 额外拍数} */
      setMeterMap(map) {
        state.meterMap = map || {};
      },
      setFermata(map) {
        state.fermata = map || {};
      },

      /** 解析「2:3/4, 5:2/4」这种手填的变拍表 */
      parseMeterMap(text) {
        const map = {};
        String(text || "").split(/[,，;；]/).forEach((chunk) => {
          const m = chunk.trim().match(/(\d+)\s*[:：]\s*(\d+)\s*\/\s*(\d+)/);
          if (m) map[Number(m[1])] = { beats: Number(m[2]), beatType: Number(m[3]) };
        });
        return map;
      },

      /** 解析「3, 152」这种小节列表 */
      parseMeasureList(text) {
        const out = [];
        String(text || "").split(/[,，;；\s]+/).forEach((chunk) => {
          const m = chunk.trim().match(/\d+/);
          if (m) out.push(Number(m[0]));
        });
        return out;
      },

      /** 用 ai_result.json 里的摘要拼出分段：优先 metronome_plan，其次 tempo_map + time_map */
      planFromPayload(payload) {
        if (!payload) return [];
        const ai = payload.ai || {};
        const summary = payload.summary || {};
        if (ai.metronome_plan && ai.metronome_plan.length) {
          return ai.metronome_plan.map((p) => ({
            start_measure: p.start_measure, end_measure: p.end_measure,
            bpm: p.bpm, beats: p.beats || 4, beat_type: p.beat_type || 4,
          }));
        }
        const tempos = summary.tempo_map || [];
        const times = summary.time_map || [];
        const total = summary.total_measures || 1;
        return tempos.map((t, i) => {
          const end = i + 1 < tempos.length ? tempos[i + 1].measure - 1 : total;
          let beats = 4, beatType = 4;
          times.forEach((ts) => { if (ts.measure <= t.measure) { beats = ts.beats; beatType = ts.beat_type; } });
          return { start_measure: t.measure, end_measure: end, bpm: Math.round(t.bpm), beats, beat_type: beatType };
        });
      },
    };

    let taps = [];
    return api;
  };
})();
