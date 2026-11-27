/* 节拍器页底部的「节拍器设置」 */
(function () {
  "use strict";
  const MC = (window.MC = window.MC || {});

  const KEY = {
    sound: "mc.sound",
    accent: "mc.accent",
    accentSound: "mc.accentSound",
    weakSound: "mc.weakSound",
    volume: "mc.volume",
    meterMap: "mc.meterMap",
    fermataMeasures: "mc.fermataMeasures",
    fermataBeats: "mc.fermataBeats",
  };
  const LABELS = { wood: "木鱼", beep: "电子滴", mech: "机械咔哒", strings: "拨弦" };

  const S = {
    sound: localStorage.getItem(KEY.sound) !== "off",
    accent: localStorage.getItem(KEY.accent) !== "off",
    accentSound: localStorage.getItem(KEY.accentSound) || "wood",
    weakSound: localStorage.getItem(KEY.weakSound) || "beep",
    volume: parseInt(localStorage.getItem(KEY.volume) || "80", 10),
  };

  function broadcast() {
    window.dispatchEvent(new CustomEvent("mc-sound-change", {
      detail: {
        sound: S.sound,
        accent: S.accent,
        accentSound: S.accentSound,
        weakSound: S.weakSound,
        volume: S.volume / 100,
      },
    }));
  }

  function bindSwitch(id, value, onChange) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle("on", !!value);
    el.onclick = () => {
      const next = !el.classList.contains("on");
      el.classList.toggle("on", next);
      onChange(next);
    };
  }

  function selectButtons(hostId, current, onPick) {
    const host = document.getElementById(hostId);
    if (!host) return;
    host.innerHTML = "";
    Object.entries(LABELS).forEach(([val, label]) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.className = val === current ? "on" : "";
      b.onclick = () => {
        host.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        onPick(val);
      };
      host.appendChild(b);
    });
  }

  function preview(kind, accent) {
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC();
    const spec = { wood: [900, 2600], beep: [1180], mech: [520, 4200], strings: [660] }[kind] || [900];
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = kind === "strings" ? "triangle" : (kind === "beep" ? "sine" : "square");
    osc.frequency.value = accent ? spec[0] : spec[0] * 0.72;
    const dur = kind === "strings" ? 0.12 : 0.06;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, S.volume / 100), ctx.currentTime + 0.004);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + dur);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + dur + 0.02);
    setTimeout(() => ctx.close(), 400);
  }

  function boot() {
    bindSwitch("sw-sound", S.sound, (v) => {
      S.sound = v;
      localStorage.setItem(KEY.sound, v ? "on" : "off");
      broadcast();
    });

    /* ---- 变拍表 / 无限延长 ----
       这几个值直接存 localStorage，节拍器播放时按小节号查表改变每小节拍数。 */
    const mm = document.getElementById("meter-map");
    const mmTip = document.getElementById("meter-map-tip");
    const mmBtn = document.getElementById("meter-map-apply");
    const fm = document.getElementById("fermata-measures");
    const fb = document.getElementById("fermata-beats");
    const fmTip = document.getElementById("fermata-tip");
    const fmBtn = document.getElementById("fermata-apply");

    function meterSummary(text) {
      const map = MC.metro && MC.metro.parseMeterMap ? MC.metro.parseMeterMap(text)
        : {"_": 0};
      const keys = Object.keys(map).filter((k) => k !== "_");
      if (!keys.length) return "按 4/4";
      return keys.map((k) => `第${k}小节起 ${map[k].beats}/${map[k].beatType}`).join("，");
    }

    function applyMeter() {
      const text = (mm.value || "").trim();
      localStorage.setItem(KEY.meterMap, text);
      if (mmTip) mmTip.textContent = meterSummary(text);
      window.dispatchEvent(new CustomEvent("mc-meter-change", { detail: { text } }));
    }

    function applyFermata() {
      const measures = (fm.value || "").trim();
      const beats = String(Math.max(0, parseInt(fb.value || "0", 10)));
      localStorage.setItem(KEY.fermataMeasures, measures);
      localStorage.setItem(KEY.fermataBeats, beats);
      if (fmTip) {
        fmTip.textContent = measures ? `延长小节：${measures}，每个多算 ${beats} 拍` : "没有延长";
      }
      window.dispatchEvent(new CustomEvent("mc-fermata-change", { detail: { measures, beats } }));
    }

    if (mm) {
      mm.value = localStorage.getItem(KEY.meterMap) || "";
      if (mmTip) mmTip.textContent = meterSummary(mm.value);
      if (mmBtn) mmBtn.onclick = applyMeter;
      mm.addEventListener("keydown", (e) => { if (e.key === "Enter") applyMeter(); });
    }
    if (fm) {
      fm.value = localStorage.getItem(KEY.fermataMeasures) || "";
      if (fb) fb.value = localStorage.getItem(KEY.fermataBeats) || "2";
      if (fmTip) {
        fmTip.textContent = fm.value ? `延长小节：${fm.value}，每个多算 ${fb.value} 拍` : "没有延长";
      }
      if (fmBtn) fmBtn.onclick = applyFermata;
      fm.addEventListener("keydown", (e) => { if (e.key === "Enter") applyFermata(); });
    }
    bindSwitch("sw-accent", S.accent, (v) => {
      S.accent = v;
      localStorage.setItem(KEY.accent, v ? "on" : "off");
      broadcast();
    });

    selectButtons("accent-sounds", S.accentSound, (v) => {
      S.accentSound = v;
      localStorage.setItem(KEY.accentSound, v);
      broadcast();
      preview(v, true);
    });
    selectButtons("weak-sounds", S.weakSound, (v) => {
      S.weakSound = v;
      localStorage.setItem(KEY.weakSound, v);
      broadcast();
      preview(v, false);
    });

    const vol = document.getElementById("volume");
    const val = document.getElementById("volume-val");
    if (vol) {
      vol.value = S.volume;
      if (val) val.textContent = S.volume + "%";
      vol.oninput = () => {
        S.volume = parseInt(vol.value, 10);
        if (val) val.textContent = S.volume + "%";
        localStorage.setItem(KEY.volume, String(S.volume));
        broadcast();
      };
    }
    const pv = document.getElementById("preview");
    if (pv) pv.onclick = () => preview(S.accentSound, true);

    // 只改了外观/主题的那一页，别把这里的开关当成全局设置
    broadcast();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
