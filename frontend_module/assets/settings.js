/* 设置页逻辑：只管外观（玻璃/动画）和主题兑换；声音已经搬到节拍器页 */
(function () {
  "use strict";
  const MC = (window.MC = window.MC || {});

  // key 是后端 palette 里的真名（不能随便动），label 是界面上显示的
  const THEMES = [
    { key: "默认", label: "默认", accent: "#4B7BE5" },
    { key: "青竹", label: "青竹", accent: "#2FA37C" },
    { key: "琥珀", label: "琥珀", accent: "#C98A2E" },
    { key: "暮紫", label: "暮紫", accent: "#7A67D8" },
    { key: "霁蓝", label: "霁蓝", accent: "#3C87C9" },
    { key: "赤陶", label: "赤陶", accent: "#C15E43" },
  ];

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

  function selectButtons(host, items, current, onPick) {
    host.innerHTML = "";
    items.forEach(([val, label]) => {
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

  function renderThemes() {
    const host = document.getElementById("theme-list");
    if (!host) return;
    host.innerHTML = "";
    const unlocked = !!MC.themeUnlocked;
    const cur = MC.themeName || "默认";
    THEMES.forEach((t) => {
      const item = document.createElement("div");
      item.className = "theme-item" + (t.key === cur ? " on" : "");
      item.innerHTML = `<span class="swatch" style="background:${t.accent}"></span><span>${t.label}</span>`;
      const locked = t.key !== "默认" && !unlocked;
      if (locked) item.style.opacity = ".5";
      item.title = locked ? "需要用兑换码解锁" : "点一下切换";
      item.onclick = async () => {
        if (locked) {
          document.getElementById("redeem-msg").textContent = "这个主题还没解锁，先兑换。";
          return;
        }
        try {
          if (window.MC_PREVIEW) {
            // 离线预览：直接改本地状态，不请求服务
            localStorage.setItem("mc.theme", t.key);
            window.MC_THEME = t.key;
            await MC.applyTheme();
            renderThemes();
            if (MC.syncPreviewLinks) MC.syncPreviewLinks();
            return;
          }
          await MC.post("/api/theme", { theme: t.key });
          await MC.applyTheme();
          renderThemes();
        } catch (err) {
          document.getElementById("redeem-msg").textContent = "切换失败：" + err.message;
        }
      };
      host.appendChild(item);
    });
  }

  function applyPerf(on) {
    localStorage.setItem("mc.perf", on ? "low" : "");
    document.documentElement.setAttribute("data-perf", on ? "low" : "high");
  }

  function bindAi() {
    if (!MC.aiConfig) return;
    const cfg = MC.aiConfig();
    const provHost = document.getElementById("ai-provider");
    const keyEl = document.getElementById("ai-key");
    const modelEl = document.getElementById("ai-model");
    const msg = document.getElementById("ai-msg");
    const card = document.getElementById("ai-card");
    const hint = document.getElementById("ai-local-hint");
    const foldHead = document.getElementById("ai-fold-head");

    // 抽屉式展开：从上往下推开，收回时从下往上卷回去（和分拍面板同一套缓动）
    if (card && foldHead) {
      foldHead.onclick = () => {
        const open = !card.classList.contains("open");
        card.classList.toggle("open", open);
        foldHead.setAttribute("aria-expanded", open ? "true" : "false");
      };
    }
    if (MC.aiProbe) {
      MC.aiProbe().then((hasServer) => {
        if (hasServer) {
          if (hint) hint.style.display = "none";
          if (card) card.style.display = "none";
        }
      });
    }

    function fillModel() {
      const ep = MC.aiEndpoints[MC.aiConfig().provider];
      modelEl.placeholder = ep ? ep.model : "";
    }

    if (provHost) {
      selectButtons(provHost,
        [["doubao", "豆包"], ["deepseek", "DeepSeek"]],
        cfg.provider,
        (v) => { MC.aiSaveConfig({ provider: v, model: "" }); fillModel(); });
    }
    if (keyEl) keyEl.value = cfg.key || "";
    if (modelEl) modelEl.value = cfg.model || "";
    fillModel();

    const saveBtn = document.getElementById("ai-save");
    if (saveBtn) {
      saveBtn.onclick = () => {
        MC.aiSaveConfig({
          key: (keyEl.value || "").trim(),
          model: (modelEl.value || "").trim(),
        });
        if (msg) { msg.style.color = "var(--mc-success)"; msg.textContent = "✓ 已保存到本机浏览器"; }
      };
    }

    const testBtn = document.getElementById("ai-test");
    if (testBtn) {
      testBtn.onclick = async () => {
        MC.aiSaveConfig({
          key: (keyEl.value || "").trim(),
          model: (modelEl.value || "").trim(),
        });
        if (msg) { msg.style.color = "var(--mc-text-muted)"; msg.textContent = "请求中…"; }
        try {
          const r = await MC.aiTest();
          if (msg) { msg.style.color = "var(--mc-success)"; msg.textContent = `✓ 通了，往返 ${r.ms} ms（模型回了「${r.text}」）`; }
        } catch (e) {
          if (msg) { msg.style.color = "var(--mc-danger)"; msg.textContent = "✗ " + e.message; }
        }
      };
    }
  }

  /* ---------------- 赞助者名单 ---------------- */
  const SPONSOR_FOLD = 8;        // 超过这么多人，就折叠成「展开全部」

  function initSponsors() {
    const list = document.getElementById("sponsor-list");
    const wrap = document.getElementById("sponsor-wrap");
    const tools = document.getElementById("sponsor-tools");
    const toggle = document.getElementById("sponsor-toggle");
    const search = document.getElementById("sponsor-search");
    const countEl = document.getElementById("sponsor-count");
    const note = document.getElementById("sponsor-note");
    if (!list || !wrap || !toggle) return;

    let all = [];
    let open = false;
    let keyword = "";

    const fmt = (s) => {
      const tier = (s.tier || "").trim();
      const date = (s.date || "").trim();
      const tail = [tier, date].filter(Boolean).join(" · ");
      return `<span class="sponsor-item"><b>${esc(s.name || "匿名")}</b>${
        tail ? `<small>${esc(tail)}</small>` : ""
      }</span>`;
    };

    function esc(t) {
      return String(t).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
      }[c]));
    }

    function render() {
      const kw = keyword.trim().toLowerCase();
      const shown = kw ? all.filter((s) => String(s.name || "").toLowerCase().includes(kw)) : all;

      if (!shown.length) {
        list.innerHTML = kw
          ? `<div class="sponsor-empty">没搜到叫「${esc(keyword.trim())}」的赞助者</div>`
          : `<div class="sponsor-empty">还没有赞助者。想第一个上榜，去爱发电搜「MaestroCore」支持一下，名字会出现在这里。</div>`;
        wrap.classList.remove("open");
        wrap.classList.add("short");
        tools.hidden = all.length > SPONSOR_FOLD ? false : true;
        return;
      }

      list.innerHTML = shown.map((s, i) =>
        fmt(s).replace("<span class=\"sponsor-item\"",
          `<span class="sponsor-item" style="animation-delay:${Math.min(i, 14) * 26}ms"`)
      ).join("");

      const few = shown.length <= SPONSOR_FOLD || kw;
      wrap.classList.toggle("short", few);
      wrap.classList.toggle("open", !few && open);
      toggle.textContent = open ? "收起" : "展开全部";
      tools.hidden = all.length <= SPONSOR_FOLD && !kw;
    }

    toggle.addEventListener("click", () => {
      open = !open;
      wrap.classList.remove("short");
      wrap.classList.toggle("open", open);
      toggle.textContent = open ? "收起" : "展开全部";
      if (!open) wrap.scrollTop = 0;
    });

    if (search) {
      search.addEventListener("input", () => {
        keyword = search.value;
        if (keyword.trim()) open = true;   // 一搜就直接摊开，免得藏在折叠里
        render();
      });
    }

    const apply = (data) => {
      const arr = Array.isArray(data) ? data : (data && data.sponsors) || [];
      all = arr
        .filter((s) => s && (s.name || "").trim())
        .sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
      if (countEl) {
        countEl.textContent = all.length
          ? `${all.length} 位，按时间从新到旧`
          : "在爱发电支持过 MaestroCore 的人";
      }
      if (note) {
        note.innerHTML = "只放名字，不放金额；不想上榜的跟我说一声就撤掉。";
      }
      render();
    };

    MC.get("/api/sponsors").then(apply).catch(() => apply({ sponsors: [] }));
  }

  function boot() {
    const glassHost = document.getElementById("glass-opts");
    if (glassHost) {
      selectButtons(glassHost,
        [["frosted", "毛玻璃"], ["liquid", "液态玻璃"], ["none", "不用玻璃"]],
        MC.island ? MC.island.getGlass() : "frosted",
        (v) => MC.island && MC.island.setGlass(v));
    }

    bindSwitch("sw-anim", MC.island ? MC.island.getAnim() : true,
      (v) => MC.island && MC.island.setAnim(v));

    // 性能模式：状态存在本机，进页面时先套上，免得白闪一下
    const perfOn = localStorage.getItem("mc.perf") === "low";
    applyPerf(perfOn);
    bindSwitch("sw-perf", perfOn, applyPerf);

    bindAi();

    renderThemes();
    initSponsors();

    // 主题解锁状态是异步拿的，拿到之后必须重画一遍，
    // 否则第一次渲染时 MC.themeUnlocked 还是 undefined，五套主题会被当成上锁
    if (MC.applyTheme) {
      MC.applyTheme().then(() => renderThemes()).catch(() => {});
    }

    const btn = document.getElementById("redeem");
    if (btn) {
      btn.onclick = async () => {
        const code = document.getElementById("code").value.trim();
        const msg = document.getElementById("redeem-msg");
        if (!code) { msg.textContent = "先填兑换码。"; return; }
        try {
          const r = await MC.post("/api/redeem", { code });
          msg.textContent = (r.ok ? "✓ " : "✗ ") + (r.msg || "");
          msg.style.color = r.ok ? "var(--mc-success)" : "var(--mc-danger)";
          if (r.ok) { await MC.applyTheme(); renderThemes(); }
        } catch (err) {
          msg.textContent = "兑换失败：" + err.message;
        }
      };
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();


