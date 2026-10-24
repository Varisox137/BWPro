"""主窗口：视图栈 + 主菜单 + 全局浅/深主题。"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

# 与 docs/gui-mock/generate.py 两套配色一致
THEMES = {
    "light": dict(
        bg="#f3efe8", panel="#fffbe9", panel2="#f0ead8", line="#c9c2b2",
        gold="#b48c32", gold2="#d9b96a", text="#26221c", dim="#777777",
        blue="#3c82c8", seat=["#b8860b", "#20848c", "#7e57c2", "#be3c3c"],
    ),
    "dark": dict(
        bg="#141121", panel="#231e3a", panel2="#2c2648", line="#564c80",
        gold="#c9a86a", gold2="#c9a86a", text="#e8e4f0", dim="#9690ac",
        blue="#5aa0dc", seat=["#d8c26a", "#6ac0c8", "#a98ad8", "#d87a7a"],
    ),
}

MENU_ENTRIES = [
    ("builder", "卡组构筑", "本地卡组管理 / 卡组码导入导出"),
    ("codex", "式神录", "查看式神与全部卡牌（单卡样式同构筑）"),
    ("hotseat", "本地热坐", "双人对战 · 同一设备"),
    ("online", "联机对战", "创建 / 加入房间"),
]


def qss(theme: str) -> str:
    t = THEMES[theme]
    return f"""
    QMainWindow, QWidget {{ background: {t['bg']}; color: {t['text']}; }}
    QLabel#title {{ color: {t['gold']}; font-size: 40px; }}
    QLabel#subtitle {{ color: {t['dim']}; font-size: 16px; }}
    QLabel {{ font-size: 15px; }}
    QPushButton {{
        background: {t['panel']}; color: {t['text']};
        border: 2px solid {t['gold']}; border-radius: 10px;
        padding: 18px 24px; font-size: 20px; text-align: left;
    }}
    QPushButton:hover {{ background: {t['panel2']}; }}
    QPushButton:pressed {{ background: {t['gold2']}; }}
    QPushButton#small {{
        border: 1px solid {t['line']}; border-radius: 6px;
        padding: 6px 14px; font-size: 14px; text-align: center;
    }}
    QPushButton#small:disabled {{ color: {t['dim']}; border-color: {t['line']}; }}
    """


class MainWindow(QMainWindow):
    def __init__(self, db=None, store_path=None):
        super().__init__()
        self.setWindowTitle("百闻牌 BWPro")
        self.resize(1600, 900)
        self.theme = "light"
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)
        self.pages: dict[str, QWidget] = {}
        self.stack.addWidget(self._make_menu())
        for key, title, _sub in MENU_ENTRIES:
            if key == "builder":
                from client.gui.builder import DeckBuilderView
                if db is None:
                    from db.loader import CardDatabase
                    db = CardDatabase.load()
                kwargs = {} if store_path is None else {"store_path": store_path}
                self.pages[key] = DeckBuilderView(db, on_back=self.go_menu, **kwargs)
            else:
                self.pages[key] = self._make_placeholder(title)
            self.stack.addWidget(self.pages[key])
        self.set_theme(self.theme)

    def set_theme(self, theme: str):
        self.theme = theme
        self.setStyleSheet(qss(theme))
        builder = self.pages.get("builder")
        if hasattr(builder, "apply_theme"):
            builder.apply_theme(theme, THEMES[theme])

    def toggle_theme(self):
        self.set_theme("dark" if self.theme == "light" else "light")

    def go(self, key: str):
        self.stack.setCurrentWidget(self.pages[key])

    def go_menu(self):
        self.stack.setCurrentIndex(0)

    def _make_menu(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(60, 60, 60, 40)
        title = QLabel("百 闻 牌")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        sub = QLabel("B W P r o")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(40)
        for key, name, desc in MENU_ENTRIES:
            btn = QPushButton(f"{name}\n{desc}")
            btn.setMinimumHeight(100)
            btn.clicked.connect(lambda _=False, k=key: self.go(k))
            lay.addWidget(btn)
        lay.addStretch(1)
        theme_btn = QPushButton("主题：浅 / 深")
        theme_btn.setObjectName("small")
        theme_btn.clicked.connect(self.toggle_theme)
        lay.addWidget(theme_btn, alignment=Qt.AlignLeft)
        foot = QLabel("个人学习项目 · 与官方无关 · 素材版权归属原作者")
        foot.setObjectName("subtitle")
        foot.setAlignment(Qt.AlignCenter)
        lay.addWidget(foot)
        return page

    def _make_placeholder(self, title: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(40, 30, 40, 30)
        back = QPushButton("← 返回主菜单")
        back.setObjectName("small")
        back.clicked.connect(self.go_menu)
        lay.addWidget(back, alignment=Qt.AlignLeft)
        lab = QLabel(f"{title}（建设中）")
        lab.setAlignment(Qt.AlignCenter)
        lay.addWidget(lab)
        lay.addStretch(1)
        return page


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()
