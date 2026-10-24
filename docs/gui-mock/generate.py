"""BWPro 桌面 GUI 界面初稿生成（一次性设计工具，PIL 绘制线框稿）。

用法（需要 Pillow，BWPro 本体暂不依赖，可用 BWPDIY 的 venv 跑）：
    python docs/gui-mock/generate.py
输出：docs/gui-mock/light/ 与 docs/gui-mock/dark/ 各一套 1600x900 线框稿（浅/深双主题）。
对局相关界面参照 gui_ref/ 原版游戏截图与内录视频抽帧（均不入库）。
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 1600, 900

# 双主题：浅色 = BWPDIY 羊皮纸；深色 = 夜樱紫。generate.py 一次生成两套（dark/ 子目录）
THEMES = {
    "light": dict(
        BG=(243, 239, 232), PANEL=(255, 251, 233), PANEL2=(240, 234, 216),
        LINE=(201, 194, 178), GOLD=(180, 140, 50), GOLD2=(217, 185, 106),
        PURPLE=(140, 120, 200), TEXT=(38, 34, 28), DIM=(119, 119, 119),
        BLUE=(60, 130, 200), GREEN=(70, 160, 90),
        SEAT=[(184, 134, 11), (32, 132, 140), (126, 87, 194), (190, 60, 60)],
    ),
    "dark": dict(
        BG=(20, 17, 33), PANEL=(35, 30, 58), PANEL2=(44, 38, 72),
        LINE=(86, 76, 128), GOLD=(201, 168, 106), GOLD2=(201, 168, 106),
        PURPLE=(140, 120, 200), TEXT=(232, 228, 240), DIM=(150, 144, 172),
        BLUE=(90, 160, 220), GREEN=(120, 200, 140),
        SEAT=[(216, 194, 106), (106, 192, 200), (169, 138, 216), (216, 122, 122)],
    ),
}
for _k, _v in THEMES["light"].items():
    globals()[_k] = _v

def set_theme(name):
    global OUT
    for k, v in THEMES[name].items():
        globals()[k] = v
    OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    os.makedirs(OUT, exist_ok=True)

def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)

F12, F14, F16, F18, F22, F28, F40 = (font(s) for s in (12, 14, 16, 18, 22, 28, 40))

def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)

def box(d, xy, fill=None, outline=None, width=1, r=10):
    fill = PANEL if fill is None else fill
    outline = LINE if outline is None else outline
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)

def ctext(d, cx, y, s, f, fill=None):
    fill = TEXT if fill is None else fill
    d.text((cx, y), s, font=f, fill=fill, anchor="ma")

def button(d, xy, label, f=F18, fill=None, outline=None, tfill=None):
    fill = PANEL2 if fill is None else fill
    outline = GOLD if outline is None else outline
    tfill = TEXT if tfill is None else tfill
    box(d, xy, fill=fill, outline=outline, width=2, r=8)
    x1, y1, x2, y2 = xy
    d.text(((x1 + x2) / 2, (y1 + y2) / 2), label, font=f, fill=tfill, anchor="mm")

def card(d, xy, name, sub="", outline=None, tfill=None):
    outline = LINE if outline is None else outline
    tfill = TEXT if tfill is None else tfill
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

def card_img(w, h, name, stats="", seat=None, back=False) -> Image.Image:
    """生成一张带圆角的卡面小图（可旋转后粘贴）。"""
    seat = LINE if seat is None else seat
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = tuple(max(0, c - 18) for c in PANEL2) + (255,) if back else PANEL + (255,)
    edge = DIM + (255,) if back else tuple(seat[:3]) + (255,)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=8, fill=fill, outline=edge, width=3)
    if back:
        d.text((w / 2, h / 2), "牌", font=F18, fill=DIM + (255,), anchor="mm")
    else:
        d.text((w / 2, h / 2 - 10), name, font=F14, fill=TEXT + (255,), anchor="mm")
        if stats:
            d.text((w / 2, h - 18), stats, font=F16, fill=GOLD + (255,), anchor="mm")
    return img

def field_card(w, h, name, power, life, seat, level=None) -> Image.Image:
    """场上式神卡：力量（左下圆）/生命（右下圆）/等级勾玉（下中），参照 38_对战。"""
    img = card_img(w, h, name, "", seat)
    d = ImageDraw.Draw(img)
    r = max(12, w // 9)
    d.ellipse((4, h - 2 * r - 4, 4 + 2 * r, h - 4), fill=(60, 130, 140, 255))
    d.text((4 + r, h - r - 4), str(power), font=F16, fill=(255, 255, 255, 255), anchor="mm")
    d.ellipse((w - 4 - 2 * r, h - 2 * r - 4, w - 4, h - 4), fill=(190, 60, 60, 255))
    d.text((w - 4 - r, h - r - 4), str(life), font=F16, fill=(255, 255, 255, 255), anchor="mm")
    if level is not None:
        d.ellipse((w / 2 - r, h - r, w / 2 + r, h + r), fill=tuple(seat[:3]) + (255,),
                  outline=(255, 251, 233, 255), width=2)
        d.text((w / 2, h + 2), str(level), font=F14, fill=(255, 251, 233, 255), anchor="mm")
    return img

def paste_tilted(base, cimg, cx, cy, angle):
    rot = cimg.rotate(angle, expand=True, resample=Image.BICUBIC)
    base.paste(rot, (int(cx - rot.width / 2), int(cy - rot.height / 2)), rot)

def avatar(d, cx, cy, r, name, hp, color=None):
    color = GOLD if color is None else color
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
               ("式神录", "查看式神与全部卡牌（单卡样式同构筑）"),
               ("本地热坐", "双人对战 · 同一设备"),
               ("联机对战", "创建 / 加入房间")]
    y = 280
    for name, sub in entries:
        box(d, (980, y, 1480, y + 100), fill=PANEL, outline=GOLD, width=2, r=12)
        d.text((1010, y + 34), name, font=F28, fill=TEXT, anchor="lm")
        d.text((1010, y + 74), sub, font=F14, fill=DIM, anchor="lm")
        y += 130
    # 左下主题切换（浅/深）示意
    button(d, (40, 700, 220, 752), "主题：浅 / 深", F14, outline=LINE, tfill=DIM)
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
    # 左右拖动翻页（按钮兜底）
    button(d, (10, 420, 46, 500), "‹", F22, outline=LINE, tfill=DIM)
    button(d, (1554, 420, 1590, 500), "›", F22, outline=LINE, tfill=DIM)
    d.text((W / 2, 850), "左右拖动 / ‹ › 翻页 · 点击卡组列进入编辑（先展示卡组码）", font=F14, fill=DIM, anchor="mm")
    save(img, "02_deck_list.png")

# ───────────────────────── 3. 构筑编辑（参照 42/47/48） ─────────────────────────
def deck_editor():
    img, d = canvas()
    # 顶栏：返回 + 卡组名；右侧卡组码/环境/标准校验
    button(d, (20, 16, 84, 52), "←", F22, fill=BG, outline=LINE, tfill=DIM)
    d.text((104, 34), "标准·主力", font=F28, fill=GOLD, anchor="lm")
    button(d, (760, 16, 1000, 52), "卡组码（点击复制）", F14, outline=LINE, tfill=DIM)
    button(d, (1020, 16, 1180, 52), "环境：经典 v", F14, outline=LINE)
    button(d, (1200, 16, 1360, 52), "保存卡组", F14)
    d.text((1570, 34), "√ 符合标准规则", font=F16, fill=BLUE, anchor="rm")
    # 左缘：卡组内 4 式神竖列小卡（当前选中金框）
    for i in range(4):
        y = 90 + i * 190
        card(d, (24, y, 114, y + 170), f"式神{i + 1}", "", outline=GOLD if i == 0 else LINE)
    # 选中式神竖排名
    d.text((150, 440), "当\n前\n式\n神", font=F22, fill=GOLD, anchor="mm")
    # 中央：当前式神卡牌大卡，每页 5 卡（左右拖动/翻页按钮；8 主卡+协战牌分页）
    tags = ["已选 1 张", "满编 2 张", "", "满编 2 张", "协战"]
    for i in range(5):
        x = 260 + i * 250
        c = card_img(200, 300, f"卡牌{i + 1}", "", SEAT[0])
        paste_tilted(img, c, x + 100, 330, 0)
        d_img = ImageDraw.Draw(img)
        d_img.ellipse((x + 8, 186, x + 40, 218), fill=SEAT[i % 4])
        if tags[i]:
            d_img.rectangle((x + 14, 220, x + 186, 252), fill=GOLD2)
            d_img.text((x + 100, 236), tags[i], font=F12,
                       fill=(60, 45, 20) if tags[i] != "协战" else (110, 90, 180), anchor="mm")
        diamond(d_img, x + 100, 512, 18, str(i % 3), GOLD if i % 3 else LINE)
    # 翻页（可左右拖动，按钮兜底）
    button(d_img, (196, 300, 244, 380), "‹", F28, outline=LINE, tfill=DIM)
    button(d_img, (1546, 300, 1594, 380), "›", F28, outline=LINE, tfill=DIM)
    d_img.text((800, 560), "第 1/2 页（每页 5 卡）·（点击卡牌：+1 张；右键/长按：-1 张·查看单卡）",
               font=F14, fill=DIM, anchor="mm")
    # 底部：当前式神已选卡牌条（小卡横排）
    for i in range(8):
        x = 250 + i * 132
        card(d_img, (x, 620, x + 116, 790), f"已选{i + 1}", "", outline=LINE)
    d_img.text((150, 705), "已选\n8/8", font=F16, fill=DIM, anchor="mm")
    # 右下：4 式神阵容菱形 + 总览入口
    d_img.text((1150, 850), "标准\n阵容", font=F14, fill=DIM, anchor="mm")
    for i in range(4):
        diamond(d_img, 1260 + i * 78, 850, 32, "", SEAT[i])
    save(img, "03_deck_editor.png")

# ───────────────────────── 3b. 阵容总览+数据（参照 43/44/45） ─────────────────────────
def deck_overview():
    img, d = canvas()
    title_bar(d, "标准·主力 · 阵容总览")
    d.text((1570, 34), "√ 符合标准规则", font=F16, fill=BLUE, anchor="rm")
    # 上半：卡牌等级分布 + 卡牌类型分布（条形图）
    box(d, (60, 80, 770, 330), fill=PANEL, r=12)
    ctext(d, 415, 106, "卡牌等级", F18, GOLD)
    for i, (lv, n) in enumerate((("1 勾", 5), ("2 勾", 18), ("3 勾", 9))):
        y = 150 + i * 56
        d.text((110, y), lv, font=F16, fill=TEXT, anchor="lm")
        d.text((180, y), str(n), font=F16, fill=DIM, anchor="lm")
        d.rounded_rectangle((230, y - 10, 230 + n * 26, y + 10), radius=4, fill=PURPLE)
        d.rounded_rectangle((230, y - 10, 720, y + 10), radius=4, outline=LINE)
    box(d, (830, 80, 1540, 330), fill=PANEL, r=12)
    ctext(d, 1185, 106, "卡牌类型", F18, GOLD)
    for i, (tp, n) in enumerate((("战斗", 4), ("法术", 19), ("形态", 6), ("幻境", 3))):
        y = 136 + i * 46
        d.text((880, y), tp, font=F16, fill=TEXT, anchor="lm")
        d.text((950, y), str(n), font=F16, fill=DIM, anchor="lm")
        d.rounded_rectangle((1000, y - 9, 1000 + n * 26, y + 9), radius=4, fill=PURPLE)
        d.rounded_rectangle((1000, y - 9, 1490, y + 9), radius=4, outline=LINE)
    # 下半：4 行，每行 = 菱形头像+式神名 + 8 卡横排
    for si in range(4):
        y = 380 + si * 128
        diamond(d, 130, y + 52, 40, "", SEAT[si])
        d.text((200, y + 52), f"式神{si + 1}", font=F18, fill=SEAT[si], anchor="lm")
        for ci in range(8):
            x = 320 + ci * 152
            card(d, (x, y, x + 136, y + 104), f"卡牌{ci + 1}", "", outline=LINE)
    save(img, "11_deck_overview.png")

# ───────────────────────── 3c. 式神选择（参照 46） ─────────────────────────
def shiki_picker():
    img, d = canvas()
    title_bar(d, "选择式神（已选 2/4）")
    # 顶部：派系 tab + 版本包筛选 + 搜索
    tabs = ["全派系", "红莲", "紫岩", "青岚", "苍叶"]
    for i, t in enumerate(tabs):
        button(d, (60 + i * 130, 84, 170 + i * 130, 126), t, F16,
               outline=GOLD if i == 0 else LINE, tfill=TEXT if i == 0 else DIM)
    button(d, (760, 84, 960, 126), "版本：全部 v", F14, outline=LINE)
    button(d, (980, 84, 1240, 126), "搜索：____", F14, outline=LINE, tfill=DIM)
    # 网格式神方块
    for i in range(18):
        cx, cy = 60 + (i % 6) * 215, 160 + (i // 6) * 220
        chosen = i in (1, 7)
        card(d, (cx, cy, cx + 190, cy + 190), f"式神{i + 1}", "",
             outline=GOLD if chosen else LINE)
        if chosen:
            d.text((cx + 95, cy + 170), "已入队", font=F12, fill=GOLD, anchor="mm")
    # 右侧：当前已选 4 式神竖列
    box(d, (1370, 84, 1560, 700), fill=PANEL, r=12)
    ctext(d, 1465, 112, "当前阵容", F16, GOLD)
    for i in range(4):
        diamond(d, 1465, 200 + i * 120, 42, "", SEAT[i] if i < 2 else LINE)
    d.text((1465, 660), "点击式神\n加入/移出", font=F12, fill=DIM, anchor="mm")
    save(img, "12_shiki_picker.png")

# ───────────────────────── 3d. 单卡卡面组件（编辑/式神录/对局详情共用） ─────────────────────────
def card_detail():
    img, d = canvas()
    d.rectangle((0, 0, W, H), fill=(40, 36, 30))
    # 居中大卡：卡图区 / 卡名 / 效果文本 / 身材 / 子类型 / 勾玉等级 / 稀有度
    box(d, (560, 90, 1040, 810), fill=PANEL2, outline=GOLD, width=3, r=14)
    box(d, (590, 120, 1010, 420), fill=(58, 50, 92), outline=LINE, r=10)
    ctext(d, 800, 270, "卡图区（BWPDIY 合成）", F18, DIM)
    # 勾玉等级（左上）+ 稀有度（右上）
    d.ellipse((570, 100, 620, 150), fill=SEAT[1])
    d.text((595, 125), "2", font=F18, fill=BG, anchor="mm")
    d.text((1016, 108), "SSR", font=F14, fill=GOLD, anchor="ra")
    ctext(d, 800, 452, "卡牌名", F28, GOLD)
    ctext(d, 800, 500, "（效果文本区，多行，含增强后数值动态显示）", F14, TEXT)
    ctext(d, 800, 560, "力量 4 ｜ 生命 5（战斗/形态）", F16, TEXT)
    ctext(d, 800, 620, "式神名 · 子类型", F14, DIM)
    ctext(d, 800, 760, "构筑编辑 / 式神录 / 对局查看详情 共用此卡面样式", F14, DIM)
    diamond(d, 1500, 80, 44, "确认", GOLD)
    save(img, "13_card_detail.png")

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
def battle_base(banner=("你的回合", "距额外升级还剩 2 回合 ｜ 计时 96s")):
    """对局主界面布局（参照 38_对战）：四角信息、双方式神弧线、中央战斗区、
    手牌叠加绘制在场况之上。返回 (img, draw)。"""
    img, d = canvas()
    # 左上：敌方牌手——头像 + 头像右下生命徽标 + 右侧出击状态/鬼火
    d.ellipse((28, 28, 108, 108), fill=PANEL2, outline=LINE, width=3)
    d.text((68, 68), "头像", font=F12, fill=DIM, anchor="mm")
    d.ellipse((90, 90, 126, 126), fill=(190, 60, 60), outline=PANEL, width=2)
    d.text((108, 108), "30", font=F14, fill=(255, 255, 255), anchor="mm")
    d.text((138, 44), "对手", font=F16, fill=TEXT, anchor="lm")
    d.text((138, 72), "鬼火 ●●", font=F14, fill=PURPLE, anchor="lm")
    d.text((138, 98), "出击 0/1", font=F12, fill=DIM, anchor="lm")
    # 敌方 4 式神：准备区弧线（上，中央留空给战斗区）
    ARC_X = (420, 640, 960, 1180)
    for i in range(4):
        c = field_card(120, 176, f"敌·式神{i + 1}", 2, 5, SEAT[i], level=1 + i % 2)
        paste_tilted(img, c, ARC_X[i], 190 + abs(i - 1.5) * 16, -3 + i * 2)
    d_img = ImageDraw.Draw(img)
    # 敌方战斗区（中央，虚位）
    box(d_img, (735, 262, 865, 428), fill=BG, outline=LINE, r=10)
    d_img.text((800, 345), "敌方\n战斗区", font=F14, fill=DIM, anchor="mm")
    # 右上：敌方手牌背（仅确认数量）+ 设置/菜单
    for i in range(5):
        c = card_img(56, 84, "", back=True)
        paste_tilted(img, c, 1200 + i * 48, 52, 0)
    d_img.text((1460, 52), "×5", font=F14, fill=DIM, anchor="lm")
    button(d_img, (1490, 20, 1570, 64), "菜单", F14, outline=LINE, tfill=DIM)
    # 中央：回合横幅
    box(d_img, (540, 438, 1060, 500), fill=PANEL, outline=GOLD2, width=2, r=24)
    ctext(d_img, 800, 454, banner[0], F28, GOLD)
    ctext(d_img, 800, 482, banner[1], F12, DIM)
    # 我方战斗区（中央，虚位）
    box(d_img, (735, 512, 865, 678), fill=BG, outline=LINE, r=10)
    d_img.text((800, 595), "我方\n战斗区", font=F14, fill=DIM, anchor="mm")
    # 我方 4 式神：准备区弧线（下，中央留空给战斗区）
    for i in range(4):
        c = field_card(120, 176, f"式神{i + 1}", 3, 4, SEAT[i], level=1 + i % 2)
        paste_tilted(img, c, ARC_X[i], 720 - abs(i - 1.5) * 14, 3 - i * 2)
    # 左下：我方牌手
    d_img.ellipse((28, 792, 108, 872), fill=PANEL2, outline=GOLD2, width=3)
    d_img.text((68, 832), "头像", font=F12, fill=DIM, anchor="mm")
    d_img.ellipse((90, 854, 126, 890), fill=(190, 60, 60), outline=PANEL, width=2)
    d_img.text((108, 872), "30", font=F14, fill=(255, 255, 255), anchor="mm")
    d_img.text((138, 806), "你", font=F16, fill=TEXT, anchor="lm")
    d_img.text((138, 834), "鬼火 ●●○", font=F14, fill=PURPLE, anchor="lm")
    d_img.text((138, 860), "出击 1/1 · 加成+1/+1", font=F12, fill=DIM, anchor="lm")
    # 左中：查看对战记录
    d_img.ellipse((18, 420, 66, 468), fill=PANEL, outline=LINE, width=2)
    d_img.text((42, 444), "录", font=F16, fill=GOLD, anchor="mm")
    d_img.text((42, 484), "对战记录", font=F12, fill=DIM, anchor="mm")
    # 右缘中央：敌方牌库（上）/ 结束回合（中）/ 我方牌库（下），牌库可点击查看详情
    for i in range(3):
        c = card_img(70, 104, "", back=True)
        paste_tilted(img, c, 1500, 280 + i * 6, -4 + i * 4)
    d_img.text((1500, 350), "敌·牌库 21", font=F12, fill=DIM, anchor="mm")
    d_img.ellipse((1425, 400, 1575, 550), fill=PANEL, outline=GOLD, width=4)
    d_img.text((1500, 475), "结束\n回合", font=F22, fill=GOLD, anchor="mm")
    for i in range(3):
        c = card_img(70, 104, "", back=True)
        paste_tilted(img, c, 1500, 600 + i * 6, -4 + i * 4)
    d_img.text((1500, 674), "我·牌库 24", font=F12, fill=DIM, anchor="mm")
    d_img.text((1500, 694), "（点击查看详情）", font=F12, fill=DIM, anchor="mm")
    # 我方手牌：底部靠右扇形，叠加在场况之上绘制
    for i in range(5):
        c = field_card(110, 160, f"手牌{i + 1}", 4, 5, SEAT[0])
        paste_tilted(img, c, 980 + i * 96, 872 - abs(i - 2) * 8, -10 + i * 5)
    return img, ImageDraw.Draw(img)

def battle():
    img, _ = battle_base()
    save(img, "05_battle.png")

# ───────────────────────── 6. 起始手牌调度（参照 37_3） ─────────────────────────
def mulligan():
    img, d = canvas()
    # 暗化战场背景（简化示意）
    d.rectangle((0, 0, W, H), fill=(40, 36, 30))
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

# ───────────────────────── 8. 升级阶段（基于对局主界面，参照 39_3） ─────────────────────────
def level_up():
    img, d = battle_base()
    # 暗化场况，手牌不变暗（升级阶段不看手牌，一并压暗）
    overlay = Image.new("RGBA", (W, H), (38, 34, 28, 110))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"),
              (0, 0))
    d = ImageDraw.Draw(img)
    # 可升级式神金色发光描边（位置与 battle_base 我方准备区一致）
    for i in (0, 2):
        cx, cy = (420, 640, 960, 1180)[i], 720 - abs(i - 1.5) * 14
        d.rounded_rectangle((cx - 72, cy - 100, cx + 72, cy + 100), radius=12,
                            outline=GOLD2, width=6)
    # 右侧提示
    d.text((1330, 430), "请选择升级式神", font=F22, fill=PURPLE, anchor="mm")
    d.text((1330, 470), "本回合剩余次数 1", font=F14, fill=DIM, anchor="mm")
    save(img, "08_level_up.png")

# ───────────────────────── 9. 式神详情面板（参照 40_3） ─────────────────────────
def shiki_detail():
    img, d = canvas()
    d.rectangle((0, 0, W, H), fill=(40, 36, 30))  # 暗化背景
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
    d.rectangle((0, 0, W, H), fill=(40, 36, 30))
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

# ───────────────────────── 11+. 视频参考补充（gui_ref/*.mp4 抽帧） ─────────────────────────
def targeting():
    """出击/出牌目标选择：攻击者金框、拖拽箭头、合法目标高亮（battle/t034）。"""
    img, d = battle_base()
    # 攻击者金框（我方 1 号位准备区）
    d.rounded_rectangle((420 - 72, 720 - 7 - 100, 420 + 72, 720 - 7 + 100),
                        radius=12, outline=GOLD2, width=6)
    # 拖拽箭头：从攻击者指向敌方战斗区
    d.line((470, 640, 800, 400), fill=PURPLE, width=6)
    d.polygon([(800, 400), (770, 408), (788, 430)], fill=PURPLE)
    # 合法目标高亮（敌方战斗区 + 敌方牌手）
    d.rounded_rectangle((735, 262, 865, 428), radius=10, outline=GOLD2, width=5)
    ctext(d, 800, 60, "拖拽出击 / 出牌选择目标 · 点击空白处取消", F16, DIM)
    save(img, "14_targeting.png")

def deck_viewer():
    """牌库详情：暗化+标题+中央大卡+页码+灵咒计数（battle/t042）。"""
    img, d = canvas()
    d.rectangle((0, 0, W, H), fill=(40, 36, 30))
    ctext(d, 800, 60, "正在查看自己的牌库", F22, (232, 228, 240))
    card(d, (640, 140, 960, 640), "牌库卡牌（占位）", "", outline=GOLD)
    ctext(d, 800, 680, "「 1 – 24 」", F16, (232, 228, 240))
    diamond(d, 1500, 80, 44, "确认", GOLD)
    # 右下：牌库灵咒计数
    d.text((1400, 830), "灵咒", font=F16, fill=(232, 228, 240), anchor="mm")
    d.ellipse((1460, 800, 1520, 860), fill=PANEL2, outline=GOLD, width=2)
    d.text((1490, 830), "1", font=F18, fill=GOLD, anchor="mm")
    save(img, "15_deck_viewer.png")

def codex_home():
    """式神录·式神主页：立绘+右侧竖排名与入口+底部卡牌扇（codex/t008）。"""
    img, d = canvas()
    title_bar(d, "式神录")
    # 中央立绘占位
    box(d, (320, 100, 760, 560), fill=PANEL2, outline=LINE, r=14)
    ctext(d, 540, 330, "式神立绘", F28, DIM)
    # 右侧竖排名 + 卡牌/百科/详情入口
    d.text((900, 180), "式\n神\n名", font=F40, fill=GOLD, anchor="ma")
    diamond(d, 940, 380, 44, "卡牌", GOLD)
    d.text((940, 440), "8/8", font=F14, fill=DIM, anchor="mm")
    diamond(d, 940, 510, 40, "百科", LINE)
    button(d, (1060, 470, 1180, 520), "详情", F16, outline=LINE)
    # 底部：该式神卡牌扇（可拖动翻页）
    for i in range(8):
        c = card_img(130, 190, f"卡牌{i + 1}", "", SEAT[0])
        paste_tilted(img, c, 330 + i * 130, 730 - abs(i - 3.5) * 12, -8 + i * 2)
    d.text((60, 820), "式神总览 / 三界百闻", font=F14, fill=DIM, anchor="lm")
    d.text((800, 862), "筛选器 ｜ 已激活 ｜ 默认排序", font=F14, fill=DIM, anchor="mm")
    save(img, "16_codex_home.png")

def result():
    """胜负结算：胜负题字+双方阵容回顾+返回（无视频参考，按现有版式推演）。"""
    img, d = canvas()
    ctext(d, 800, 150, "胜  利", F40, GOLD)
    ctext(d, 800, 210, "对局结束 · 第 12 回合", F14, DIM)
    for side, y in (("敌方", 300), ("我方", 560)):
        d.text((300, y + 60), side, font=F18, fill=DIM, anchor="mm")
        for i in range(4):
            diamond(d, 480 + i * 160, y + 60, 44, "", SEAT[i])
    button(d, (640, 760, 960, 820), "返回主菜单", F22)
    save(img, "17_result.png")

# ───────────────────────── 12+. 用牌/效果处理界面（第二批视频） ─────────────────────────
def usage_options():
    """使用方式多择：同一卡牌按爆能档并列（各档文本/数值不同），右上取消出牌。
    起源多择=不同卡并排同版式；不合法选项灰化+居中浮字原因（burst-bless-invalid/t012）。"""
    img, d = canvas()
    d.rectangle((0, 0, W, H), fill=(40, 36, 30))
    d.text((60, 50), "请选择卡牌的使用方式", font=F18, fill=(232, 228, 240), anchor="lm")
    tags = [("基础", "贯通", "+2/+2"), ("能量 2", "贯通，吸血", "+3/+2"),
            ("能量 4", "贯通，吸血，免疫战斗伤害", "+4/+2"),
            ("能量 8", "贯通，吸血，连击，免疫战斗伤害", "+5/+2")]
    for i, (tag, text, stats) in enumerate(tags):
        x = 200 + i * 310
        card(d, (x, 140, x + 280, 620), "卡牌名", text, outline=GOLD if i == 2 else LINE)
        d.text((x + 140, 420), stats, font=F16, fill=GOLD, anchor="mm")
        # 右上费用徽标
        if i:
            d.ellipse((x + 240, 120, x + 290, 170), fill=(190, 60, 60))
            d.text((x + 265, 145), f"-{i * 2}", font=F16, fill=(255, 255, 255), anchor="mm")
        d.text((x + 140, 650), tag, font=F16, fill=(232, 228, 240), anchor="mm")
    button(d, (1330, 30, 1430, 76), "取消出牌", F14, outline=LINE, tfill=DIM)
    diamond(d, 1520, 50, 36, "战场", PURPLE)
    save(img, "18_usage_options.png")

def scry():
    """占卜：牌库顶/牌库底上下卡位，拖动卡牌选择去向，右侧确认（scry/t010）。"""
    img, d = canvas()
    d.rectangle((0, 0, W, H), fill=(40, 36, 30))
    ctext(d, 640, 60, "牌库顶", F18, (232, 228, 240))
    card(d, (520, 100, 760, 380), "卡牌 A", "", outline=GOLD)
    card(d, (520, 440, 760, 720), "卡牌 B", "", outline=LINE)
    ctext(d, 640, 756, "牌库底", F18, (232, 228, 240))
    ctext(d, 640, 396, "拖动卡牌使其置入牌库顶或牌库底", F14, (232, 228, 240))
    # 拖动箭头示意
    d.line((800, 240, 800, 540), fill=PURPLE, width=5)
    d.polygon([(800, 540), (786, 516), (814, 516)], fill=PURPLE)
    diamond(d, 1500, 450, 44, "确认", GOLD)
    save(img, "19_scry.png")

def discard_pick():
    """选择弃牌：暗化+候选大卡横排+选中红叉+确认（discard/t018）。"""
    img, d = canvas()
    d.rectangle((0, 0, W, H), fill=(40, 36, 30))
    d.text((60, 50), "请选择卡牌弃牌（1/1）", font=F18, fill=(232, 228, 240), anchor="lm")
    for i in range(5):
        x = 180 + i * 260
        card(d, (x, 180, x + 230, 560), f"手牌{i + 1}", "", outline=LINE)
        if i == 2:  # 已选中：红色大叉
            d.line((x + 20, 200, x + 210, 540), fill=(220, 60, 60), width=10)
            d.line((x + 210, 200, x + 20, 540), fill=(220, 60, 60), width=10)
    diamond(d, 1500, 80, 44, "确认", GOLD)
    save(img, "20_discard_pick.png")

# ───────────────────────── 13+. 菜单/战斗记录/响应（第三批视频） ─────────────────────────
def battle_menu():
    """右上菜单展开（选项/录屏/好友/弃权）+ 弃权确认弹窗（menu-log/t026）。"""
    img, d = battle_base()
    overlay = Image.new("RGBA", (W, H), (38, 34, 28, 90))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)
    # 右上竖排小菜单
    box(d, (1440, 80, 1580, 320), fill=PANEL, outline=LINE, r=8)
    for i, t in enumerate(["选项", "录屏", "好友", "弃权"]):
        d.text((1510, 116 + i * 56), t, font=F16, fill=TEXT, anchor="mm")
    # 中央确认弹窗
    box(d, (520, 300, 1080, 500), fill=PANEL, outline=GOLD, width=2, r=14)
    ctext(d, 800, 380, "确定要弃权么？", F22, TEXT)
    button(d, (600, 420, 760, 470), "取消", F18, outline=LINE, tfill=DIM)
    button(d, (840, 420, 1000, 470), "确定", F18)
    save(img, "21_battle_menu.png")

def battle_log():
    """战斗记录：左侧竖长面板+底部"返回最新记录"；点击条目场中显示对应大卡（log-detail）。"""
    img, d = battle_base()
    # 左侧记录面板
    d.rectangle((0, 0, 380, H), fill=PANEL)
    d.text((24, 30), "战斗记录", font=F28, fill=TEXT, anchor="lm")
    logs = ["狸猫获得【心身炼磨】", "【犬神】攻击【影鳄】",
            "【影鳄】受到了2点伤害，【犬神】受到了4点反击伤害",
            "狸猫使用了【心斩】", "【犬神】：护甲->2", "【犬神】攻击暗灵137",
            "暗灵137受到了2点伤害", "暗灵137：生命->28"]
    for i, s in enumerate(logs):
        d.text((24, 100 + i * 56), s, font=F14, fill=TEXT, anchor="lm")
    d.rectangle((0, 560, 380, 616), fill=PANEL2)
    d.text((24, 588), "暗灵137 ｜【回合 2】", font=F14, fill=DIM, anchor="lm")
    button(d, (60, 810, 320, 856), "返回最新记录 v", F14, outline=LINE, tfill=DIM)
    # 点击条目后：场中显示对应大卡+关键字说明
    card(d, (700, 200, 980, 560), "心身炼磨", "", outline=GOLD)
    box(d, (1020, 220, 1300, 380), fill=PANEL, outline=PURPLE, r=10)
    d.text((1040, 250), "关键字说明占位", font=F14, fill=TEXT, anchor="la")
    save(img, "22_battle_log.png")

def response_flash():
    """响应：满足条件必触发（无确认窗），中央短暂醒目"响应"大字。"""
    img, d = battle_base()
    overlay = Image.new("RGBA", (W, H), (38, 34, 28, 70))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)
    d.text((800, 420), "响  应", font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 96),
           fill=GOLD2, stroke_width=3, stroke_fill=GOLD, anchor="mm")
    ctext(d, 800, 520, "满足响应条件时自动使用，无确认窗口", F16, DIM)
    save(img, "23_response_flash.png")

if __name__ == "__main__":
    for theme in ("light", "dark"):
        set_theme(theme)
        main_menu()
        deck_list()
        deck_editor()
        deck_overview()
        shiki_picker()
        card_detail()
        vs_splash()
        battle()
        mulligan()
        lobby()
        level_up()
        shiki_detail()
        field_detail()
        targeting()
        deck_viewer()
        codex_home()
        result()
        usage_options()
        scry()
        discard_pick()
        battle_menu()
        battle_log()
        response_flash()
