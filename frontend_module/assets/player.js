/* 节拍器页面逻辑：把灵动岛、引擎、练习方案接起来 */
(function () {
  "use strict";
  const MC = (window.MC = window.MC || {});

  const S = {
    sound: localStorage.getItem("mc.sound") !== "off",
    accent: localStorage.getItem("mc.accent") !== "off",
    accentSound: localStorage.getItem("mc.accentSound") || "wood",
    weakSound: localStorage.getItem("mc.weakSound") || "beep",
    // 设置页存的是 0-100 的整数，引擎要 0-1
    volume: (() => {
      const raw = localStorage.getItem("mc.volume");
      if (raw === null) return 0.8;
      const n = parseFloat(raw);
      return Number.isFinite(n) && n > 1 ? n / 100 : n;
    })(),
  };

  function boot() {
    const island = MC.island;
    const dots = document.getElementById("dots");
    const nowBpm = document.getElementById("now-bpm");
    const nowMeasure = document.getElementById("now-measure");
    const segInfo = document.getElementById("seg-info");
    const planList = document.getElementById("plan-list");
    const planChip = document.getElementById("plan-chip");
    const toggleBtn = document.getElementById("toggle");
    const followBox = document.getElementById("follow");

    const metro = MC.createMetronome({
      onBeat(ev) {
        nowBpm.textContent = metro.state.bpm;   // 一律以引擎当前速度为真，别用排拍时抓的旧值
        nowMeasure.textContent = metro.state.follow
          ? "第 " + ev.measure + " 小节"
          : (title ? title : "自由练习");
        drawDots(ev.beats, ev.beat, ev.accent);
        island.setMeasure(metro.state.follow ? "第 " + ev.measure + " 小节" : "");
        syncIsland();                                  // 跟随谱面换段时，岛上的数字跟着走
      },
      onSegment(info) {
        segInfo.textContent = "第 " + (info.index + 1) + "/" + info.total + " 段 · "
          + info.segment.bpm + " BPM · " + info.segment.beats + "/" + info.segment.beat_type;
        highlightPlan(info.index);
        island.setBpm(info.segment.bpm, true);   // 岛上同步，但不回打给引擎
        metro.setBpm(info.segment.bpm);
      },
    });

    /* 当前真正在用的速度/拍号是引擎说了算，岛只是显示屏。
       每拍都对一次，三处（岛 / 大数字 / 设置）不会再各说各话。 */
    MC.metro = metro;   // 设置卡片要用它来解析变拍表

    function applyMeterSettings() {
      const text = localStorage.getItem("mc.meterMap") || "";
      metro.setMeterMap(metro.parseMeterMap(text));
      const measures = metro.parseMeasureList(localStorage.getItem("mc.fermataMeasures") || "");
      const extra = Math.max(0, parseInt(localStorage.getItem("mc.fermataBeats") || "2", 10) || 0);
      const map = {};
      measures.forEach((m) => { map[m] = extra; });
      metro.setFermata(map);
      // 当前小节该用哪个拍号：变拍表里没有就保持原样（别把第 2 小节的 3/4 提前扣到第 1 小节）
      const here = meterAt(metro.state.measure);
      if (here) {
        metro.state.beats = here.beats;
        metro.state.beatType = here.beatType;
      }
      refreshPlanMeters();
      renderStructure(lastStructure);
      syncIsland();
    }

    /** 把「起拍 / 空拍 / 变拍」这行说明写到练习方案下面 */
    function renderStructure(st) {
      const host = document.getElementById("structure-line");
      if (!host) return;
      const bits = [];
      if (st && st.pickup) bits.push("开头是起拍，约 " + st.pickup.beats + " 拍");
      if (st && st.empty && st.empty.length) {
        const runs = st.empty.map((r) => (r.from === r.to ? `${r.from}` : `${r.from}–${r.to}`));
        bits.push("疑似整小节空拍：" + runs.join("、"));
      }
      const map = metro.state.meterMap || {};
      const keys = Object.keys(map).map(Number).sort((a, b) => a - b);
      if (keys.length) {
        bits.push("变拍：" + keys.map((k) => `第${k}小节起 ${map[k].beats}/${map[k].beatType}`).join("，"));
      }
      host.textContent = bits.length ? bits.join("　|　") : "拍号按 4/4；有变拍就在上面的变拍表里填一行。";
    }

    function meterAt(measure) {
      const keys = Object.keys(metro.state.meterMap).map(Number).filter((k) => k <= measure).sort((a, b) => a - b);
      const key = keys[keys.length - 1];
      return key ? metro.state.meterMap[key] : null;
    }

    /** 把练习方案每一行的拍号按变拍表刷新；段里有延长就标出来 */
    function refreshPlanMeters() {
      if (!planList) return;
      const ferm = metro.state.fermata || {};
      planList.querySelectorAll(".plan-line").forEach((line) => {
        const i = Number(line.dataset.i);
        const s = metro.state.plan[i];
        if (!s) return;
        const m = meterAt(Number(s.start_measure));
        const beats = m ? m.beats : (s.beats || 4);
        const bt = m ? m.beatType : (s.beat_type || 4);
        const hasF = Object.keys(ferm).some((k) => Number(k) >= Number(s.start_measure) && Number(k) <= Number(s.end_measure));
        const span = line.children[2];
        if (span) span.textContent = beats + "/" + bt + (hasF ? " · 𝄐延长" : "");
      });
    }

    let lastStructure = null;
    window.addEventListener("mc-meter-change", applyMeterSettings);
    window.addEventListener("mc-fermata-change", applyMeterSettings);
    applyMeterSettings();

    function syncIsland() {
      if (island.getBpm() !== metro.state.bpm) island.setBpm(metro.state.bpm, true);
      const meterText = metro.state.beats + "/" + metro.state.beatType;
      if (island.getMeter() !== meterText) island.setMeter(meterText, true);
      nowBpm.textContent = metro.state.bpm;
    }

    let title = "";
    let rawPlan = [];
    let latestPayload = null;
    const baseInput = document.getElementById("tempo-base");
    if (baseInput) {
      const saved = localStorage.getItem("mc.tempoBase");
      if (saved) baseInput.value = saved;
      baseInput.onchange = () => applyPlanScale(true);
      baseInput.onkeydown = (e) => { if (e.key === "Enter") applyPlanScale(true); };
      const btn = document.getElementById("tempo-base-apply");
      if (btn) btn.onclick = () => applyPlanScale(true);
    }

    metro.state.sound = S.sound;
    metro.state.accent = S.accent;
    metro.state.accentSound = S.accentSound;
    metro.state.weakSound = S.weakSound;
    metro.setVolume(S.volume);
    metro.setBpm(island.getBpm());
    metro.setMeter(island.getMeter());
    nowBpm.textContent = metro.state.bpm;      // 页面上的大数字别写死 100
    metro.state.follow = followBox.checked = localStorage.getItem("mc.follow") === "on";

    // 从识别页跳过来时带的 ?follow=1 / ?follow=0 优先
    const qFollow = new URLSearchParams(location.search).get("follow");
    if (qFollow !== null) {
      metro.state.follow = followBox.checked = (qFollow === "1" || qFollow === "on");
      localStorage.setItem("mc.follow", metro.state.follow ? "on" : "off");
    }

    /* ---------------- 拍点 ---------------- */
    function drawDots(beats, current, accent) {
      if (dots.dataset.beats !== String(beats)) {
        dots.innerHTML = "";
        for (let i = 0; i < beats; i++) {
          const d = document.createElement("div");
          d.className = "dot" + (i === 0 ? " accent" : "");
          dots.appendChild(d);
        }
        dots.dataset.beats = String(beats);
      }
      Array.from(dots.children).forEach((d, i) => d.classList.toggle("on", i === current - 1));
      if (accent) {
        const first = dots.children[0];
        if (first) {
          first.style.transform = "scale(1.6)";
          setTimeout(() => { first.style.transform = ""; }, 120);
        }
      }
    }

    /* 高亮是一块会滑动的色块：换到下一段就往下滑，换回上面一段就往上滑。
       色块只负责“指位置”，跟文字完全脱钩，选中/移动都不影响排版。 */
    let hl = null;
    function ensureHighlighter() {
      if (hl || !planList) return hl;
      hl = document.createElement("div");
      hl.className = "plan-hl";
      planList.appendChild(hl);
      return hl;
    }

    function highlightPlan(index, instant) {
      const lines = Array.from(planList.querySelectorAll(".plan-line"));
      lines.forEach((line, i) => line.classList.toggle("cur", i === index));
      const h = ensureHighlighter();
      if (!h) return;
      const line = lines[index];
      if (!line) { h.style.opacity = "0"; return; }
      const fresh = h.style.opacity !== "1";     // 第一次出现别从顶上滑下来，直接落位
      if (instant || fresh) h.style.transition = "none";
      // 用实际矩形算偏移，别信 offsetTop（父层不是定位元素时它会算到卡片上去）
      const lr = planList.getBoundingClientRect();
      const rr = line.getBoundingClientRect();
      h.style.top = (rr.top - lr.top) + "px";
      h.style.height = rr.height + "px";
      h.style.opacity = "1";
      if (instant || fresh) { void h.offsetHeight; h.style.transition = ""; }
    }

    /* ---------------- 启动/暂停 ---------------- */
    toggleBtn.onclick = () => {
      metro.toggle();
      syncButton();
      island.setRunning(metro.running);
      syncIsland();          // 一起步就按当前段的速度校准岛和大数字
    };

    function syncButton() {
      toggleBtn.textContent = metro.running ? "暂停" : (metro.state.running ? "继续" : "开始");
      toggleBtn.classList.toggle("btn-primary", !metro.running);
      island.setPlaying(metro.running);
    }

    document.getElementById("stop").onclick = () => {
      metro.stop();
      metro.state.running = false;
      syncButton();
      island.setRunning(false);
      island.setMeasure("");
      nowMeasure.textContent = title || "准备开始";
      Array.from(dots.children).forEach((d) => d.classList.remove("on"));
    };

    document.getElementById("tap").onclick = () => {
      const bpm = metro.tap();
      island.setBpm(bpm, true);
      nowBpm.textContent = bpm;
    };

    /* ---------------- 岛 → 引擎 ---------------- */
    /* 岛上手动改速度（点加减、输入框回车）才算“人定的速度”，
       程序自己同步用的是 silent=true，不会走到这里。
       人在跟随时手动改速 → 直接退出跟随，否则下一小节又被方案改回去，
       就会出现“我设 170、大数字还在响 187”的鬼打墙。 */
    island.onBpm((v) => {
      metro.setBpm(v);
      nowBpm.textContent = metro.state.bpm;
      if (metro.state.follow) stopFollow("自由练习：手动速度 " + v + " BPM");
    });
    island.onMeter((m) => {
      metro.setMeter(m);
      metro.state.beatInBar = 0;
      if (!metro.state.running) drawDots(metro.state.beats, 0, false);
    });

    function stopFollow(note) {
      metro.state.follow = false;
      if (followBox) followBox.checked = false;
      localStorage.setItem("mc.follow", "off");
      if (note && segInfo) segInfo.textContent = note;
      highlightPlan(-1);
    }

    // 岛上的播放键：直接启停同一套引擎
    island.onPlay(() => {
      toggleBtn.click();
    });

    // 页面下方「节拍器设置」改了参数，立刻塞进引擎
    window.addEventListener("mc-sound-change", (e) => {
      const d = e.detail || {};
      metro.state.sound = d.sound;
      metro.state.accent = d.accent;
      metro.state.accentSound = d.accentSound;
      metro.state.weakSound = d.weakSound;
      metro.setVolume(d.volume);
    });

    /* ---------------- 键盘 ---------------- */
    document.addEventListener("keydown", (e) => {
      if (e.target && /input|select|textarea/i.test(e.target.tagName)) return;
      if (e.code === "Space") { e.preventDefault(); toggleBtn.click(); }
      if (e.key === "t" || e.key === "T") document.getElementById("tap").click();
      if (e.key === "ArrowUp") island.setBpm(island.getBpm() + 1);
      if (e.key === "ArrowDown") island.setBpm(island.getBpm() - 1);
    });

    followBox.onchange = () => {
      metro.state.follow = followBox.checked;
      localStorage.setItem("mc.follow", followBox.checked ? "on" : "off");
      if (metro.state.follow && metro.state.plan.length) {
        metro.state.planIndex = 0;
        metro.state.measure = Number(metro.state.plan[0].start_measure) || 1;
        metro.setBpm(metro.state.plan[0].bpm);
        island.setBpm(metro.state.plan[0].bpm, true);
        nowBpm.textContent = metro.state.plan[0].bpm;
      }
      segInfo.textContent = followBox.checked ? "跟随谱面：按小节自动变速" : "自由练习";
    };
    segInfo.textContent = metro.state.follow ? "跟随谱面：按小节自动变速" : "自由练习";

    /* ---------------- 读方案 ---------------- */
    MC.get("/api/latest").then((p) => {
      latestPayload = p || null;
      const plan = metro.planFromPayload(p);
      if (!plan.length) return;
      rawPlan = plan.slice();
      metro.loadPlan(plan, { follow: followBox.checked });
      title = (p.summary || {}).title || "";
      planChip.textContent = plan.length + " 段 · " + (title || "未命名");
      planChip.classList.add("ok");
      planList.innerHTML = plan.map((s, i) => `
        <div class="plan-line" data-i="${i}">
          <span class="bars">${s.start_measure}–${s.end_measure} 小节</span>
          <span><b>${s.bpm} BPM</b></span>
          <span style="color:var(--mc-text-muted)">${s.beats}/${s.beat_type}</span>
        </div>`).join("");
      hl = null;                     // 列表重排了，滑块跟着重做
      // 点某一段 → 从这一拍开始
      planList.querySelectorAll(".plan-line").forEach((line) => {
        line.style.cursor = "pointer";
        line.onclick = () => {
          const i = Number(line.dataset.i);
          const seg = metro.state.plan[i] || plan[i];
          metro.state.follow = true;
          followBox.checked = true;
          metro.state.planIndex = i;
          metro.state.measure = Number(seg.start_measure) || 1;
          metro.state.beatInBar = 0;
          metro.setBpm(seg.bpm);
          island.setBpm(seg.bpm, true);
          island.setMeter(seg.beats + "/" + seg.beat_type, true);
          metro.setMeter(seg.beats + "/" + seg.beat_type);
          const mmAt = meterAt(Number(seg.start_measure));
          if (mmAt) {
            metro.setMeter(mmAt.beats + "/" + mmAt.beatType);
            island.setMeter(mmAt.beats + "/" + mmAt.beatType, true);
          }
          highlightPlan(i);
          segInfo.textContent = "第 " + (i + 1) + "/" + metro.state.plan.length + " 段 · " + seg.bpm + " BPM";
        };
      });
      drawDots(plan[0].beats, 0, false);
      autoTempoFromScore(p);
      applyPlanScale(false);         // 之前填过基础速度就套上
      lastStructure = (p.summary || {}).structure || null;
      applyMeterSettings();          // 手填的变拍表/延长，读进来就生效
      refreshPlanMeters();
      renderStructure(lastStructure);
    }).catch(() => {});

    /* ---------------- 从谱面文字里捞速度标记 ---------------- */
    /* 谱子上写的 ♩=170，OCR 常把它认成 "J=170 ca."。捞出来当整曲基础速度，
       用户没手动填过的时候自动填上，省得自己再抄一遍。 */
    function tempoMarksFromScore(payload) {
      const text = (payload && payload.score_text || []).join("  ");
      const re = /(?:[♩♪JQq𝅘𝅥]|1)\s*[=＝]\s*(\d{2,3})/g;
      const out = [];
      let m;
      while ((m = re.exec(text)) !== null) {
        const v = parseInt(m[1], 10);
        if (v >= 30 && v <= 300 && out.indexOf(v) < 0) out.push(v);
      }
      return out;
    }

    function autoTempoFromScore(payload) {
      if (!baseInput) return;
      /* 谱面速度已经逐段识别出来时，基础速度就是第一段的速度。
         这时按它填 → 比例 1 → 各段保持谱面原速（64→170→180 这种不会被拉歪）。 */
      const map = ((payload && payload.summary && payload.summary.tempo_map) || [])
        .filter((t) => t && Number(t.bpm) > 0)
        .sort((a, b) => Number(a.measure) - Number(b.measure));
      if (map.length >= 2) {
        baseInput.placeholder = "谱面逐段识别 " + map.length + " 处（首段 " +
          Math.round(Number(map[0].bpm)) + "）";
        // 有真值时不许再拿旧的缩放值捣乱（以前存过的 mc.tempoBase 会把 170 拉成 187）
        localStorage.removeItem("mc.tempoBase");
        baseInput.value = String(Math.round(Number(map[0].bpm)));
        baseInput.setAttribute("data-auto", "1");
        return;
      }
      const marks = tempoMarksFromScore(payload);
      if (!marks.length) return;
      baseInput.placeholder = "谱面读到 " + marks.join(" / ");
      if (localStorage.getItem("mc.tempoBase")) return;   // 手动填过就别动
      const pick = Math.max.apply(null, marks);
      baseInput.value = String(pick);
      baseInput.setAttribute("data-auto", "1");
    }

    /* ---------------- 整曲基础速度 ---------------- */
    /* 谱面速度标记没读出来时，AI 会按整曲时长瞎估（经常低到 40 出头）。
       这里给一个总开关：填谱子上那个 ♩= 的数值，所有段落按同比例放大，
       段落之间的相对快慢保留。 */
    function applyPlanScale(persist) {
      if (!rawPlan.length) return;
      /* 谱面速度已经逐段识别出来（第几小节多少 BPM 都是真的），
         这时候再做“整体按比例放大”只会把 170 变成 187，直接置 1。 */
      const map = ((latestPayload && latestPayload.summary && latestPayload.summary.tempo_map) || [])
        .filter((t) => t && Number(t.bpm) > 0);
      if (map.length >= 2) {
        localStorage.removeItem("mc.tempoBase");
        metro.loadPlan(rawPlan.slice(), { follow: metro.state.follow });
        metro.state.planIndex = Math.min(metro.state.planIndex, rawPlan.length - 1);
        planList.querySelectorAll(".plan-line").forEach((line, i) => {
          const b = line.querySelector("b");
          if (b && rawPlan[i]) b.textContent = rawPlan[i].bpm + " BPM";
        });
        if (metro.state.follow) {
          const cur = metro.state.plan[metro.state.planIndex] || rawPlan[0];
          /* 进页面时别拿第一段速度顶掉用户在别的页面调好的速度：
             只有当这一轮已经在跑（真的在跟随播放），才按当前段刷新速度。 */
          if (metro.state.running) {
            metro.setBpm(cur.bpm);
            island.setBpm(cur.bpm, true);
            nowBpm.textContent = cur.bpm;
          } else {
            metro.setBpm(island.getBpm());
            nowBpm.textContent = metro.state.bpm;
          }
        } else {
          metro.setBpm(island.getBpm());
          nowBpm.textContent = metro.state.bpm;
        }
        return;
      }
      const base = parseInt(baseInput.value, 10);
      if (persist) {
        if (base > 0) localStorage.setItem("mc.tempoBase", String(base));
        else localStorage.removeItem("mc.tempoBase");
      }
      const first = Number(rawPlan[0].bpm) || 1;
      const ratio = base > 0 ? base / first : 1;
      const scaled = rawPlan.map((s) => Object.assign({}, s, {
        bpm: Math.max(20, Math.min(300, Math.round(Number(s.bpm) * ratio))),
      }));
      const keepIndex = metro.state.planIndex;
      metro.loadPlan(scaled, { follow: metro.state.follow });
      metro.state.planIndex = Math.min(keepIndex, scaled.length - 1);
      planList.querySelectorAll(".plan-line").forEach((line, i) => {
        const b = line.querySelector("b");
        if (b && scaled[i]) b.textContent = scaled[i].bpm + " BPM";
      });
      const cur = metro.state.plan[metro.state.planIndex] || scaled[0];
      if (metro.state.follow) {
        metro.setBpm(cur.bpm);
        island.setBpm(cur.bpm, true);
        nowBpm.textContent = cur.bpm;
      } else {
        // 自由练习：速度是岛（也就是你手动设的）说了算，别用方案里的第一段覆盖
        metro.setBpm(island.getBpm());
        nowBpm.textContent = island.getBpm();
      }
    }

    drawDots(metro.state.beats, 0, false);
    syncButton();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
