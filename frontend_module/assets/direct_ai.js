/* MaestroCore · 浏览器直连大模型
 *
 * 为什么有这个东西：这台机器上跑不起本地 HTTP 服务（回环连接被安全软件拦掉），
 * 所以网页不能靠 /api 转发。好消息是两个模型平台都允许浏览器跨域调用，
 * 于是网页可以自己带 Key 直接请求，不经过任何本地端口。
 *
 * 代价：Key 存在浏览器 localStorage 里，只适合本机自己用。
 * 千万别把填好 Key 的页面截图/发布出去，也别把带 key 的 html 传到仓库。
 */
(function () {
  const MC = (window.MC = window.MC || {});

  const ENDPOINTS = {
    doubao: {
      url: "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
      model: "doubao-seed-2-1-pro-260915",
      label: "豆包（火山方舟）",
    },
    deepseek: {
      url: "https://api.deepseek.com/v1/chat/completions",
      model: "deepseek-v4-pro",
      label: "DeepSeek",
    },
  };

  const STORE = "mc.ai";
  const DEFAULTS = { provider: "doubao", key: "", model: "", maxTokens: 1200 };

  /* 每台浏览器一个匿名 ID，服务端按它计次数（不涉及任何个人信息） */
  function uid() {
    let v = "";
    try {
      v = localStorage.getItem("mc.uid") || "";
      if (!v) {
        v = "u" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
        localStorage.setItem("mc.uid", v);
      }
    } catch (e) {}
    return v;
  }
  MC.aiUid = uid;

  /* 有服务端就用服务端（Key 在服务器上，用户什么都不用填）；
     没有（比如现在这台机器回环被拦）就退回浏览器直连自己的 Key */
  MC.aiServer = false;
  MC.aiProbe = function () {
    if (window.MC_PREVIEW) return Promise.resolve(false);
    return fetch("/api/usage", { headers: { "X-MC-User": uid() } })
      .then((r) => {
        MC.aiServer = r.ok;
        return MC.aiServer;
      })
      .catch(() => {
        MC.aiServer = false;
        return false;
      });
  };
  MC.aiProbe();

  MC.aiEndpoints = ENDPOINTS;

  MC.aiConfig = function () {
    let cfg = {};
    try {
      cfg = JSON.parse(localStorage.getItem(STORE) || "{}") || {};
    } catch (e) {
      cfg = {};
    }
    return Object.assign({}, DEFAULTS, cfg);
  };

  MC.aiSaveConfig = function (patch) {
    const next = Object.assign(MC.aiConfig(), patch || {});
    localStorage.setItem(STORE, JSON.stringify(next));
    return next;
  };

  MC.aiReady = function () {
    if (MC.aiServer) return true; // 服务端模式：Key 在服务器，用户不用填
    const c = MC.aiConfig();
    return !!(c.key && c.provider && ENDPOINTS[c.provider]);
  };

  /* 走服务端代理：Key 不下发，按天限额 */
  MC.aiViaServer = async function (opts) {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-MC-User": uid() },
      body: JSON.stringify({
        system: opts.system,
        user: opts.user,
        provider: opts.provider || MC.aiConfig().provider,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "服务端返回 " + resp.status);
    if (opts.onDelta && data.text) opts.onDelta(data.text, data.text);
    MC.aiLeft = data.left;
    return data.text || "";
  };

  /* 流式请求：一边收一边回调 onDelta，用户能立刻看到字出来 */
  MC.aiStream = async function (opts) {
    if (MC.aiServer) return MC.aiViaServer(opts);
    const cfg = MC.aiConfig();
    const provider = opts.provider || cfg.provider || "doubao";
    const ep = ENDPOINTS[provider];
    if (!ep) throw new Error("不认识的通道：" + provider);
    const key = opts.key || cfg.key;
    if (!key) throw new Error("还没填 API Key，去设置页的「AI 通道」里填一下");

    const body = {
      model: opts.model || cfg.model || ep.model,
      messages: [
        { role: "system", content: opts.system || "你是一位乐队指导老师，回答要短、要具体、能直接照做。" },
        { role: "user", content: opts.user || "" },
      ],
      temperature: 0.3,
      max_tokens: opts.maxTokens || cfg.maxTokens || 1200,
      stream: true,
    };
    // 豆包默认开思考模式，一句话能想 20 秒；这里直接关掉（实测 23s -> 5s）
    if (provider === "doubao") body.thinking = { type: "disabled" };

    const resp = await fetch(ep.url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + key },
      body: JSON.stringify(body),
      signal: opts.signal,
    });

    if (!resp.ok) {
      let detail = "";
      try {
        detail = (await resp.text()).slice(0, 300);
      } catch (e) {}
      const friendly =
        resp.status === 401
          ? "API Key 不对或失效（401）"
          : resp.status === 402
          ? "账户余额不足（402）"
          : resp.status === 429
          ? "触发限流（429），等会儿再试"
          : "接口返回 " + resp.status + "：" + detail;
      throw new Error(friendly);
    }

    if (!resp.body || !resp.body.getReader) {
      // 浏览器不支持流式读，退化成整段
      const text = await resp.text();
      const full = _collect(text);
      if (opts.onDelta && full) opts.onDelta(full, full);
      return full;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let acc = "";
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE 以空行分事件
      let idx;
      while ((idx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (data === "[DONE]") {
          buf = "";
          break;
        }
        let chunk;
        try {
          chunk = JSON.parse(data);
        } catch (e) {
          continue;
        }
        const delta = ((chunk.choices || [])[0] || {}).delta || {};
        const piece = delta.content || "";
        if (piece) {
          acc += piece;
          if (opts.onDelta) opts.onDelta(piece, acc);
        }
      }
    }
    return acc;
  };

  function _collect(text) {
    const out = [];
    text.split(/\n/).forEach(function (line) {
      const l = line.trim();
      if (!l.startsWith("data:")) return;
      const d = l.slice(5).trim();
      if (d === "[DONE]") return;
      try {
        const j = JSON.parse(d);
        const c = ((j.choices || [])[0] || {}).message || ((j.choices || [])[0] || {}).delta || {};
        if (c.content) out.push(c.content);
      } catch (e) {}
    });
    return out.join("");
  }

  /* 把一次识别结果压成一段短提示，别把几万字全塞给模型（省时间也省钱） */
  MC.aiPromptFromResult = function (payload) {
    const s = (payload && payload.summary) || {};
    const ai = (payload && payload.ai) || {};
    const plan = (ai.metronome_plan || [])
      .slice(0, 10)
      .map(function (p) {
        return p.start_measure + "-" + p.end_measure + " 小节 " + p.bpm + "BPM";
      })
      .join(" / ");
    const blocks = (ai.practice_blocks || [])
      .slice(0, 8)
      .map(function (b) {
        return b.measures + "：" + (b.focus || "");
      })
      .join("；");
    return [
      "曲目：" + (s.title || "未知"),
      "声部：" + ((payload && payload.instrument) || "未知"),
      "规模：" + (s.total_measures || 0) + " 小节 / " + (s.total_notes || 0) + " 音符",
      "已判定的难度：" + (ai.level || "未评定"),
      "现有节拍器分段：" + (plan || "无"),
      "现有练习分块：" + (blocks || "无"),
      "",
      "请写一段「今天怎么练」的说明：先给 3 步练习顺序（每步一句话，写清小节号和速度），",
      "再点出最容易翻车的 1 个地方和应对办法。不要复述上面的数据，不要客套。",
    ].join("\n");
  };

  /* 测试 Key：花最少的 token 验证能不能通 */
  MC.aiTest = async function () {
    const cfg = MC.aiConfig();
    const t0 = performance.now();
    const text = await MC.aiStream({
      system: "只回答一个词。",
      user: "回复：通",
      maxTokens: 8,
    });
    return { ok: true, ms: Math.round(performance.now() - t0), text: (text || "").trim() };
  };
})();
