// Data Browser - MediaCrawler
// 提供帖子与评论的统一浏览，支持抖音、小红书、快手、B站、微博、贴吧、知乎等平台。
(function () {
  "use strict";

  const API_BASE = "/api/data-browser";
  const STATE = {
    platform: null,
    storage: "",
    keyword: "",
    page: 1,
    pageSize: 50,
    posts: [],
    total: 0,
    storageUsed: null,
    expanded: new Set(),
    platforms: [],
    stats: [],
  };

  const PLATFORM_LABEL = {
    xhs: "小红书", dy: "抖音", ks: "快手", bili: "B站",
    wb: "微博", tieba: "百度贴吧", zhihu: "知乎",
  };

  const PLATFORM_TAG_CLASS = {
    xhs: "xhs", dy: "dy", ks: "ks", bili: "bili",
    wb: "wb", tieba: "tieba", zhihu: "zhihu",
  };

  function $(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    if (s === undefined || s === null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function escapeAttr(s) { return escapeHtml(s); }

  function fmtNum(n) {
    if (n === undefined || n === null || n === "") return "0";
    n = String(n);
    if (n.length <= 4) return n;
    const num = parseInt(n, 10);
    if (!isFinite(num)) return n;
    if (num >= 100000000) return (num / 100000000).toFixed(1) + "亿";
    if (num >= 10000) return (num / 10000).toFixed(1) + "万";
    return n;
  }

  function toast(msg, type) {
    const el = $("toast");
    el.textContent = msg;
    el.style.background = type === "error" ? "#dc2626" : "#10b981";
    el.style.opacity = "1";
    el.style.transform = "translateY(0)";
    setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(-8px)"; }, 2400);
  }

  async function api(path, opts) {
    const url = API_BASE + path;
    const res = await fetch(url, opts || {});
    if (!res.ok) {
      let detail = res.statusText;
      try { const d = await res.json(); detail = d.detail || JSON.stringify(d); } catch (_) {}
      throw new Error(detail);
    }
    return await res.json();
  }

  // ---------- 平台统计卡片 ----------
  async function loadStats() {
    try {
      const data = await api("/stats");
      STATE.stats = data.stats || [];
      renderStats();
    } catch (e) {
      console.error(e);
    }
  }

  function renderStats() {
    const bar = $("stats-bar");
    if (!STATE.stats.length) { bar.innerHTML = ""; return; }
    bar.innerHTML = STATE.stats.map(s => {
      const cls = s.has_data ? "" : "empty";
      const active = STATE.platform === s.platform ? "active" : "";
      const dataAttr = s.has_data ? `data-platform="${s.platform}"` : "";
      // 最多 2 行：emoji+名称｜数据+来源（仅当有数据时）
      return `
        <div class="stat-card ${cls} ${active}" ${dataAttr}>
          <div class="stat-line1"><span class="emoji">${s.emoji}</span><span class="name">${escapeHtml(s.label)}</span></div>
          ${s.has_data
            ? `<div class="stat-line2"><span>📝 <b>${fmtNum(s.post_count)}</b></span><span>💬 <b>${fmtNum(s.comment_count)}</b></span><span class="storage-tag">${escapeHtml(s.storage || "")}</span></div>`
            : `<div class="stat-line2 stat-empty-text">暂无数据</div>`}
        </div>`;
    }).join("");
    bar.querySelectorAll(".stat-card[data-platform]").forEach(el => {
      el.addEventListener("click", () => {
        STATE.platform = el.getAttribute("data-platform");
        STATE.page = 1;
        STATE.keyword = "";
        $("keyword-input").value = "";
        renderStats();
        loadPosts();
      });
    });
  }

  // ---------- 帖子列表 ----------
  async function loadPosts() {
    if (!STATE.platform) {
      $("post-list").innerHTML = emptyHint("👈 请先在左侧选择平台");
      $("pagination-bar").innerHTML = "";
      return;
    }
    const params = new URLSearchParams({
      platform: STATE.platform,
      limit: STATE.pageSize,
      offset: (STATE.page - 1) * STATE.pageSize,
    });
    if (STATE.storage) params.set("storage", STATE.storage);
    if (STATE.keyword) params.set("keyword", STATE.keyword);

    $("post-list").innerHTML = `<div style="text-align:center;padding:60px;color:#888;">加载中...</div>`;
    try {
      const data = await api("/posts?" + params.toString());
      STATE.posts = data.items || [];
      STATE.total = data.total || 0;
      STATE.storageUsed = data.storage;
      renderPosts();
      renderPagination();
    } catch (e) {
      $("post-list").innerHTML = `<div style="text-align:center;padding:60px;color:#dc2626;">加载失败：${escapeHtml(e.message)}</div>`;
    }
  }

  function renderPosts() {
    const root = $("post-list");
    if (!STATE.posts.length) {
      root.innerHTML = emptyHint(STATE.keyword ? "🔍 没有匹配的帖子" : "📭 暂无帖子数据");
      return;
    }
    root.innerHTML = STATE.posts.map(renderPostCard).join("");
    bindPostEvents();
  }

  function renderPostCard(p) {
    const tagCls = PLATFORM_TAG_CLASS[STATE.platform] || "";
    const platformLabel = PLATFORM_LABEL[STATE.platform] || STATE.platform;
    const stats = platformStats(p);
    const tagsHtml = p.tags ? p.tags.split(",").filter(Boolean).slice(0, 5)
      .map(t => `<span class="hash-tag">#${escapeHtml(t)}</span>`).join("") : "";
    const keyword = p.source_keyword
      ? `<span class="kw-tag">关键词：${escapeHtml(p.source_keyword)}</span>`
      : "";
    const imgs = p.image_urls && p.image_urls.length ? p.image_urls : (p.cover_url ? [p.cover_url] : []);
    return `
      <div class="post-card" data-post-id="${escapeAttr(p.post_id)}">
        ${imgs.length ? `
          <div class="post-imgs-top">
            ${imgs.filter(Boolean).slice(0, 6).map(u => `
              <a href="${escapeAttr(p.post_url || u)}" target="_blank" rel="noopener" class="post-img-thumb">
                <img src="${escapeAttr(u)}" loading="lazy" onerror="this.parentElement.style.display='none';" />
              </a>`).join("")}
          </div>
        ` : ""}
        <div class="post-head">
          <div class="meta-row">
            <span class="platform-tag ${tagCls}">${escapeHtml(platformLabel)}</span>
            <span class="meta-tag">${escapeHtml(p.post_type || "")}</span>
            <span class="meta-tag">·</span>
            <span class="meta-tag">${escapeHtml(p.create_time || "时间未知")}</span>
            ${keyword}
          </div>
          <div class="title">${escapeHtml(p.title || (p.content || "").slice(0, 80) || "（无标题）")}</div>
          <div class="content-text">${escapeHtml(p.content || "")}</div>
          ${tagsHtml ? `<div class="tags">${tagsHtml}</div>` : ""}
          <div class="footer-row">
            <div class="stats-line">
              <span title="作者">👤 ${escapeHtml(p.author || "匿名")}</span>
              ${stats}
              ${p.video_url ? `<a href="${escapeAttr(p.video_url)}" target="_blank" rel="noopener" class="ext-link">🎬 视频</a>` : ""}
              ${p.post_url ? `<a href="${escapeAttr(p.post_url)}" target="_blank" rel="noopener" class="ext-link">🔗 原帖</a>` : ""}
            </div>
            <button class="btn btn-ghost toggle-comments-btn" data-post-id="${escapeAttr(p.post_id)}">
              💬 <b>${p.comments_total || 0}</b> ${STATE.expanded.has(p.post_id) ? "▲" : "▼"}
            </button>
          </div>
        </div>
        <div class="comments-area" data-post-id="${escapeAttr(p.post_id)}" style="display:${STATE.expanded.has(p.post_id) ? "block" : "none"};">
          ${renderComments(p.comments || [], p.comments_total || 0, p.has_more_comments)}
        </div>
      </div>
    `;
  }

  function platformStats(p) {
    const parts = [];
    const plat = STATE.platform;
    if (plat === "bili") {
      if (p.view_count) parts.push(`<span title="播放">▶ ${fmtNum(p.view_count)}</span>`);
      if (p.liked_count) parts.push(`<span title="点赞">👍 ${fmtNum(p.liked_count)}</span>`);
      if (p.coin_count) parts.push(`<span title="投币">🪙 ${fmtNum(p.coin_count)}</span>`);
      if (p.favorite_count) parts.push(`<span title="收藏">⭐ ${fmtNum(p.favorite_count)}</span>`);
      if (p.share_count) parts.push(`<span title="转发">↗ ${fmtNum(p.share_count)}</span>`);
      if (p.danmaku_count) parts.push(`<span title="弹幕">💬 ${fmtNum(p.danmaku_count)}</span>`);
    } else if (plat === "dy" || plat === "ks") {
      if (p.liked_count) parts.push(`<span title="点赞">👍 ${fmtNum(p.liked_count)}</span>`);
      if (plat === "ks" && p.view_count) parts.push(`<span title="播放">▶ ${fmtNum(p.view_count)}</span>`);
      if (p.collected_count && p.collected_count !== "0") parts.push(`<span title="收藏">⭐ ${fmtNum(p.collected_count)}</span>`);
      if (p.share_count && p.share_count !== "0") parts.push(`<span title="分享">↗ ${fmtNum(p.share_count)}</span>`);
    } else if (plat === "xhs") {
      if (p.liked_count) parts.push(`<span title="点赞">👍 ${fmtNum(p.liked_count)}</span>`);
      if (p.collected_count) parts.push(`<span title="收藏">⭐ ${fmtNum(p.collected_count)}</span>`);
      if (p.share_count) parts.push(`<span title="分享">↗ ${fmtNum(p.share_count)}</span>`);
    } else if (plat === "wb") {
      if (p.liked_count) parts.push(`<span title="点赞">👍 ${fmtNum(p.liked_count)}</span>`);
      if (p.share_count) parts.push(`<span title="转发">↗ ${fmtNum(p.share_count)}</span>`);
    } else if (plat === "zhihu") {
      if (p.liked_count) parts.push(`<span title="赞同">👍 ${fmtNum(p.liked_count)}</span>`);
    } else {
      if (p.liked_count && p.liked_count !== "0") parts.push(`<span title="点赞">👍 ${fmtNum(p.liked_count)}</span>`);
      if (p.comment_count && p.comment_count !== "0") parts.push(`<span title="评论">💬 ${fmtNum(p.comment_count)}</span>`);
      if (p.share_count && p.share_count !== "0") parts.push(`<span title="分享">↗ ${fmtNum(p.share_count)}</span>`);
    }
    if (p.comment_count && (plat === "dy" || plat === "xhs" || plat === "wb" || plat === "tieba" || plat === "zhihu")) {
      parts.push(`<span title="评论">💬 ${fmtNum(p.comment_count)}</span>`);
    }
    return parts.join('<span style="color:#d1d5db;">|</span>');
  }

  function renderComments(comments, total, hasMore) {
    if (!comments.length) {
      return `<div style="text-align:center;color:#9ca3af;padding:20px;font-size:13px;">暂无评论</div>`;
    }
    const list = comments.map(c => `
      <div class="comment-item" data-cid="${escapeAttr(c.comment_id)}" style="padding:10px 0;border-bottom:1px dashed #eee;font-size:13px;">
        <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;">
          <div>
            <span style="font-weight:600;color:#4f46e5;">${escapeHtml(c.author || "匿名")}</span>
            <span style="color:#9ca3af;font-size:11px;margin-left:6px;">${escapeHtml(c.create_time || "")}</span>
          </div>
          <div style="font-size:11px;color:#9ca3af;">👍 ${fmtNum(c.like_count)}${c.sub_comment_count && c.sub_comment_count !== "0" ? ` · 💬 ${fmtNum(c.sub_comment_count)} 子评论` : ""}</div>
        </div>
        <div style="margin-top:4px;color:#374151;word-break:break-word;line-height:1.6;">${escapeHtml(c.content || "")}</div>
        ${(c.pictures && c.pictures.length) ? `<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">${c.pictures.map(u => `<a href="${escapeAttr(u)}" target="_blank" rel="noopener"><img src="${escapeAttr(u)}" loading="lazy" style="width:64px;height:64px;object-fit:cover;border-radius:6px;" onerror="this.style.display='none';" /></a>`).join("")}</div>` : ""}
      </div>
    `).join("");
    const more = hasMore ? `<div style="text-align:center;padding:10px;color:#9ca3af;font-size:12px;">仅展示前 10 条，共 ${total} 条。完整列表请到 <b>评论</b> tab 查看。</div>` : "";
    return list + more;
  }

  function bindPostEvents() {
    $("post-list").querySelectorAll(".toggle-comments-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const pid = btn.getAttribute("data-post-id");
        if (STATE.expanded.has(pid)) STATE.expanded.delete(pid);
        else STATE.expanded.add(pid);
        renderPosts();
      });
    });
  }

  function renderPagination() {
    const totalPages = Math.max(1, Math.ceil(STATE.total / STATE.pageSize));
    const bar = $("pagination-bar");
    if (STATE.total === 0) { bar.innerHTML = ""; return; }
    let html = `<span class="label" style="margin-right:auto;">共 ${STATE.total} 条，当前第 ${STATE.page} / ${totalPages} 页</span>`;
    html += `<button class="btn btn-ghost" id="prev-btn" ${STATE.page === 1 ? "disabled" : ""}>上一页</button>`;
    const start = Math.max(1, STATE.page - 2);
    const end = Math.min(totalPages, start + 4);
    for (let i = start; i <= end; i++) {
      html += `<button class="btn ${i === STATE.page ? "btn-primary" : "btn-ghost"} page-btn" data-page="${i}">${i}</button>`;
    }
    html += `<button class="btn btn-ghost" id="next-btn" ${STATE.page === totalPages ? "disabled" : ""}>下一页</button>`;
    bar.innerHTML = html;
    bar.querySelectorAll(".page-btn").forEach(b => {
      b.addEventListener("click", () => { STATE.page = parseInt(b.getAttribute("data-page"), 10); loadPosts(); });
    });
    const prev = bar.querySelector("#prev-btn");
    const next = bar.querySelector("#next-btn");
    if (prev) prev.addEventListener("click", () => { STATE.page--; loadPosts(); });
    if (next) next.addEventListener("click", () => { STATE.page++; loadPosts(); });
  }

  function emptyHint(text) {
    return `<div style="background:#fff;border-radius:12px;padding:60px 20px;text-align:center;color:#9ca3af;box-shadow:0 2px 8px rgba(0,0,0,0.05);">
      <div style="font-size:48px;margin-bottom:10px;">📊</div>
      <div style="font-size:15px;color:#6b7280;">${escapeHtml(text)}</div>
    </div>`;
  }

  function populatePlatformSelect() {
    const sel = $("platform-select");
    sel.innerHTML = `<option value="">-- 请选择平台 --</option>` +
      STATE.platforms.map(p => `<option value="${p.value}" ${STATE.platform === p.value ? "selected" : ""}>${p.emoji} ${escapeHtml(p.label)}${p.has_data ? "" : " (无数据)"}</option>`).join("");
    sel.addEventListener("change", () => {
      STATE.platform = sel.value || null;
      STATE.page = 1;
      STATE.keyword = "";
      $("keyword-input").value = "";
      renderStats();
      loadPosts();
    });
  }

  async function loadPlatforms() {
    try {
      const data = await api("/platforms");
      STATE.platforms = data.platforms || [];
      populatePlatformSelect();
      loadStats();
    } catch (e) {
      console.error(e);
    }
  }

  function bindToolbar() {
    $("storage-select").addEventListener("change", (e) => { STATE.storage = e.target.value; STATE.page = 1; loadPosts(); });
    $("page-size-select").addEventListener("change", (e) => { STATE.pageSize = parseInt(e.target.value, 10); STATE.page = 1; loadPosts(); });
    $("search-btn").addEventListener("click", () => { STATE.keyword = $("keyword-input").value.trim(); STATE.page = 1; loadPosts(); });
    $("keyword-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("search-btn").click(); });
    $("refresh-btn").addEventListener("click", () => { loadStats(); loadPosts(); toast("已刷新"); });
    $("expand-all-btn").addEventListener("click", () => {
      STATE.posts.forEach(p => STATE.expanded.add(p.post_id));
      renderPosts();
    });
    $("collapse-all-btn").addEventListener("click", () => {
      STATE.expanded.clear();
      renderPosts();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindToolbar();
    loadPlatforms();
    $("post-list").innerHTML = emptyHint("👈 请先在上方选择平台");
  });
})();

