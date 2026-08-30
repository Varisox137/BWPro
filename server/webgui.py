"""Web GUI（Phase 4 基础框架）：单页应用 + 卡组/环境 HTTP API。

- /gui 返回静态单页（static/webgui/，纯 vanilla JS/HTML/CSS，无构建步骤）；
- /gui/api/* 提供环境目录（catalog）、卡组校验与卡组码导入导出：
  数据来自 CardDatabase + db/envs 环境解析，校验/卡组码复用 db/deck.py 与
  db/deckcode.py；
- 联机对战复用既有 /ws 协议——页面本身即一个 WebSocket 客户端（client 标识
  沿用 BWPro-CLI 前缀软门槛，见 server/main.py）；/gui 的挂载不改变
  protocol/room/manager 的任何行为。

挂载：server/main.py create_app 内 mount_webgui(app, manager.db)（须在
403 catch-all 之前注册）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db.deck import validate_deck
from db.deckcode import decode_deck, encode_deck, group_deck
from db.envs import ENV_ALIASES, env_label, parse_env_input
from db.loader import CardDatabase

STATIC_DIR = Path(__file__).parent.parent / "static" / "webgui"

# 页面引用的静态文件白名单（显式路由，不用 StaticFiles 目录挂载——保持
# main.py 的 403 catch-all 语义，不暴露目录结构）
_STATIC_FILES = {"app.js": "text/javascript", "style.css": "text/css"}


def _shiki_json(d) -> dict:
    """式神目录条目：基础数值 + 能力文本；buildable = 可进构筑池
    （kind=shikigami 且非 WIP 且非未发布，与 client/deckbuilder.available_shikigami
    同口径）。"""
    return {
        "id": d.id,
        "name": d.name,
        "kind": d.kind,
        "faction": d.faction,
        "power": d.power,
        "health": d.health,
        "text": d.text,
        "keywords": list(d.keywords),
        "unreleased": d.unreleased,
        "buildable": d.kind == "shikigami" and not d.wip and not d.unreleased,
    }


def _card_json(c) -> dict:
    """卡牌目录条目：类型/等级/费用/数值/效果文本；token=衍生卡（不可构筑，
    目录保留供对局详情查询）；unreleased=未加入游戏（哨兵日期占位，不可构筑）。"""
    return {
        "id": c.id,
        "name": c.name,
        "shikigami": c.shikigami,
        "shikigami2": c.shikigami2,
        "card_type": c.card_type,
        "subtype": c.subtype,
        "level": c.level,
        "cost": c.cost,
        "rarity": c.rarity,
        "token": c.token,
        "unreleased": c.unreleased,
        "text": c.text,
        "keywords": list(c.keywords),
        "form_power": c.form_power,
        "form_health": c.form_health,
        "intensity": c.intensity,
        "awaken_power": c.awaken_power,
        "awaken_health": c.awaken_health,
        "needs_target": c.target.kind == "choose",
        "needs_target2": c.target2 is not None and c.target2.kind == "choose",
        "options": list(c.options or []),  # 协战牌子选项卡 id（前端子选项选择用）
    }


class DeckPayload(BaseModel):
    """validate_deck / deckcode.export 的公共请求体。"""

    shikigami: list[int]
    cards: list[int]
    env: str | None = None  # 环境别名或日期（缺省 = 最新）


class DeckCodeImport(BaseModel):
    code: str
    env: str | None = None


def _parse_env(env: str | None) -> int | None:
    """解析环境查询参数；非法输入抛 400。"""
    try:
        return parse_env_input(env or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def mount_webgui(app: FastAPI, db: CardDatabase) -> None:
    """把 Web GUI 路由挂到既有 FastAPI app（db = 完整库，环境切换时 at_date 解析）。"""
    router = APIRouter()

    @router.get("/gui", include_in_schema=False)
    async def gui_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/gui/static/{filename}", include_in_schema=False)
    async def gui_static(filename: str) -> FileResponse:
        if filename not in _STATIC_FILES:
            raise HTTPException(status_code=404)
        return FileResponse(STATIC_DIR / filename,
                            media_type=_STATIC_FILES[filename])

    @router.get("/gui/api/catalog")
    async def catalog(env: str | None = None) -> dict:
        """指定环境下的可用式神与卡牌目录（构筑池 + 对局详情查询共用）。"""
        date = _parse_env(env)
        edb = db.at_date(date)
        return {
            "env": date,
            "env_label": env_label(date),
            "aliases": dict(ENV_ALIASES),
            "shikigami": [_shiki_json(d) for d in sorted(
                edb.shikigami.values(), key=lambda x: x.id)],
            "cards": [_card_json(c) for c in sorted(
                edb.cards.values(), key=lambda x: x.id)],
            # 灵咒定义表（交互选择 invocation_pick 的选项文本展示用）
            "invocations": {n: {"text": getattr(idef, "text", "") or ""}
                            for n, idef in sorted(edb.invocations.items())},
        }

    @router.post("/gui/api/validate_deck")
    async def api_validate_deck(body: DeckPayload) -> dict:
        """复用 db/deck.validate_deck 的组卡规则校验（按环境解析后的库）。"""
        edb = db.at_date(_parse_env(body.env))
        errors = validate_deck(edb, body.shikigami, body.cards)
        return {"ok": not errors, "errors": errors}

    @router.post("/gui/api/deckcode/export")
    async def api_export(body: DeckPayload) -> dict:
        """（式神列表, 卡牌列表）→ 卡组码（分组归属同 db/deckcode.group_deck）。"""
        edb = db.at_date(_parse_env(body.env))
        code = encode_deck(group_deck(edb, body.shikigami, body.cards))
        return {"code": code}

    @router.post("/gui/api/deckcode/import")
    async def api_import(body: DeckCodeImport) -> dict:
        """卡组码 → 分组结构 + 平铺列表；仅校验当前环境下的可用性
        （式神/卡牌存在且归属在队式神——构筑编辑允许非标准卡组，合法性由
        validate_deck 另行给出）。"""
        edb = db.at_date(_parse_env(body.env))
        try:
            deck = decode_deck(body.code)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        shikigami_ids = [sid for sid, _ in deck]
        card_ids = [cid for _, cards in deck for cid in cards]
        for sid in shikigami_ids:
            if sid not in edb.shikigami:
                raise HTTPException(status_code=400,
                                    detail=f"式神 {sid} 在当前环境下不存在")
        for cid in card_ids:
            c = edb.cards.get(cid)
            if c is None:
                raise HTTPException(status_code=400,
                                    detail=f"卡牌 {cid} 在当前环境下不存在")
            if c.shikigami not in shikigami_ids \
                    and getattr(c, "shikigami2", None) not in shikigami_ids:
                raise HTTPException(status_code=400,
                                    detail=f"卡牌【{c.name}】不属于出战式神")
        return {"groups": [[sid, cards] for sid, cards in deck],
                "shikigami": shikigami_ids, "cards": card_ids}

    app.include_router(router)
