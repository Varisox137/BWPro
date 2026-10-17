"""BWPro 桌面 GUI 界面初稿生成（一次性设计工具，PIL 绘制线框稿）。

用法（需要 Pillow，BWPro 本体暂不依赖，可用 BWPDIY 的 venv 跑）：
    python docs/gui-mock/generate.py
输出：docs/gui-mock/0x_*.png（1600x900 线框稿）。
对局相关界面参照 gui_ref/ 原版游戏截图布局（不入库）。
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 1600, 900

# 配色：夜樱深紫底 + 金/紫点缀；座次色同 CLI 语义
BG = (20, 17, 33)
PANEL = (35, 30, 58)
PANEL2 = (44, 38, 72)
LINE = (86, 76, 128)
GOLD = (201, 168, 106)
PURPLE = (140, 120, 200)
TEXT = (232, 228, 240)
DIM = (150, 144, 172)
BLUE = (90, 160, 220)      # 标准卡组亮蓝
GREEN = (120, 200, 140)
SEAT = [(216, 194, 106), (106, 192, 200), (169, 138, 216), (216, 122, 122)]

def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)

F12, F14, F16, F18, F22, F28, F40 = (font(s) for s in (12, 14, 16, 18, 22, 28, 40))

def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)

def box(d, xy, fill=PANEL, outline=LINE, width=1, r=10):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)

def ctext(d, cx, y, s, f, fill=TEXT):
    d.text((cx, y), s, font=f, fill=fill, anchor="ma")

def button(d, xy, label, f=F18, fill=PANEL2, outline=GOLD, tfill=TEXT):
    box(d, xy, fill=fill, outline=outline, width=2, r=8)
    x1, y1, x2, y2 = xy
    d.text(((x1 + x2) / 2, (y1 + y2) / 2), label, font=f, fill=tfill, anchor="mm")

def card(d, xy, name, sub="", outline=LINE, tfill=TEXT):
    box(d, xy, fill=PANEL2, outline=outline, width=2, r=6)
    x1, y1, x2, y2 = xy
    d.text(((x1 + x2) / 2, (y1 + y2) / 2 - (8 if sub else 0)), name, font=F14, fill=tfill, anchor="mm")
    if sub:
        d.text(((x1 + x2) / 2, (y1 + y2) / 2 + 14), sub, font=F12, fill=DIM, anchor="mm")

def diamond(d, cx, cy, r, label, color):
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
              fill=PANEL2, outline=color, width=3)
    d.text((cx, cy), label, font=F16, fill=TEXT, anchor="mm")

def title_bar(d, text, back=True):
    if back:
        button(d, (20, 16, 84, 52), "←", F22, fill=BG, outline=LINE, tfill=DIM)
    d.text((104, 34), text, font=F28, fill=GOLD, anchor="lm")

def save(img, name):
    import time
    path = os.path.join(OUT, name)
    for attempt in range(5):
        try:
            img.save(path)
            break
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.3)
    print("saved", name)

# ── 对战通用小件 ──────────────────────────────────────────────

def card_img(w, h, name, stats="", seat=LINE, back=False) -> Image.Image:
    """生成一张带圆角的卡面小图（可旋转后粘贴）。"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = (58, 50, 92, 255) if back else (44, 38, 72, 255)
    edge = (110, 100, 150, 255) if back else tuple(seat[:3]) + (255,)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=8, fill=fill, outline=edge, width=3)
    if back:
        d.text((w / 2, h / 2), "牌", font=F18, fill=(150, 144, 172, 255), anchor="mm")
    else:
        d.text((w / 2, h / 2 - 10), name, font=F14, fill=(232, 228, 240, 255), anchor="mm")
        if stats:
            d.text((w / 2, h - 18), stats, font=F16, fill=GOLD + (255,), anchor="mm")
    return img

def paste_tilted(base, cimg, cx, cy, angle):
    rot = cimg.rotate(angle, expand=True, resample=Image.BICUBIC)
    base.paste(rot, (int(cx - rot.width / 2), int(cy - rot.height / 2)), rot)

def avatar(d, cx, cy, r, name, hp, color=GOLD):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=PANEL2, outline=color, width=3)
    d.text((cx, cy - 6), "头像", font=F12, fill=DIM, anchor="mm")
    d.text((cx, cy + r + 4), name, font=F14, fill=TEXT, anchor="ma")
    d.text((cx + r + 10, cy), str(hp), font=F28, fill=GOLD, anchor="lm")

# ───────────────────────── 1. 主菜单 ─────────────────────────
def main_menu():
    img, d = canvas()
    d.text((W / 2, 180), "百 闻 牌", font=F40, fill=GOLD, anchor="mm")
    d.text((W / 2, 236), "B W P r o", font=F22, fill=PURPLE, anchor="mm")
    entries = [("卡组构筑", "本地卡组管理 / 卡组码导入导出"),
               ("本地热坐", "双人对战 · 同一设备"),
               ("联机对战", "创建 / 加入房间")]
    y = 340
    for name, sub in entries:
        box(d, (980, y, 1480, y + 110), fill=PANEL, outline=GOLD, width=2, r=12)
        d.text((1010, y + 40), name, font=F28, fill=TEXT, anchor="lm")
        d.text((1010, y + 80), sub, font=F14, fill=DIM, anchor="lm")
        y += 140
    box(d, (30, 770, 420, 860), fill=PANEL, outline=LINE)
    d.text((55, 800), "本地玩家", font=F18, fill=TEXT, anchor="lm")
    d.text((55, 832), "卡组：~/.bwpro/decks.json", font=F12, fill=DIM, anchor="lm")
    d.text((W / 2, 882), "个人学习项目 · 与官方无关 · 素材版权归属原作者", font=F12, fill=DIM, anchor="mm")
    d.text((W - 24, 882), "v0.1", font=F12, fill=DIM, anchor="rm")
    save(img, "01_main_menu.png")

# ───────────────────────── 2. 卡组管理（阵容） ─────────────────────────
def deck_list():
    img, d = canvas()
    title_bar(d, "卡组构筑")
    button(d, (1150, 16, 1330, 52), "＋ 新建卡组", F16)
    button(d, (1350, 16, 1570, 52), "导入卡组码", F16, outline=LINE)
    decks = [("标准·主力", True), ("青岚快攻", True), ("娱乐整活", False), ("测试卡组", False), ("新卡组 5", True)]
    x = 60
    for name, standard in decks:
        border = BLUE if standard else LINE
        box(d, (x, 90, x + 220, 800), fill=PANEL, outline=border, width=3 if standard else 1, r=12)
        for i in range(4):
            diamond(d, x + 110, 200 + i * 120, 44, "式神", SEAT[i])
        d.text((x + 110, 700), "标准" if standard else "非标准", font=F12,
               fill=BLUE if standard else DIM, anchor="mm")
        d.text((x + 110, 730), name, font=F18, fill=TEXT, anchor="mm")
        for j, t in enumerate(("码", "名", "删")):
            button(d, (x + 30 + j * 58, 752, x + 74 + j * 58, 788), t, F14, fill=PANEL2, outline=LINE, tfill=DIM)
        x += 250
    d.text((W / 2, 850), "← 横向滚动 · 点击卡组列进入编辑（先展示卡组码）", font=F14, fill=DIM, anchor="mm")
    save(img, "02_deck_list.png")

# ───────────────────────── 3. 构筑编辑 ─────────────────────────
def deck_editor():
    img, d = canvas()
    title_bar(d, "编辑卡组：标准·主力")
    button(d, (560, 16, 900, 52), "卡组码：BWPR-XXXX…（点击复制）", F14, outline=LINE, tfill=DIM)
    button(d, (920, 16, 1140, 52), "环境：经典 v", F14, outline=LINE)
    d.text((1570, 34), "√ 符合标准规则", font=F16, fill=BLUE, anchor="rm")
    box(d, (20, 80, 320, 860), fill=PANEL, r=12)
    d.text((40, 104), "版本包 / 式神", font=F18, fill=GOLD, anchor="la")
    packs = ["00 新手包", "01 经典", "02 不夜之火", "03 月夜幻响", "04 沧海刀鸣", "05 吉运缘结"]
    y = 150
    for p in packs:
        d.text((40, y), ">" + p, font=F16, fill=TEXT if p != "01 经典" else GOLD, anchor="la")
        y += 40
        if p == "01 经典":
            for s in ("白狼", "兵俑", "大天狗", "姑获鸟", "…"):
                d.text((70, y), s, font=F14, fill=DIM, anchor="la")
                y += 32
    d.text((40, 830), "搜索：________", font=F14, fill=DIM, anchor="la")
    box(d, (340, 80, 1000, 860), fill=PANEL, r=12)
    d.text((360, 104), "白狼 · 卡牌（点选 ×2 上限提示，不强制）", font=F16, fill=GOLD, anchor="la")
    names = ["文射", "援护", "离", "残心", "起弓", "迅捷之射", "觉醒·白狼", "无我", "协战·会"]
    for i, n in enumerate(names):
        cx, cy = 370 + (i % 3) * 215, 150 + (i // 3) * 230
        card(d, (cx, cy, cx + 195, cy + 200), n, "1/2" if i % 2 else "2/2",
             outline=GOLD if i % 2 == 0 else LINE)
        button(d, (cx + 60, cy + 164, cx + 135, cy + 192), "＋", F16, fill=PANEL)
    box(d, (1020, 80, 1580, 860), fill=PANEL, r=12)
    d.text((1040, 104), "当前卡组（4 式神 × 8）", font=F18, fill=GOLD, anchor="la")
    y = 150
    for si in range(4):
        box(d, (1040, y, 1560, y + 150), fill=PANEL2, outline=SEAT[si], width=2, r=8)
        d.text((1058, y + 18), f"式神{si + 1}（8/8）", font=F16, fill=SEAT[si], anchor="la")
        d.text((1058, y + 52), "文射×2  援护×2  离×2  残心×1\n起弓×1  …", font=F12, fill=DIM, anchor="la")
        y += 168
    button(d, (1040, y + 8, 1290, y + 56), "保存卡组", F18)
    button(d, (1310, y + 8, 1560, y + 56), "放弃修改", F18, outline=LINE, tfill=DIM)
    save(img, "03_deck_editor.png")

# ───────────────────────── 4. 对阵展示（VS splash，参照 36_3） ─────────────────────────
def vs_splash():
    img, d = canvas()
    # 敌方：左上倾斜 4 卡 + 右上头像
    for i in range(4):
        c = card_img(150, 220, f"敌·式神{i + 1}", seat=SEAT[i])
        paste_tilted(img, c, 160 + i * 165, 180 + (i % 2) * 18, -8 + i * 3)
    d_img = ImageDraw.Draw(img)
    avatar(d_img, 1330, 150, 56, "对手", 30)
    # 我方：右下倾斜 4 卡 + 左下头像
    for i in range(4):
        c = card_img(150, 220, f"式神{i + 1}", seat=SEAT[i])
        paste_tilted(img, c, 950 + i * 160, 700 - (i % 2) * 18, 8 - i * 3)
    avatar(d_img, 270, 720, 56, "你", 30)
    # 中央 VS
    d_img.text((W / 2, H / 2 - 20), "V S", font=F40, fill=GOLD, anchor="mm")
    d_img.text((W / 2, H / 2 + 40), "环境：经典 ｜ 你为先手", font=F18, fill=DIM, anchor="mm")
    d_img.text((W / 2, H - 40), "点击进入对局", font=F14, fill=DIM, anchor="mm")
    save(img, "04_vs_splash.png")

# ───────────────────────── 5. 对局主界面（参照 38_3） ─────────────────────────
def battle():
    img, d = canvas()
    # 左上：敌方头像+生命+状态小图标
    avatar(d, 90, 80, 40, "对手", 30)
    d.text((180, 60), "鬼火 ●●", font=F12, fill=PURPLE, anchor="la")
    # 敌方 4 式神：立绘卡弧形立于上方
    for i in range(4):
        c = card_img(130, 190, f"敌·式神{i + 1}", "2/5", SEAT[i])
        paste_tilted(img, c, 500 + i * 160, 160 + abs(i - 1.5) * 14, -4 + i * 2.5)
    # 敌方战斗区（前移一格位置）
    c = card_img(130, 190, "敌·战斗", "4/4", GOLD + (255,))
    paste_tilted(img, c, 660, 268, 0)
    # 右上：敌方手牌背 + 设置
    for i in range(5):
        c = card_img(56, 84, "", back=True)
        paste_tilted(img, c, 1330 + i * 48, 52, 0)
    d_img = ImageDraw.Draw(img)
    d_img.text((1560, 30), "设", font=F18, fill=DIM, anchor="mm")
    # 中线提示（演示时不画分割线，只标阶段横幅）
    box(d_img, (560, 354, 1040, 424), fill=PANEL, outline=PURPLE, width=2, r=24)
    ctext(d_img, 800, 376, "你的回合", F28, GOLD)
    ctext(d_img, 800, 402, "距额外升级还剩 2 回合 ｜ 计时 96s", F14, DIM)
    # 我方战斗区
    c = card_img(130, 190, "我·战斗", "3/4", GOLD + (255,))
    paste_tilted(img, c, 740, 524, 0)
    # 我方 4 式神：立于下方
    for i in range(4):
        c = card_img(130, 190, f"式神{i + 1}", "3/4", SEAT[i])
        paste_tilted(img, c, 420 + i * 160, 640 - abs(i - 1.5) * 12, 4 - i * 2.5)
    # 左下：我方头像+生命+鬼火
    avatar(d_img, 90, 800, 40, "你", 30)
    d_img.text((180, 780), "鬼火 ●●○", font=F12, fill=PURPLE, anchor="la")
    d_img.text((180, 806), "出击加成 +1/+1", font=F12, fill=DIM, anchor="la")
    # 左缘：结算记录开关（点击展开覆盖面板）
    d_img.ellipse((18, 420, 66, 468), fill=PANEL, outline=LINE, width=2)
    d_img.text((42, 444), "录", font=F16, fill=DIM, anchor="mm")
    # 右缘：牌库 + 回合按钮
    for i in range(3):
        c = card_img(70, 104, "", back=True)
        paste_tilted(img, c, 1500, 560 + i * 8, -6 + i * 6)
    d_img.text((1500, 640), "牌库 21", font=F12, fill=DIM, anchor="mm")
    d_img.ellipse((1430, 680, 1560, 810), fill=PANEL, outline=GOLD, width=4)
    d_img.text((1495, 745), "结束\n回合", font=F22, fill=GOLD, anchor="mm")
    # 我方手牌：右下扇形
    for i in range(5):
        c = card_img(112, 164, f"手牌{i + 1}", "", SEAT[0])
        paste_tilted(img, c, 900 + i * 92, 792 - abs(i - 2) * 8, -12 + i * 6)
    save(img, "05_battle.png")

# ───────────────────────── 6. 起始手牌调度（参照 37_3） ─────────────────────────
def mulligan():
    img, d = canvas()
    # 暗化战场背景（简化示意）
    d.rectangle((0, 0, W, H), fill=(12, 10, 22))
    for i in range(4):
        c = card_img(110, 164, f"敌·式神{i + 1}", seat=SEAT[i])
        paste_tilted(img, c, 560 + i * 140, 120, -3 + i * 2)
    d_img = ImageDraw.Draw(img)
    d_img.rectangle((0, 0, W, H), fill=None)
    # 左上：先后手徽标 + 提示
    diamond(d_img, 90, 80, 46, "先手", GOLD)
    d_img.text((170, 80), "点击手牌标记替换（0/4）", font=F18, fill=TEXT, anchor="lm")
    d_img.text((170, 116), "座次：白狼 → 兵俑 → 大天狗 → 姑获鸟", font=F14, fill=DIM, anchor="lm")
    # 右上：对方手牌背 + 确认
    for i in range(4):
        c = card_img(56, 84, "", back=True)
        paste_tilted(img, c, 1240 + i * 48, 52, 0)
    button(d_img, (1440, 24, 1576, 84), "确认", F22)
    # 中央：4 张大手牌
    for i in range(4):
        x = 290 + i * 270
        glow = i % 2 == 1
        card(d_img, (x, 250, x + 230, 610), f"手牌{i + 1}", "", outline=GOLD if glow else LINE)
        if glow:
            d_img.text((x + 115, 242), "替换", font=F16, fill=GOLD, anchor="mb")
    ctext(d_img, 800, 660, "剩余 24s（超时按当前选择确认）", F16, DIM)
    save(img, "06_mulligan.png")

# ───────────────────────── 7. 联机大厅 ─────────────────────────
def lobby():
    img, d = canvas()
    title_bar(d, "联机对战")
    box(d, (60, 90, 1540, 190), fill=PANEL, r=12)
    d.text((90, 124), "服务器", font=F16, fill=DIM, anchor="lm")
    button(d, (200, 100, 700, 148), "ws://127.0.0.1:1037（默认本机，回车连接）", F14, outline=LINE, tfill=DIM)
    d.text((740, 124), "玩家名", font=F16, fill=DIM, anchor="lm")
    button(d, (860, 100, 1100, 148), "Varis", F14, outline=LINE)
    d.text((1140, 124), "√ 已连接", font=F16, fill=GREEN, anchor="lm")
    d.text((90, 168), "卡组", font=F16, fill=DIM, anchor="lm")
    button(d, (200, 152, 700, 186), "标准·主力（标准 √）v", F14, outline=BLUE, tfill=BLUE)
    button(d, (1060, 230, 1300, 290), "创建房间", F22)
    button(d, (1320, 230, 1540, 290), "加入房间", F22, outline=LINE)
    button(d, (60, 230, 460, 290), "房间码：______（6 位，可自定义）", F14, outline=LINE, tfill=DIM)
    box(d, (400, 330, 1200, 800), fill=PANEL, outline=GOLD, width=2, r=16)
    ctext(d, 800, 380, "房间 A3F9K2", F28, GOLD)
    box(d, (460, 440, 760, 640), fill=PANEL2, outline=BLUE, width=2, r=12)
    ctext(d, 610, 490, "Varis（房主）", F22, TEXT)
    ctext(d, 610, 540, "标准·主力 √", F16, BLUE)
    ctext(d, 610, 590, "已准备", F18, GREEN)
    ctext(d, 800, 540, "VS", F28, GOLD)
    box(d, (840, 440, 1140, 640), fill=PANEL2, outline=LINE, r=12)
    ctext(d, 990, 490, "等待加入…", F22, DIM)
    ctext(d, 990, 590, "未准备", F18, DIM)
    ctext(d, 800, 680, "环境：经典（房主可改）｜ 对方准备后 15s 自动准备", F14, DIM)
    button(d, (500, 716, 750, 772), "取消准备", F18, outline=LINE)
    button(d, (850, 716, 1100, 772), "离开房间", F18, outline=LINE, tfill=DIM)
    save(img, "07_online_lobby.png")

# ───────────────────────── 8. 升级阶段（参照 39_3） ─────────────────────────
def level_up():
    img, d = canvas()
    # 暗化战场示意：敌方一排在上
    for i in range(4):
        c = card_img(110, 164, f"敌·式神{i + 1}", "2/5", SEAT[i])
        paste_tilted(img, c, 500 + i * 150, 130, 0)
    d_img = ImageDraw.Draw(img)
    # 我方 4 式神：可升级者金色发光描边 + 头顶等级勾玉
    for i in range(4):
        cx = 420 + i * 250
        can = i in (0, 2)  # 演示：1、3 号位可升级
        if can:
            d_img.rounded_rectangle((cx - 78, 358, cx + 78, 582), radius=10,
                                    outline=GOLD, width=6)
        c = card_img(140, 200, f"式神{i + 1}", "3/4", SEAT[i])
        paste_tilted(img, c, cx, 470, 0)
        # 等级勾玉（圆形太极示意，填派系色）
        d_img.ellipse((cx - 20, 300, cx + 20, 340), fill=SEAT[i], outline=BG, width=2)
        d_img.text((cx, 320), str(1 + (i % 2)), font=F16, fill=BG, anchor="mm")
    # 右侧提示
    d_img.text((1330, 430), "请选择升级式神", font=F22, fill=PURPLE, anchor="mm")
    d_img.text((1330, 470), "本回合剩余次数 1", font=F14, fill=DIM, anchor="mm")
    save(img, "08_level_up.png")

# ───────────────────────── 9. 式神详情面板（参照 40_3） ─────────────────────────
def shiki_detail():
    img, d = canvas()
    d.rectangle((0, 0, W, H), fill=(14, 12, 24))  # 暗化背景
    # 左侧大面板：增益列表 + 形态卡面 + 能力文本
    box(d, (40, 40, 620, 860), fill=PANEL, outline=LINE, r=14)
    ctext(d, 330, 66, "式神详情", F22, GOLD)
    # 增益列表（带来源小图标）
    box(d, (70, 100, 590, 250), fill=PANEL2, outline=LINE, r=10)
    ctext(d, 330, 122, "增益（3）", F16, TEXT)
    for i, s in enumerate(["永久得 +1/+1（来源：形态·千年之守）",
                           "得 +1/+1（来源：幻境·神赐之日）",
                           "额外获得能力：贯通（来源：觉醒能力）"]):
        d.ellipse((92, 148 + i * 30, 108, 164 + i * 30), fill=SEAT[i % 4])
        d.text((120, 156 + i * 30), s, font=F14, fill=TEXT, anchor="lm")
    # 形态卡面 + 身材
    card(d, (90, 280, 300, 520), "形态·千年之守", "8/11", outline=GOLD)
    # 能力文本区
    box(d, (70, 550, 590, 830), fill=PANEL2, outline=LINE, r=10)
    d.text((90, 576), "基础能力", font=F16, fill=GOLD, anchor="la")
    d.text((90, 606), "（能力文本占位，多行）", font=F14, fill=TEXT, anchor="la")
    d.text((90, 660), "觉醒能力", font=F16, fill=GOLD, anchor="la")
    d.text((90, 690), "（觉醒能力文本占位）", font=F14, fill=TEXT, anchor="la")
    # 右侧浮动：关键词条解释（可切换标签）
    box(d, (680, 100, 1180, 480), fill=PANEL, outline=PURPLE, width=2, r=12)
    for i, kw in enumerate(["贯通", "觉醒", "瞬发"]):
        button(d, (700 + i * 110, 120, 800 + i * 110, 156), kw, F14,
               outline=GOLD if i == 0 else LINE)
    d.text((700, 186), "贯通", font=F18, fill=GOLD, anchor="la")
    d.text((700, 216), "具有贯通的卡牌主动对式神造成的\n过量伤害会转移给它的牌手。",
           font=F14, fill=TEXT, anchor="la")
    save(img, "09_shiki_detail.png")

# ───────────────────────── 10. 幻境队列详情（参照 41_3） ─────────────────────────
def field_detail():
    img, d = canvas()
    d.rectangle((0, 0, W, H), fill=(14, 12, 24))
    ctext(d, 800, 80, "幻境队列（技能卡详情）", F28, GOLD)
    # 队列：三张幻境卡，队首标"优先承受伤害"
    for i in range(3):
        x = 320 + i * 280
        card(d, (x, 220, x + 240, 560), f"幻境·卡牌{i + 1}", f"耐久 {11 - i * 5}",
             outline=GOLD if i == 0 else LINE)
        if i == 0:
            ctext(d, x + 120, 600, "「 优先承受伤害 」", F16, GOLD)
    # 右侧：牌手级能力说明卡
    card(d, (1200, 220, 1440, 560), "牌手能力", "（文本占位）", outline=PURPLE)
    # 右上确认
    diamond(d, 1500, 80, 44, "确认", GOLD)
    save(img, "10_field_detail.png")

if __name__ == "__main__":
    main_menu()
    deck_list()
    deck_editor()
    vs_splash()
    battle()
    mulligan()
    lobby()
    level_up()
    shiki_detail()
    field_detail()
