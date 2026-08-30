/* BWPro Web GUI 基础框架（纯 vanilla JS，无构建步骤）。
 *
 * 三个视图：主菜单 / 卡组构筑 / 联机对战。
 * - 构筑数据来自 /gui/api/catalog（按环境解析），校验与卡组码走 /gui/api/*；
 *   卡组保存在浏览器 localStorage（键 bwpro.webgui.decks）。
 * - 联机对战是 /ws 协议的又一个客户端（client 标识沿用 BWPro-CLI 前缀软门槛）；
 *   只读渲染服务端下发的 GameState payload，指令与 CLI 同一 cmd dict 协议。
 */
"use strict";

// ---------- 全局状态 ----------
const S = {
  catalog: null,           // 当前环境的目录（含 aliases）
  cardById: {},            // 卡 id → 目录条目
  shikiById: {},           // 式神 id → 目录条目
  builder: { env: "", team: [], cards: {}, active: -1 },  // cards: {式神id: [卡id...]}
  net: {
    ws: null, roomId: null, token: null, seat: null, me: null,
    payload: null, timer: null, over: false, endedNormally: false,
    targeting: null,       // 待选目标的出牌 {cmd, effDef, mainDef, stage}
    choiceOpen: false,     // 交互选择弹窗打开中（state 更新时按 pending_choice 收口）
    server: "", name: "",
  },
};

const $ = (id) => document.getElementById(id);
const DECKS_KEY = "bwpro.webgui.decks";
// 客户端标识：服务端软门槛要求 create/join 带 BWPro-CLI 前缀（server/main.py）
const CLIENT_ID = "BWPro-CLI/webgui";

// 结算明细排版：与 client/cli.py format_settle_lines/format_timeline_lines 同口径
// （嵌套块"战斗/伤害结算 开始-结束"按层级缩进两格，结束行与开始行同级；
// 时间线叙事行 k="l" 以 "| "前缀按当前层级缩进）。纯展示排版，不含规则计算。
const SETTLE_OPEN = ["—— 战斗开始", "—— 伤害结算开始"];

function fmtSettle(lines) {
  const out = [];
  let depth = 0;
  for (const line of lines) {
    const s = line.trim();
    if (s.startsWith("—— 战斗结束") || s.startsWith("—— 伤害结算结束"))
      depth = Math.max(0, depth - 1);
    out.push(depth ? "  ".repeat(depth) + s : s);
    if (SETTLE_OPEN.some((p) => s.startsWith(p))) depth += 1;
  }
  return out;
}

function fmtTimeline(entries) {
  const out = [];
  let depth = 0;
  for (const e of entries) {
    const s = (e.m || "").trim();
    if (e.k === "l") { out.push((depth ? "  ".repeat(depth) : "  ") + "| " + s); continue; }
    if (s.startsWith("—— 战斗结束") || s.startsWith("—— 伤害结算结束"))
      depth = Math.max(0, depth - 1);
    out.push(depth ? "  ".repeat(depth) + s : s);
    if (SETTLE_OPEN.some((p) => s.startsWith(p))) depth += 1;
  }
  return out;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function showView(name) {
  for (const v of document.querySelectorAll(".view")) v.classList.add("hidden");
  $("view-" + name).classList.remove("hidden");
}

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
  return data;
}

// ---------- 目录 ----------

async function loadCatalog(env) {
  const data = await api("/gui/api/catalog" + (env ? "?env=" + encodeURIComponent(env) : ""));
  S.catalog = data;
  S.cardById = {};
  for (const c of data.cards) S.cardById[c.id] = c;
  S.shikiById = {};
  for (const s of data.shikigami) S.shikiById[s.id] = s;
  return data;
}

// ---------- 卡组构筑 ----------

function builderCardsOf(sid) {
  // 某式神全部可构筑卡：本家卡在前，作为第二所属式神的协战牌列最后
  // （与 client/deckbuilder.buildable_cards 同口径）
  const own = [], second = [];
  for (const c of S.catalog.cards) {
    if (c.token || c.unreleased) continue;
    if (c.shikigami === sid) own.push(c);
    else if (c.card_type === "reinforce" && c.shikigami2 === sid) second.push(c);
  }
  return own.concat(second);
}

function renderBuilder() {
  // 式神池
  const pool = $("shiki-pool");
  pool.innerHTML = "";
  for (const s of S.catalog.shikigami) {
    if (!s.buildable) continue;
    const item = el("div", "item");
    item.append(el("span", null, s.name));
    item.append(el("span", "sub",
      `${s.faction} ${s.power}/${s.health} — ${s.text || "（无能力）"}`));
    item.onclick = () => {
      if (S.builder.team.includes(s.id)) return;
      if (S.builder.team.length >= 4) { builderMsg("出战式神至多 4 名", true); return; }
      S.builder.team.push(s.id);
      S.builder.cards[s.id] = S.builder.cards[s.id] || [];
      if (S.builder.active < 0) S.builder.active = s.id;
      renderBuilder();
    };
    pool.append(item);
  }
  // 队伍槽位
  const slots = $("team-slots");
  slots.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const sid = S.builder.team[i];
    const slot = el("div", "team-slot" + (sid === S.builder.active ? " active" : ""));
    if (sid) {
      const s = S.shikiById[sid];
      slot.append(el("div", null, s ? s.name : sid));
      slot.append(el("span", "sub", `已配 ${(S.builder.cards[sid] || []).length}/8 张（右键移除）`));
      slot.onclick = () => { S.builder.active = sid; renderBuilder(); };
      slot.oncontextmenu = (ev) => {
        ev.preventDefault();
        S.builder.team.splice(i, 1);
        delete S.builder.cards[sid];
        if (S.builder.active === sid) S.builder.active = S.builder.team[0] ?? -1;
        renderBuilder();
      };
    } else {
      slot.append(el("span", "sub", "（空槽位）"));
    }
    slots.append(slot);
  }
  // 卡牌池（当前槽位式神）
  const cp = $("card-pool");
  cp.innerHTML = "";
  const sid = S.builder.active;
  $("card-pool-title").textContent = sid > 0 && S.shikiById[sid]
    ? `卡牌池：${S.shikiById[sid].name}（点击加入卡组）` : "卡牌池（先选中上方槽位）";
  if (sid > 0 && S.shikiById[sid]) {
    for (const c of builderCardsOf(sid)) {
      const item = el("div", "item");
      item.append(el("span", null,
        `【${c.name}】${c.card_type === "reinforce" ? "☆协战 " : ""}`));
      item.append(el("span", "sub",
        `${typeLabel(c)} Lv${c.level} 费${c.cost} — ${c.text || ""}`));
      item.onclick = () => {
        const list = S.builder.cards[sid];
        if (list.length >= 8) { builderMsg("每名式神恰好 8 张牌", true); return; }
        if (list.filter((x) => x === c.id).length >= 2)
          builderMsg(`提示：《${c.name}》已超过同名限 2（仅提示，不强制）`, true);
        list.push(c.id);
        renderBuilder();
      };
      cp.append(item);
    }
  }
  // 当前卡组
  const dl = $("deck-list");
  dl.innerHTML = "";
  for (const sid2 of S.builder.team) {
    const s = S.shikiById[sid2];
    dl.append(el("div", null, `—— ${s ? s.name : sid2} ——`));
    const counts = {};
    for (const cid of S.builder.cards[sid2] || []) counts[cid] = (counts[cid] || 0) + 1;
    for (const [cid, n] of Object.entries(counts)) {
      const c = S.cardById[cid];
      const entry = el("div", "deck-entry");
      entry.append(el("span", null, `${c ? c.name : cid} ×${n}`));
      entry.append(el("span", "sub", "点击移除一张"));
      entry.onclick = () => {
        const list = S.builder.cards[sid2];
        list.splice(list.indexOf(Number(cid)), 1);
        renderBuilder();
      };
      dl.append(entry);
    }
  }
  renderSavedDecks();
}

function typeLabel(c) {
  return { spell: "法术", form: "形态", combat: "战斗", field: "幻境",
           reinforce: "协战" }[c.card_type] || c.card_type;
}

function builderMsg(text, isErr) {
  const box = $("deck-validate-result");
  box.textContent = text;
  box.className = "msg" + (isErr ? " err" : "");
}

function deckFlat() {
  const cards = [];
  for (const sid of S.builder.team) cards.push(...(S.builder.cards[sid] || []));
  return { shikigami: S.builder.team.slice(), cards, env: S.builder.env || null };
}

function loadSavedDecks() {
  try { return JSON.parse(localStorage.getItem(DECKS_KEY) || "[]"); }
  catch { return []; }
}

function storeSavedDecks(list) {
  localStorage.setItem(DECKS_KEY, JSON.stringify(list));
}

function renderSavedDecks() {
  const box = $("saved-decks");
  box.innerHTML = "";
  for (const [i, d] of loadSavedDecks().entries()) {
    const row = el("div", "saved");
    row.append(el("span", null, d.name));
    const load = el("button", null, "载入");
    load.onclick = () => {
      S.builder.team = d.shikigami.slice();
      S.builder.cards = {};
      for (const sid of d.shikigami) S.builder.cards[sid] = (d.cards[sid] || []).slice();
      S.builder.active = S.builder.team[0] ?? -1;
      renderBuilder();
    };
    const del = el("button", null, "删除");
    del.onclick = () => {
      const list = loadSavedDecks();
      list.splice(i, 1);
      storeSavedDecks(list);
      renderSavedDecks();
      renderNetDeckSelect();
    };
    row.append(load, del);
    box.append(row);
  }
}

async function initBuilder() {
  // 环境下拉：标准(最新) + 目录中的别名登记表
  const sel = $("builder-env");
  sel.innerHTML = "";
  sel.append(new Option("标准(最新)", ""));
  for (const alias of Object.keys(S.catalog.aliases)) sel.append(new Option(alias, alias));
  sel.value = S.builder.env;
  renderBuilder();
}

// ---------- 联机对战 ----------

function normalizeServerUrl(raw) {
  // 与 client/net.py normalize_server_url 同口径
  let s = raw.trim();
  if (s.startsWith("https://")) s = "wss://" + s.slice(8);
  else if (s.startsWith("http://")) s = "ws://" + s.slice(7);
  if (!s.startsWith("ws://") && !s.startsWith("wss://")) {
    const host = s.split("/")[0];
    s = (host.includes(":") ? "ws://" : "wss://") + s;
  }
  if (!s.split("://")[1].includes("/")) s += "/ws";
  return s;
}

function netMsg(text, isErr) {
  const box = $("net-status");
  box.textContent = text;
  box.className = "msg" + (isErr ? " err" : "");
}

function gameMsg(text, isErr) {
  const box = $("game-msg");
  box.textContent = text;
  box.className = "msg" + (isErr ? " err" : "");
}

function renderNetDeckSelect() {
  const sel = $("net-deck");
  sel.innerHTML = "";
  const decks = loadSavedDecks();
  if (!decks.length) sel.append(new Option("（无本地卡组，请先在卡组构筑保存）", ""));
  for (const d of decks) sel.append(new Option(d.name, d.name));
}

function netSend(msg) {
  S.net.ws.send(JSON.stringify(msg));
}

function netCmd(cmd) {
  netSend({ type: "cmd", cmd });
}

function connectAnd(helloFactory) {
  const n = S.net;
  const deckName = $("net-deck").value;
  const deck = loadSavedDecks().find((d) => d.name === deckName);
  n.server = normalizeServerUrl($("net-server").value || location.host);
  n.name = $("net-name").value.trim() || "玩家";
  let hello;
  try {
    hello = helloFactory(deck);
  } catch (e) {
    netMsg(String(e), true);
    return;
  }
  hello.client = CLIENT_ID;
  let ws;
  try {
    ws = new WebSocket(n.server);
  } catch (e) {
    netMsg("无法连接：" + e, true);
    return;
  }
  n.ws = ws;
  n.over = false;
  n.endedNormally = false;
  netMsg("连接中……");
  ws.onopen = () => netSend(hello);
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleNet(msg);
  };
  ws.onclose = () => {
    if (!n.endedNormally && !n.over) {
      netMsg("与服务器连接已断开");
      $("btn-reconnect").classList.remove("hidden");
    }
  };
  ws.onerror = () => netMsg("连接失败（地址/服务不可达）", true);
}

function handleNet(msg) {
  const n = S.net;
  const t = msg.type;
  if (t === "joined") {
    n.roomId = msg.room_id;
    n.token = msg.token;
    n.seat = msg.seat;
    if (msg.player_index !== undefined) n.me = msg.player_index;  // 重连补发
    netMsg(`已加入房间 ${n.roomId}（重连令牌：${n.token}），等待对手……`);
    $("net-lobby-form").classList.add("hidden");
    $("net-lobby").classList.remove("hidden");
    $("lobby-info").textContent = `房间 ${n.roomId}：等待对手加入`;
  } else if (t === "lobby") {
    const ready = msg.ready || [];
    $("lobby-info").textContent =
      `房间 ${n.roomId}（${msg.mode === "free" ? "自由" : "标准"}模式）双方已就位：` +
      (ready.includes(n.name) ? "你已准备，等待对手" : "点击「准备」开始") +
      `（已准备 ${ready.length}/2）`;
  } else if (t === "starting") {
    $("lobby-info").textContent = "双方已准备，对局即将开始……";
  } else if (t === "peer_left") {
    $("lobby-info").textContent = `${msg.name} 已离开，等待新对手加入`;
  } else if (t === "left" || t === "dissolved") {
    n.endedNormally = true;
    netMsg(t === "left" ? "已离开房间" : `房间已解散（${msg.reason || ""}）`);
    resetBattleUI();
  } else if (t === "start") {
    n.me = msg.player_index;
    $("net-lobby").classList.add("hidden");
    $("net-game").classList.remove("hidden");
    gameMsg(`对局开始：你是${msg.you_first ? "先手" : "后手"}，对手：${msg.opponent}`);
  } else if (t === "state") {
    n.payload = msg.payload;
    n.timer = msg.timer || null;
    // 结算播放：合并时间线（结算/叙事按真实发生顺序合流）优先，旧字段
    // settle+log 兜底（断线重连 resync 只发全量 payload+log）——与 CLI 联机端同口径
    if (msg.timeline && msg.timeline.length) appendLog(fmtTimeline(msg.timeline));
    else {
      if (msg.settle && msg.settle.length) appendLog(fmtSettle(msg.settle));
      if (msg.log) appendLog(msg.log.map((l) => "  | " + l));
    }
    renderGame();
  } else if (t === "error") {
    gameMsg("无效操作: " + (msg.reason || ""), true);
    n.targeting = null;
    renderGame();
  } else if (t === "notice") {
    appendLog(["** " + msg.text]);
  } else if (t === "game_over") {
    n.over = true;
    n.endedNormally = true;
    const w = msg.winner;
    const names = n.payload ? n.payload.players.map((p) => p.name) : [];
    appendLog(["***** " + (w === null ? `对局终止（${msg.reason}）`
      : (w === n.me ? "你赢了！" : `${names[w] || w} 获胜`)) + " *****"]);
    gameMsg("对局结束");
  }
}

function resetBattleUI() {
  $("net-lobby").classList.add("hidden");
  $("net-game").classList.add("hidden");
  $("net-lobby-form").classList.remove("hidden");
  $("btn-reconnect").classList.add("hidden");
  S.net.payload = null;
  S.net.me = null;
  renderNetDeckSelect();
}

function appendLog(lines) {
  const box = $("game-log");
  for (const line of lines) box.append(el("div", null, line));
  box.scrollTop = box.scrollHeight;
}

// ---------- 对局渲染 ----------

// 有效力量/生命上限：与 core/model.py ShikigamiState.eff_power/max_health 同口径
// （基础 + 永久 + 临时 + 战斗战力 + 动态光环缓存 + 灵咒层）
function effPower(s) {
  if (s.ext && s.ext.power_zero) return 0;
  let p = s.base_power + s.perm_power + s.temp_power + s.combat_power
        + ((s.ext && s.ext.dyn_power) || 0);
  for (const e of s.invocations || [])
    p += (e.power || 0) + (e.bonus || 0) + (e.mod_power || 0);
  return p;
}
function maxHealthOf(s) {
  let h = s.base_health + s.perm_health + s.temp_health
        + ((s.ext && s.ext.dyn_health) || 0);
  for (const e of s.invocations || [])
    h += (e.health || 0) + (e.bonus || 0) + (e.mod_health || 0);
  return h;
}

function myTurn() {
  const n = S.net, pl = n.payload;
  return pl && n.me !== null && pl.active === n.me && pl.phase === "battle";
}

function renderGame() {
  const n = S.net, pl = n.payload;
  if (!pl || n.me === null) return;
  const me = pl.players[n.me], opp = pl.players[1 - n.me];
  // 顶栏
  const phaseLabel = { mulligan: "调度阶段", upgrade: "升级阶段", battle: "对战阶段" }[pl.phase] || pl.phase;
  $("game-topbar").textContent =
    `房间 ${n.roomId} · ${phaseLabel} · 总第 ${Math.max(0, pl.turn - 1)} 回合 · ` +
    (pl.active === n.me ? "你的回合" : "对手行动中") +
    (n.timer ? ` · ⏱ ${fmtTimer(n.timer)}` : "");
  // 牌手卡
  renderPlayerCard($("opp-player"), opp, 1 - n.me);
  renderPlayerCard($("my-player"), me, n.me);
  // 式神行
  renderShikiRow($("opp-shiki"), opp, 1 - n.me, false);
  renderShikiRow($("my-shiki"), me, n.me, true);
  // 手牌
  renderHand(me);
  // 阶段按钮
  const mull = pl.phase === "mulligan" && !me.mulligan_done;
  $("btn-mulligan-done").classList.toggle("hidden", !mull);
  $("btn-end-turn").disabled = !myTurn();
  // 待选目标提示
  if (n.targeting) gameMsg(
    (n.targeting.stage === 2 ? "选择第二目标" : "选择目标") +
    "中：点击式神或牌手（右键取消）");
  // 结算中交互选择
  renderPendingChoice();
}

function fmtTimer(timer) {
  const left = Math.max(0, (timer.deadline || 0) - Date.now() / 1000);
  const m = Math.floor(left / 60), s = Math.floor(left % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function renderPlayerCard(box, p, pi) {
  box.innerHTML = "";
  box.append(el("span", null,
    `${p.name} · 生命 ${p.health}/${p.max_health}` +
    (p.shield ? ` 护甲${p.shield}` : "") + ` 鬼火 ${p.orb}` +
    ` 手牌 ${(p.zones.hand || []).length} 牌库 ${(p.zones.deck || []).length}`));
  box.onclick = () => {
    if (S.net.targeting) { playWithTarget({ player: pi, shikigami: null }); return; }
    showPlayerDetail(p);
  };
  box.classList.toggle("targetable", !!S.net.targeting);
}

function renderShikiRow(box, p, pi, mine) {
  box.innerHTML = "";
  const pl = S.net.payload;
  p.shikigami.forEach((s, i) => {
    const def = S.shikiById[s.id];
    const tile = el("div", "shiki" +
      (s.defeated ? " defeated" : "") +
      (p.combat_index === i ? " combat" : "") +
      (S.net.targeting ? " targetable" : ""));
    tile.append(el("div", null, `${def ? def.name : s.id}` +
      (s.defeated ? `（气绝 ${s.revive_countdown}）` : "")));
    tile.append(el("div", "stats",
      `${effPower(s)}/${s.health}` + (s.shield ? ` 甲${s.shield}` : "")));
    tile.append(el("span", "lvl", "Lv" + s.level));
    const kws = (s.keywords || []).concat(s.one_shot_keywords || [], s.perm_keywords || []);
    if (kws.length) tile.append(el("div", "kw", kws.join(" ")));
    tile.onclick = () => {
      if (S.net.targeting) { playWithTarget({ player: pi, shikigami: i }); return; }
      showShikiDetail(s, def);
    };
    tile.oncontextmenu = (ev) => { ev.preventDefault(); cancelTargeting(); };
    if (mine) {
      // 拖拽出击：拖到敌方区域 = {"op":"assault","index":i}
      tile.draggable = true;
      tile.ondragstart = (ev) => ev.dataTransfer.setData("text/assault", String(i));
      // 升级阶段：可升级式神附升级按钮（合法性交服务端校验）
      if (pl.phase === "upgrade" && pl.active === S.net.me && !s.defeated) {
        const up = el("button", null, "升级");
        up.onclick = (ev) => { ev.stopPropagation(); netCmd({ op: "upgrade", index: i }); };
        tile.append(up);
      }
    }
    box.append(tile);
  });
}

function handInfo(uid) {
  // 服务端随 state 下发的己方手牌实时信息（hand_info，键为 uid 字符串）：
  // 费用/关键字/数值段/增强/委托进度/使用方式枚举，全部为引擎求值结果
  const pl = S.net.payload;
  return ((pl && pl.hand_info) || {})[String(uid)] || null;
}

function usageLabel(usage) {
  // 使用方式段：与 client/cli.py format_hand_lines 的 _usage_label 同口径
  // （常规仅在不可用或多方式时占版面；多择方式/协战子选项逐条 ✓/✗原因+耗能）
  const parts = [];
  for (const u of usage || []) {
    const mark = u.ok ? "✓" : `✗${u.reason || ""}`;
    const energy = u.energy ? `耗能${u.energy}` : "";
    if (u.id === null || u.id === undefined) {
      if (usage.length === 1 && u.ok) continue;
      parts.push(`常规${energy}${mark}`);
    } else if (String(u.id).startsWith("choice:")) {
      parts.push(`子选项【${u.label}】${mark}`);
    } else {
      parts.push(`「${u.label}」${energy}${mark}`);
    }
  }
  return parts.join(" ");
}

function renderHand(me) {
  const row = $("hand-row");
  row.innerHTML = "";
  const pl = S.net.payload;
  const mull = pl.phase === "mulligan" && !me.mulligan_done;
  for (const c of (me.zones.hand || [])) {
    const def = S.cardById[c.id];
    const info = handInfo(c.uid);
    const box = el("div", "hand-card" + (info && !info.playable ? " unplayable" : ""));
    const cost = info ? info.cost : (def ? def.cost : 0);
    box.append(el("div", null, `【${def ? def.name : c.id}】` +
      ` <span class="cost">费${cost}</span>`));
    if (def) box.append(el("div", "sub", `${typeLabel(def)} Lv${def.level}`));
    if (info) {
      const dataParts = [];
      if (info.keywords && info.keywords.length)
        dataParts.push(`[${info.keywords.join("/")}]`);
      if (info.enhance) dataParts.push(`增强+${info.enhance}`);
      if (info.quest) dataParts.push(info.quest);
      if (dataParts.length) box.append(el("div", "kw", dataParts.join(" ")));
      if (info.stats) box.append(el("div", "stats", info.stats));
      if (!mull && pl.phase === "battle") {  // 使用方式列（调度阶段不显示，同 CLI）
        const u = usageLabel(info.usage);
        if (u) box.append(el("div", "usage", u));
      }
    }
    box.onclick = () => {
      if (mull) return;  // 调度阶段用按钮调度，不出牌
      if (!myTurn()) { showCardDetail(def); return; }
      if (!def) return;
      startPlayFlow(c, def);
    };
    box.oncontextmenu = (ev) => { ev.preventDefault(); showCardDetail(def); };
    if (mull) {
      const btn = el("button", null, "调度");
      btn.onclick = (ev) => { ev.stopPropagation(); netCmd({ op: "mulligan", uid: c.uid }); };
      box.append(btn);
    }
    row.append(box);
  }
}

// ---------- 出牌流程（使用方式 → 子选项 → 目标 → 第二目标） ----------

function startPlayFlow(c, def) {
  // 出牌入口：按服务端 usage 枚举决定路径（协战牌子选项 / 多择使用方式 / 常规），
  // 再按需收集目标与第二目标（target2）。合法性交服务端校验。
  const info = handInfo(c.uid);
  const usage = info ? info.usage : [{ id: null, ok: true, cost: def.cost }];
  if (def.card_type === "reinforce") {
    // 协战牌子选项（裁决(16)）：列出全部子选项（含不合法者与原因）
    const subs = usage.filter((u) => String(u.id).startsWith("choice:"));
    if (!subs.length) { beginPlay({ uid: c.uid }, def, def); return; }  // 兜底直发
    showUsagePicker(def, subs, (u) => {
      const idx = Number(String(u.id).split(":")[1]);
      const sub = S.cardById[(def.options || [])[idx]] || null;
      beginPlay({ uid: c.uid, choice: idx }, sub, def);
    });
    return;
  }
  const methods = usage.filter((u) => u.id !== null && u.id !== undefined);
  if (!methods.length) {
    const normal = usage[0];
    if (normal && !normal.ok) {
      gameMsg(`无法使用【${def.name}】：${normal.reason || ""}`, true);
      return;
    }
    beginPlay({ uid: c.uid }, def, def);
    return;
  }
  // 多择使用方式（爆能等）：常规 + 各方式逐条列出（含不合法原因）
  showUsagePicker(def, usage, (u) => {
    const cmd = { uid: c.uid };
    if (u.id !== null && u.id !== undefined) cmd.play_method = u.id;
    beginPlay(cmd, def, def);
  });
}

function showUsagePicker(def, usage, onPick) {
  // 使用方式/协战子选项选择弹窗：合法性交服务端校验，不合法项灰显并附原因
  const body = $("modal-body");
  body.innerHTML = "";
  body.append(el("h3", null, `使用【${def.name}】`));
  for (const u of usage) {
    const isSub = String(u.id).startsWith("choice:");
    const head = (u.id === null || u.id === undefined) ? "常规"
      : isSub ? `子选项【${u.label}】` : `「${u.label}」`;
    const energy = u.energy ? ` 耗能${u.energy}` : "";
    const btn = el("button", "choice",
      `${head}（费${u.cost}${energy}）` +
      (u.ok ? "" : ` —— 不可选：${u.reason || ""}`) +
      (u.effect ? `\n${u.effect}` : ""));
    btn.disabled = !u.ok;
    btn.onclick = () => { closeModal(); onPick(u); };
    body.append(btn);
  }
  const cancel = el("button", null, "取消");
  cancel.onclick = closeModal;
  body.append(el("div", null, ""), cancel);
  $("modal").classList.remove("hidden");
}

function beginPlay(cmd, effDef, mainDef) {
  // 方式/子选项已定：effDef 的目标（协战牌 = 子选项卡目标），mainDef 的第二目标
  if (effDef && effDef.needs_target) {
    S.net.targeting = { cmd, effDef, mainDef, stage: 1 };
    renderGame();
  } else if (mainDef && mainDef.needs_target2) {
    S.net.targeting = { cmd, effDef, mainDef, stage: 2 };
    renderGame();
  } else {
    netCmd(Object.assign({ op: "play_card" }, cmd));
  }
}

function playWithTarget(ref) {
  const t = S.net.targeting;
  if (!t) return;
  if (t.stage === 1) {
    t.cmd.target = ref;
    if (t.mainDef && t.mainDef.needs_target2) {
      t.stage = 2;  // 双选择目标卡（target2）：继续收集第二目标
      renderGame();
      return;
    }
  } else {
    t.cmd.target2 = ref;
  }
  S.net.targeting = null;
  netCmd(Object.assign({ op: "play_card" }, t.cmd));
}

function cancelTargeting() {
  S.net.targeting = null;
  renderGame();
}

// 结算中交互选择（pending_choice）的作答键与标题：按 CLI 联机端分支对齐
// （client/net.py input_loop pending_choice 段）——card_name/field_summon_pick/
// pick_generate/invocation_pick 作答键为 choice（数据 id 或灵咒名），
// discard_pick/quest_complete_pick 与默认（检视牌库顶）为 uid（实例 uid）。
const PEND_CHOICE_KINDS = new Set(
  ["card_name", "field_summon_pick", "pick_generate", "invocation_pick"]);
const PEND_TITLES = {
  discard_pick: "弃置手牌：选择一张弃置",
  field_summon_pick: "选择要召唤的幻境",
  pick_generate: "选择一张牌置入手牌",
  quest_complete_pick: "选择一张紧急委托使其视为达成",
  invocation_pick: "选择一张灵咒牌结附",
};

function pendTitle(pend) {
  if (pend.kind === "card_name")
    return pend.stage === "shikigami" ? "选择敌方式神" : "选择一张牌名";
  return PEND_TITLES[pend.kind] || "检视牌库顶：选择一张置入手牌";
}

function renderPendingChoice() {
  // 结算中交互选择（青灯夜谈检视/弃牌/生成选取等）：通用列出选项作答
  const pl = S.net.payload, n = S.net;
  const pend = pl.pending_choice;
  if (!pend || pend.player !== n.me) {
    if (pend) gameMsg("等待对方完成交互选择");
    if (n.choiceOpen) { n.choiceOpen = false; closeModal(); }  // 作答完毕/视角不符时收口
    return;
  }
  const body = $("modal-body");
  body.innerHTML = "";
  body.append(el("h3", null, pendTitle(pend)));
  for (const opt of pend.options || []) {
    const label = choiceLabel(opt, pend);
    const btn = el("button", "choice", label);
    btn.onclick = () => {
      n.choiceOpen = false;
      closeModal();
      netCmd(choiceCmd(opt, pend));
    };
    body.append(btn);
  }
  n.choiceOpen = true;
  $("modal").classList.remove("hidden");
}

function choiceLabel(opt, pend) {
  const me = S.net.payload.players[S.net.me];
  const zones = (me.zones.hand || []).concat(me.zones.deck || []);
  const inst = zones.find((c) => c.uid === opt);
  if (inst) { const d = S.cardById[inst.id]; return d ? `【${d.name}】 ${d.text || ""}` : String(opt); }
  if (pend.kind === "card_name" && pend.stage === "shikigami" && S.shikiById[opt])
    return S.shikiById[opt].name;  // 忘忧的旋律第一级：敌方式神
  if (typeof opt === "number" && S.cardById[opt])
    return `【${S.cardById[opt].name}】 ${S.cardById[opt].text || ""}`;
  if (pend.kind === "invocation_pick") {
    const inv = ((S.catalog && S.catalog.invocations) || {})[opt];
    return `【${opt}】` + (inv && inv.text ? ` ${inv.text}` : "");
  }
  if (typeof opt === "number" && S.shikiById[opt]) return S.shikiById[opt].name;
  return String(opt);
}

function choiceCmd(opt, pend) {
  // 作答键判定：choice 键 kind 直接作答；uid 键 kind 与默认（检视牌库顶等）
  // 以选项命中己方手牌/牌库实例 uid 为准
  if (PEND_CHOICE_KINDS.has(pend.kind)) return { op: "choose", choice: opt };
  const me = S.net.payload.players[S.net.me];
  const zones = (me.zones.hand || []).concat(me.zones.deck || []);
  if (zones.some((c) => c.uid === opt)) return { op: "choose", uid: opt };
  return { op: "choose", choice: opt };
}

// ---------- 详情弹窗 ----------

function showModal(title, lines) {
  const body = $("modal-body");
  body.innerHTML = "";
  body.append(el("h3", null, title));
  for (const line of lines) body.append(el("div", null, line));
  const close = el("button", null, "关闭");
  close.onclick = closeModal;
  body.append(el("div", null, ""), close);
  $("modal").classList.remove("hidden");
}

function closeModal() { $("modal").classList.add("hidden"); }

function showCardDetail(def) {
  if (!def) return;
  showModal(`【${def.name}】`, [
    `${typeLabel(def)} · Lv${def.level} · 费${def.cost}` +
      (def.rarity ? ` · ${def.rarity}` : "") + (def.subtype ? ` · ${def.subtype}` : ""),
    def.keywords && def.keywords.length ? "关键字：" + def.keywords.join(" ") : "",
    def.text || "（无效果文本）",
  ].filter(Boolean));
}

function showShikiDetail(s, def) {
  showModal(def ? def.name : String(s.id), [
    `力量 ${effPower(s)}（基础 ${s.base_power}） · 生命 ${s.health}/${maxHealthOf(s)}` +
      (s.shield ? ` · 护甲 ${s.shield}` : ""),
    `等级 ${s.level}` + (s.defeated ? ` · 气绝（复活倒计时 ${s.revive_countdown}）` : "") +
      (s.form ? ` · 形态【${(S.cardById[s.form.id] || {}).name || s.form.id}】` : "") +
      (s.awakened ? " · 已觉醒" : ""),
    def && def.text ? def.text : "",
  ].filter(Boolean));
}

function showPlayerDetail(p) {
  showModal(p.name, [
    `生命 ${p.health}/${p.max_health}` + (p.shield ? ` · 护甲 ${p.shield}` : ""),
    `鬼火 ${p.orb} · 手牌 ${(p.zones.hand || []).length} · 牌库 ${(p.zones.deck || []).length}` +
      ` · 墓地 ${(p.zones.graveyard || []).length}`,
  ]);
}

// ---------- 事件绑定 ----------

function init() {
  $("btn-goto-builder").onclick = async () => {
    try {
      if (!S.catalog) await loadCatalog(S.builder.env);
      await initBuilder();
      showView("builder");
    } catch (e) { alert("目录加载失败：" + e); }
  };
  $("btn-goto-battle").onclick = async () => {
    try {
      if (!S.catalog) await loadCatalog("");
      renderNetDeckSelect();
      $("net-server").value = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
      showView("battle");
    } catch (e) { alert("目录加载失败：" + e); }
  };
  for (const b of document.querySelectorAll("[data-back]"))
    b.onclick = () => { showView("menu"); };

  // 构筑
  $("builder-env").onchange = async (ev) => {
    S.builder.env = ev.target.value;
    try { await loadCatalog(S.builder.env); renderBuilder(); }
    catch (e) { builderMsg("环境解析失败：" + e, true); }
  };
  $("btn-deck-validate").onclick = async () => {
    try {
      const r = await api("/gui/api/validate_deck", deckFlat());
      builderMsg(r.ok ? "✓ 卡组合法" : "✗ 卡组不合法：\n" + r.errors.join("\n"), !r.ok);
    } catch (e) { builderMsg("校验失败：" + e, true); }
  };
  $("btn-deck-export").onclick = async () => {
    try {
      const r = await api("/gui/api/deckcode/export", deckFlat());
      $("deck-code-box").value = r.code;
      builderMsg("已导出卡组码");
    } catch (e) { builderMsg("导出失败：" + e, true); }
  };
  $("btn-deck-import").onclick = async () => {
    try {
      const r = await api("/gui/api/deckcode/import",
        { code: $("deck-code-box").value, env: S.builder.env || null });
      S.builder.team = r.shikigami;
      S.builder.cards = {};
      for (const [sid, cards] of r.groups) S.builder.cards[sid] = cards;
      S.builder.active = S.builder.team[0] ?? -1;
      renderBuilder();
      builderMsg("导入完成（合法性请点「校验卡组」确认）");
    } catch (e) { builderMsg("导入失败：" + e, true); }
  };
  $("btn-deck-save").onclick = async () => {
    const name = $("deck-name").value.trim();
    if (!name) { builderMsg("请先填写卡组名", true); return; }
    let code = null;
    try {
      code = (await api("/gui/api/deckcode/export", deckFlat())).code;
    } catch (e) { builderMsg("卡组码导出失败：" + e, true); return; }
    const list = loadSavedDecks().filter((d) => d.name !== name);
    list.push({ name, env: S.builder.env, shikigami: S.builder.team.slice(),
                cards: S.builder.cards, code });
    storeSavedDecks(list);
    builderMsg(`已保存「${name}」到浏览器本地`);
    renderSavedDecks();
  };

  // 联机
  $("btn-room-create").onclick = () => connectAnd((deck) => {
    if (!deck) throw new Error("请选择本地卡组");
    const room = $("net-room").value.trim();
    const hello = { type: "create", name: S.net.name, deck_code: deck.code };
    if (room) hello.room_id = room;
    return hello;
  });
  $("btn-room-join").onclick = () => connectAnd((deck) => {
    const room = $("net-room").value.trim();
    if (!room) throw new Error("请填写房间代码");
    const token = $("net-token").value.trim();
    if (!token && !deck) throw new Error("请选择本地卡组（重连凭令牌可免）");
    return { type: "join", room_id: room, name: S.net.name,
             deck_code: token ? null : deck.code, token: token || null };
  });
  $("btn-ready").onclick = () => netSend({ type: "ready" });
  $("btn-leave").onclick = () => netSend({ type: "leave" });
  $("btn-end-turn").onclick = () => netCmd({ op: "end_turn" });
  $("btn-mulligan-done").onclick = () => netCmd({ op: "ready" });
  $("btn-reconnect").onclick = () => {
    // 断线重连：协议已支持（join 带 房间id+token，重连令牌免卡组码）
    $("btn-reconnect").classList.add("hidden");
    connectAnd(() => ({ type: "join", room_id: S.net.roomId, name: S.net.name,
                        deck_code: null, token: S.net.token }));
  };
  // 拖拽出击落点：拖到敌方区域 = 出击指令
  const enemyArea = $("opponent-area");
  enemyArea.ondragover = (ev) => {
    ev.preventDefault();
    enemyArea.classList.add("drop-hover");
  };
  enemyArea.ondragleave = () => enemyArea.classList.remove("drop-hover");
  enemyArea.ondrop = (ev) => {
    ev.preventDefault();
    enemyArea.classList.remove("drop-hover");
    const idx = ev.dataTransfer.getData("text/assault");
    if (idx !== "") netCmd({ op: "assault", index: Number(idx) });
  };
  $("modal").onclick = (ev) => { if (ev.target === $("modal")) closeModal(); };
  // 倒计时逐秒刷新
  setInterval(() => {
    if (S.net.payload && S.net.timer) renderGame();
  }, 1000);
}

init();
