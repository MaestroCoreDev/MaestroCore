/* MaestroCore 前端公共脚本：接口请求、主题、结果渲染、上传流程 */
(function () {
  "use strict";

  const MC = (window.MC = window.MC || {});

  /* ---------------- 基础请求 ---------------- */
  /* 离线预览：直接双击 html 时（file://）没有服务，用内联数据顶上 */
  function offline(path) {
    const P = window.MC_PREVIEW;
    if (!P) return undefined;
    if (path === "/api/theme") return P.theme || { theme: "默认", unlocked: false };
    if (path === "/api/latest") return P.latest || { empty: true };
    if (path === "/api/history") return P.history || [];
    if (path === "/api/sponsors") return P.sponsors || { sponsors: [] };
    if (path.startsWith("/api/result/")) {
      const no = path.split("/").pop();
      return (P.results || {})[no] || { error: "离线预览里没有这条记录" };
    }
    return { ok: false, msg: "这是离线预览页面，不能提交或写入。要用真功能请双击 启动网页.bat。" };
  }

  async function api(path, options) {
    if (window.MC_PREVIEW) return offline(path);
    const resp = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, options || {}));
    if (!resp.ok) {
      let detail = "";
      try { detail = (await resp.json()).error || ""; } catch (_) { /* ignore */ }
      throw new Error(detail || ("接口返回 " + resp.status));
    }
    return resp.json();
  }
  MC.api = api;
  MC.get = (p) => api(p);
  MC.post = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });

  /* ---------------- 主题：跟后端的解锁状态对齐 ---------------- */
  MC.applyTheme = async function () {
    try {
      // 离线预览没有服务，主题状态走 localStorage
      if (window.MC_PREVIEW) {
        const P = window.MC_PREVIEW.theme || {};
        // 地址栏 ?t= 是页面之间传的主题；没有再退回默认，不要老拿着上一次点过的颜色不放
        const qTheme = new URLSearchParams(location.search).get("t");
        const name = window.MC_THEME || qTheme || P.theme || "默认";
        window.MC_THEME = name;
        localStorage.setItem("mc.theme", name);
        if (name === "默认") document.documentElement.removeAttribute("data-theme");
        else document.documentElement.setAttribute("data-theme", name);
        MC.themeName = name;
        MC.themeUnlocked = !!P.unlocked;
        return;
      }
      const t = await MC.get("/api/theme");
      const name = t.theme || "默认";
      if (name === "默认") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", name);
      MC.themeName = name;
      MC.themeUnlocked = !!t.unlocked;
    } catch (_) { /* 服务没开就先按默认配色渲染 */ }
  };

  /* ---------------- 小工具 ---------------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  MC.esc = esc;

  function el(id) { return document.getElementById(id); }
  MC.el = el;

  function measureRange(a, b) {
    if (!a && !b) return "";
    if (String(a).includes("-")) return String(a);
    if (!b) return String(a);
    return a + "–" + b;
  }
  MC.measureRange = measureRange;

  /* ---------------- 结果渲染 ---------------- */
  MC.renderResult = function (payload, target) {
    const host = target || el("result");
    if (!host) return;
    if (!payload || payload.empty || !payload.summary) {
      host.innerHTML = '<div class="empty">还没有结果。左边传一张谱子，跑一次就有了。</div>';
      return;
    }

    const s = payload.summary || {};
    const ai = payload.ai || {};
    const guess = ai.piece_guess || {};

    const soloHtml = (ai.solo_highlights || []).map((x) => `
      <div class="item">
        <div class="title">★ ${esc(x.type || "重点段")}　第 ${esc(x.measures || "")} 小节</div>
        <div class="body">${esc(x.note || "")}</div>
      </div>`).join("") || '<div class="empty">模型没给出重点段</div>';

    const blockHtml = (ai.practice_blocks || []).map((b) => `
      <div class="measure-line">
        <span class="m">${esc(b.measures || "")}</span>
        <span><b>${esc(b.tempo_bpm || "")} BPM</b>　${esc(b.focus || "")}</span>
      </div>
      <div class="body" style="font-size:12.5px;color:var(--mc-text-muted);padding:0 0 8px 82px">${esc(b.tips || "")}</div>
    `).join("") || '<div class="empty">没有练习分段</div>';

    const hardHtml = (ai.hard_spots || []).map((h) => `
      <div class="item">
        <div class="title">难点　第 ${esc(h.measures || "")} 小节</div>
        <div class="body">${esc(h.why || "")}<br>→ ${esc(h.how || "")}</div>
      </div>`).join("") || '<div class="empty">没有标出难点</div>';

    const plan = ai.metronome_plan || [];
    const planHtml = plan.map((p) => `
      <div class="measure-line">
        <span class="m">${p.start_measure}–${p.end_measure}</span>
        <span>${p.bpm} BPM　${p.beats}/${p.beat_type}</span>
      </div>`).join("") || '<div class="empty">没有节拍器分段</div>';

    host.innerHTML = `
      <div class="card">
        <div class="card-head">
          <h2>${esc(s.title || "未命名乐曲")}</h2>
          <span class="badge">${esc(ai.level || "未评定")}</span>
          ${payload.instrument ? `<span class="chip">${esc(payload.instrument)}</span>` : ""}
          <span class="hint">${s.total_measures || 0} 小节 · ${s.total_notes || 0} 音符 · 约 ${s.estimated_duration_sec || 0} 秒</span>
        </div>
        <div class="kv">
          <div class="k">曲目推测</div>
          <div class="v">${esc(guess.name || "未知")}${guess.composer ? " · " + esc(guess.composer) : ""}
            ${guess.confidence ? `<span class="badge warn">${esc(guess.confidence)}</span>` : ""}</div>
          <div class="k">声部角色</div><div class="v">${esc(ai.ensemble_role || "无法判断")}</div>
        </div>
        ${ai.overview ? `<p style="margin:14px 0 0">${esc(ai.overview)}</p>` : ""}
        ${ai.background ? `<p style="margin:6px 0 0;color:var(--mc-text-muted);font-size:12.5px">${esc(ai.background)}</p>` : ""}
        <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--mc-border)">
          <button class="btn" id="ai-live-btn">让 AI 现场讲一段</button>
          <span class="hint" style="margin-left:10px">直连模型，边生成边显示</span>
          <div id="ai-live-out" style="margin-top:10px;font-size:13px;line-height:1.7;white-space:pre-wrap"></div>
        </div>
      </div>

      <div class="grid-2" style="margin-top:16px">
        <div class="card">
          <div class="card-head"><h2>重点 / 独奏段</h2></div>
          <div class="list">${soloHtml}</div>
        </div>
        <div class="card">
          <div class="card-head"><h2>难点</h2></div>
          <div class="list">${hardHtml}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2>分块练</h2><span class="hint">由易到难、由慢到快</span></div>
        ${blockHtml}
        ${ai.tempo_notes ? `<p style="margin:12px 0 0;font-size:12.5px;color:var(--mc-text-muted)">速度处理：${esc(ai.tempo_notes)}</p>` : ""}
      </div>

      <div class="card">
        <div class="card-head">
          <h2>节拍器分段</h2>
          <span class="hint">按小节从头走到尾，到段末自动换速度</span>
          <a href="metronome.html" style="margin-left:auto" class="btn btn-primary">用这个方案练 →</a>
        </div>
        ${planHtml}
      </div>
    `;

    // AI 现场讲解：浏览器直接打模型，流式出字；没填 Key 就提示去设置
    const aiBtn = host.querySelector("#ai-live-btn");
    const aiOut = host.querySelector("#ai-live-out");
    if (aiBtn && aiOut) {
      aiBtn.onclick = async () => {
        if (!MC.aiStream) { aiOut.textContent = "AI 模块没加载，刷新一下。"; return; }
        if (!MC.aiReady || !MC.aiReady()) {
          aiOut.textContent = "还没配 Key。去「设置 → AI 通道」填一个，几秒钟就好。";
          return;
        }
        aiBtn.disabled = true;
        aiOut.textContent = "";
        try {
          await MC.aiStream({
            system: "你是乐队指导老师，说话短、具体、能直接照着练。用中文。",
            user: MC.aiPromptFromResult(payload),
            onDelta: (_piece, acc) => { aiOut.textContent = acc; },
          });
        } catch (e) {
          aiOut.textContent = "调用失败：" + e.message;
        } finally {
          aiBtn.disabled = false;
          aiBtn.textContent = "换一段再讲";
        }
      };
    }
  };

  /* ---------------- 首页：上传跑流水线 ---------------- */
  MC.initIndex = function () {
    const picked = [];
    const drop = el("drop");
    const fileInput = el("file");
    const list = el("files");
    const runBtn = el("run");
    const logBox = el("log");
    const status = el("status");
    if (window.MC_PREVIEW) runBtn.textContent = "用桌面助手识别";

    function renderFiles() {
      list.innerHTML = picked.map((f, i) => `
        <div class="file-item">
          <b>${esc(f.name)}</b>
          <span class="path">${(f.size / 1024).toFixed(0)} KB</span>
          <button data-i="${i}" class="btn-ghost" style="margin-left:auto;padding:4px 10px">移除</button>
        </div>`).join("");
      list.querySelectorAll("button").forEach((b) => {
        b.onclick = () => { picked.splice(+b.dataset.i, 1); renderFiles(); };
      });
      runBtn.disabled = picked.length === 0;
    }

    function addFiles(files) {
      Array.from(files || []).forEach((f) => {
        if (!/^image\//.test(f.type)) return;
        picked.push(f);
      });
      renderFiles();
    }

    drop.onclick = () => fileInput.click();
    fileInput.onchange = () => { addFiles(fileInput.files); fileInput.value = ""; };

    // 手机上最常用的两条路：直接调相机、或从相册挑几页
    const camBtn = el("btn-camera");
    const albumBtn = el("btn-album");
    const camInput = el("file-camera");
    if (camBtn && camInput) {
      camBtn.onclick = () => camInput.click();
      camInput.onchange = () => { addFiles(camInput.files); camInput.value = ""; };
    }
    if (albumBtn) albumBtn.onclick = () => fileInput.click();
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
      e.preventDefault(); drop.classList.add("over");
    }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
      e.preventDefault(); drop.classList.remove("over");
    }));
    drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

    async function toBase64(file) {
      const buf = await file.arrayBuffer();
      let bin = "";
      const bytes = new Uint8Array(buf);
      for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
      return btoa(bin);
    }

    runBtn.onclick = async function () {
      if (!picked.length) return;
      if (window.MC_PREVIEW) {
        // 离线预览没有服务：直接说清楚该去哪儿按
        status.textContent = "离线页面不能跑识别";
        logBox.style.display = "block";
        logBox.textContent =
          "要识别新谱子，双击桌面上的「识别谱面.bat」：选照片 → 开始识别 → 跑完会自动打开这个网页。\n" +
          "这里看到的是上一次识别好的结果，看结果、进节拍器都正常。";
        return;
      }
      runBtn.disabled = true;
      status.textContent = "正在上传图片…";
      logBox.style.display = "block";
      logBox.textContent = "";
      const prog = el("progress");
      const progLabel = el("progress-label");
      if (prog) { prog.hidden = false; progLabel.textContent = "正在上传图片…"; }
      try {
        const images = [];
        for (const f of picked) {
          images.push({ name: f.name, data: await toBase64(f) });
        }
        const body = {
          images_data: images,
          instrument: el("instrument").value.trim(),
          tempo: el("tempo").value.trim(),
          provider: (el("provider") && el("provider").value) || "doubao",
        };
        const { job } = await MC.post("/api/analyze", body);
        status.textContent = "识别中…（这一步可能要 1–3 分钟）";
        if (progLabel) progLabel.textContent = "谱面识别中…";
        await waitJob(job, logBox, status, progLabel);
      } catch (err) {
        status.textContent = "出错了：" + err.message;
        if (progLabel) progLabel.textContent = "出错了：" + err.message;
      } finally {
        runBtn.disabled = false;
        if (prog) setTimeout(() => { prog.hidden = true; }, 600);
      }
    };

    // 首屏先把已有结果放出来
    MC.get("/api/latest").then((p) => MC.renderResult(p, el("result"))).catch(() => {});
    renderFiles();
  };

  async function waitJob(jobId, logBox, status, progLabel) {
    while (true) {
      await new Promise((r) => setTimeout(r, 1200));
      const job = await MC.get("/api/job/" + jobId);
      if (job.log) {
        logBox.textContent = job.log;
        logBox.scrollTop = logBox.scrollHeight;
        if (progLabel) {
          const lines = job.log.trim().split("\n");
          const last = (lines[lines.length - 1] || "").trim();
          if (last) progLabel.textContent = last.length > 60 ? last.slice(-60) : last;
        }
      }
      if (job.status === "done") {
        status.textContent = "完成。";
        MC.renderResult(job.result, el("result"));
        return;
      }
      if (job.status === "error") {
        status.textContent = "失败：" + (job.error || "未知错误");
        if (progLabel) progLabel.textContent = "失败：" + (job.error || "未知错误");
        return;
      }
    }
  }

  /* ---------------- 历史页 ---------------- */
  MC.initHistory = function () {
    const host = el("history");
    MC.get("/api/history").then((records) => {
      if (!records || !records.length) {
        host.innerHTML = '<div class="empty">还没有历史记录，先跑一次谱子。</div>';
        return;
      }
      records.sort((a, b) => (b.index || 0) - (a.index || 0));
      const themeTag = window.MC_PREVIEW
        ? "&t=" + encodeURIComponent(MC.themeName || "默认")
        : "";
      host.innerHTML = records.map((r) => `
        <a class="item" style="display:block" href="record.html?no=${String(r.index).padStart(2, "0")}${themeTag}">
          <div class="title">${String(r.index).padStart(2, "0")} · ${esc(r.title || "未命名乐曲")}
            ${r.level ? `<span class="badge" style="margin-left:8px">${esc(r.level)}</span>` : ""}</div>
          <div class="body">${r.measures || 0} 小节 · ${r.notes || 0} 音符 · ${esc(r.created_at || "")}
            ${r.instrument ? " · " + esc(r.instrument) : ""}${r.provider ? " · " + esc(r.provider) : ""}</div>
        </a>`).join("");
    }).catch((err) => {
      host.innerHTML = `<div class="empty">读取失败：${esc(err.message)}</div>`;
    });
  };

  /* ---------------- 单条记录页 ---------------- */
  MC.initRecord = function () {
    const no = new URLSearchParams(location.search).get("no") || "01";
    MC.get("/api/result/" + no).then((p) => MC.renderResult(p, el("result")))
      .catch((err) => {
        el("result").innerHTML = `<div class="empty">没有这条记录：${esc(err.message)}</div>`;
      });
  };

  /* ---------------- 启动 ---------------- */
  /* 版本号：页脚统一写一个，改了 VERSION 文件所有页面一起变 */
  MC.renderVersion = function () {
    const apply = (m) => {
      if (!m || !m.version) return;
      MC.meta = m;
      document.querySelectorAll(".foot").forEach((f) => {
        if (f.querySelector(".mc-ver")) return;
        const s = document.createElement("span");
        s.className = "mc-ver";
        s.style.cssText = "margin-left:10px;opacity:.5;font-size:11.5px;letter-spacing:.02em";
        s.textContent = "v" + m.version + (m.built ? " · " + m.built : "");
        s.title = m.channel === "preview" ? "离线预览快照" : "服务模式";
        f.appendChild(s);
      });
    };
    if (window.MC_META) apply(window.MC_META);
    else if (MC.get) MC.get("/api/meta").then(apply).catch(() => {});
  };

  MC.boot = function () {
    // 性能模式先套上，避免进页面才关模糊导致闪一下
    try {
      document.documentElement.setAttribute(
        "data-perf",
        localStorage.getItem("mc.perf") === "low" ? "low" : "high"
      );
    } catch (e) {}
    MC.applyTheme();
    MC.renderVersion();
    bindPageLeave();
    const page = document.body.dataset.page;
    if (page === "index") MC.initIndex();
    if (page === "history") MC.initHistory();
    if (page === "record") MC.initRecord();
  };

  /* 点导航先让页面收一下再跳，别硬切（PCL 那种干脆的过渡） */
  function bindPageLeave() {
    document.querySelectorAll(".nav-links a").forEach((a) => {
      a.addEventListener("click", (e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
        const href = a.dataset.rawHref || a.getAttribute("href");
        if (!href || href.startsWith("#") || a.classList.contains("active")) return;
        e.preventDefault();
        document.body.classList.add("pg-leave");
        MC.savePreviewState();
        setTimeout(() => { location.href = MC.previewHrefTheme(href); }, 130);
      });
    });
    MC.syncPreviewLinks();
  }

  /* 离线预览：把 mc.* 状态放进 window.name，同标签页翻页时天然带过去
     （不写地址栏，URL 保持干净；Firefox 本地文件之间 localStorage 不通） */
  MC.savePreviewState = function () {
    if (!window.MC_PREVIEW) return;
    const bag = {};
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.indexOf("mc.") === 0) bag[k] = localStorage.getItem(k);
      }
      bag["mc.ts"] = String(Date.now());   // 带时间戳，翻页时谁新听谁的
      window.name = "mc:" + JSON.stringify(bag);
    } catch (_) { /* 忽略 */ }
  };

  MC.syncPreviewLinks = function () { /* 状态不再塞链接，保留空实现免得旧代码报错 */ };

  /* 每动一下就同步：任何 mc.* 写入都顺手把状态塞进 window.name，
     这样翻页时不会拿着上一版的旧值（玻璃、速度、拍号、主题都走这条路） */
  (function hookStorage() {
    if (!Storage || !Storage.prototype || Storage.prototype.__mcHooked) return;
    const rawSet = Storage.prototype.setItem;
    const rawRemove = Storage.prototype.removeItem;
    Storage.prototype.setItem = function (k, v) {
      try { rawSet.call(this, k, v); } catch (_) { /* file:// 下可能被拦，靠 window.name 兜底 */ }
      if (String(k).indexOf("mc.") === 0 && MC.savePreviewState) MC.savePreviewState();
    };
    Storage.prototype.removeItem = function (k) {
      rawRemove.call(this, k);
      if (String(k).indexOf("mc.") === 0 && MC.savePreviewState) MC.savePreviewState();
    };
    Storage.prototype.__mcHooked = true;
  })();

  /* 预览里所有站内链接都带上当前主题，任何一种跳法都不会掉回默认 */
  MC.previewHrefTheme = function (href) {
    if (!window.MC_PREVIEW || !href) return href;
    if (/[?&]t=/.test(href)) return href;
    const theme = MC.themeName || localStorage.getItem("mc.theme") || "默认";
    const hashAt = href.indexOf("#");
    const base = hashAt >= 0 ? href.slice(0, hashAt) : href;
    const hash = hashAt >= 0 ? href.slice(hashAt) : "";
    const sep = base.indexOf("?") >= 0 ? "&" : "?";
    return base + sep + "t=" + encodeURIComponent(theme) + hash;
  };

  document.addEventListener("click", (e) => {
    if (!window.MC_PREVIEW) return;
    const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    const href = a.getAttribute("href");
    if (!href || href.startsWith("#") || /^[a-z]+:/i.test(href) || !/\.html/.test(href)) return;
    if (a.closest(".nav-links")) return;      // 导航有自己的淡出处理
    MC.savePreviewState();
    a.setAttribute("href", MC.previewHrefTheme(href));
  }, true);

  /* 非节拍器页面：岛上的播放键也能直接响，不用先跳页 */
  MC.bootIslandMetronome = function () {
    if (!MC.createMetronome || !MC.island) return;
    const metro = MC.createMetronome({});
    const read = (k, d) => localStorage.getItem(k) || d;
    metro.state.sound = read("mc.sound", "on") !== "off";
    metro.state.accent = read("mc.accent", "on") !== "off";
    metro.state.accentSound = read("mc.accentSound", "wood");
    metro.state.weakSound = read("mc.weakSound", "beep");
    const rawVol = localStorage.getItem("mc.volume");
    metro.setVolume(rawVol === null ? 0.8 : (parseFloat(rawVol) > 1 ? parseFloat(rawVol) / 100 : parseFloat(rawVol)));
    metro.setBpm(MC.island.getBpm());
    metro.setMeter(MC.island.getMeter());

    MC.island.onBpm((v) => metro.setBpm(v));
    MC.island.onMeter((m) => metro.setMeter(m));
    MC.island.onPlay(() => {
      metro.toggle();
      MC.island.setPlaying(metro.running);
    });

    window.addEventListener("mc-sound-change", (e) => {
      const d = e.detail || {};
      metro.state.sound = d.sound;
      metro.state.accent = d.accent;
      metro.state.accentSound = d.accentSound;
      metro.state.weakSound = d.weakSound;
      metro.setVolume(d.volume);
    });
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", MC.boot);
  else MC.boot();
})();

