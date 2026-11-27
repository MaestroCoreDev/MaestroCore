/* 离线预览的状态通道：file:// 下每个 html 文件各自一个 localStorage，
   所以设置页选的玻璃、改的速度根本传不到别的页面（三页三种效果就是这么来的）。
   这里把全部 mc.* 状态编码进 URL 的 s= 参数：
   进页面先按 URL 还原，之后任何一改动立刻把 URL 刷新，
   页面里的站内链接也自动带上当前状态 —— 换标签页、直接打开都一致。 */
(function () {
  "use strict";
  var RE = /^mc\./;

  function readState() {
    var o = {};
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && RE.test(k)) o[k] = localStorage.getItem(k);
      }
    } catch (_) { /* 忽略 */ }
    return o;
  }

  function enc(o) {
    try {
      return btoa(unescape(encodeURIComponent(JSON.stringify(o))))
        .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    } catch (_) { return ""; }
  }

  function dec(s) {
    try {
      return JSON.parse(decodeURIComponent(escape(
        atob(s.replace(/-/g, "+").replace(/_/g, "/")))));
    } catch (_) { return null; }
  }

  function put(o) {
    if (!o) return;
    for (var k in o) {
      if (!RE.test(k)) continue;
      try { localStorage.setItem(k, o[k]); } catch (_) { /* 忽略 */ }
    }
  }

  // 1) URL 里的状态最可信（跟标签页、跟新打开的页面都走）
  var fromUrl = dec(new URLSearchParams(location.search).get("s") || "");
  put(fromUrl);
  if (fromUrl) {
    // 打过时间戳，免得 head 里的旧状态袋把这套刚还原的值顶回去
    try { localStorage.setItem("mc.ts", String(Date.now())); } catch (_) { /* 忽略 */ }
  }

  // 2) 把当前状态写回地址栏，动一下就同步；链接也跟着重算，
  //    不然先渲染再改设置，链接里还带着改之前那套状态（切回旧玻璃就是这么来的）
  function syncUrl() {
    try {
      var u = new URL(location.href);
      var s = enc(readState());
      if (s) u.searchParams.set("s", s); else u.searchParams.delete("s");
      history.replaceState(null, "", u.toString());
    } catch (_) { /* 忽略 */ }
    decorate();
  }
  window.MC_SYNC_PREVIEW_STATE = syncUrl;

  // 3) 任何 mc.* 写入 / 删除，立刻刷地址栏
  (function hook() {
    if (!window.Storage || !Storage.prototype || Storage.prototype.__mcUrlHooked) return;
    var set = Storage.prototype.setItem;
    var rem = Storage.prototype.removeItem;
    Storage.prototype.setItem = function (k, v) {
      set.call(this, k, v);
      if (RE.test(String(k))) syncUrl();
    };
    Storage.prototype.removeItem = function (k) {
      rem.call(this, k);
      if (RE.test(String(k))) syncUrl();
    };
    Storage.prototype.__mcUrlHooked = true;
  })();

  // 4) 站内链接一律带上当前状态，另开标签页也不会掉档
  function decorate() {
    var s = enc(readState());
    var links = document.querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#" || /^[a-z]+:/i.test(href) || !/\.html/.test(href)) continue;
      try {
        var u = new URL(href, location.href);
        if (s) u.searchParams.set("s", s);
        a.setAttribute("href", u.pathname.split("/").pop() + u.search + u.hash);
      } catch (_) { /* 忽略 */ }
    }
  }

  // 点链接前再算一次，保证带走的永远是刚改过的状态
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    var href = a.getAttribute("href");
    if (!href || href.charAt(0) === "#" || /^[a-z]+:/i.test(href) || !/\.html/.test(href)) return;
    try {
      var u = new URL(href, location.href);
      var s = enc(readState());
      if (s) u.searchParams.set("s", s);
      a.setAttribute("href", u.pathname.split("/").pop() + u.search + u.hash);
    } catch (_) { /* 忽略 */ }
  }, true);

  document.addEventListener("DOMContentLoaded", function () { decorate(); syncUrl(); });
  syncUrl();
})();
