"""主窗口：视图栈 + 主菜单 + 全局浅/深主题。"""
from __future__ import annotations

import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
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
    ("codex", "式神录", "查看式神与全部卡牌"),
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
    QPushButton#themeToggle {{
        border: 1px solid {t['gold']}; border-radius: 18px;
        padding: 0; font-size: 18px; text-align: center;
    }}
    QPushButton#dialogButton {{
        border: 1px solid {t['line']}; border-radius: 6px;
        padding: 4px 12px; font-size: 14px; text-align: center;
    }}
    """


def _theme_icon(theme: str) -> QIcon:
    """自绘太阳/月亮，避免不同平台字体缺字导致图标变方框。"""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    color = QColor(THEMES[theme]["gold"])
    if theme == "light":
        painter.setPen(color)
        for line in ((12, 1, 12, 4), (12, 20, 12, 23), (1, 12, 4, 12),
                     (20, 12, 23, 12), (4, 4, 6, 6), (18, 18, 20, 20),
                     (4, 20, 6, 18), (18, 6, 20, 4)):
            painter.drawLine(*line)
        painter.setBrush(color)
        painter.drawEllipse(7, 7, 10, 10)
    else:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        moon = QPainterPath()
        moon.addEllipse(4, 3, 18, 18)
        cutout = QPainterPath()
        cutout.addEllipse(10, 0, 18, 18)
        painter.drawPath(moon.subtracted(cutout))
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, db=None, store_path=None):
        super().__init__()
        self.setWindowTitle("BWPro")
        self.resize(1600, 900)
        self.theme = "light"
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        chrome = QHBoxLayout()
        self.back_button = QPushButton("← 返回主菜单")
        self.back_button.setObjectName("small")
        self.back_button.setFixedSize(116, 36)
        self.back_button.clicked.connect(self.back)
        chrome.addWidget(self.back_button, alignment=Qt.AlignLeft)
        chrome.addStretch(1)
        self.game_menu_button = QPushButton("退出对局")
        self.game_menu_button.setObjectName("small")
        self.game_menu_button.setFixedSize(120, 36)
        self.game_menu_button.clicked.connect(self.return_current_game)
        chrome.addWidget(self.game_menu_button, alignment=Qt.AlignRight)
        self.game_menu_button.hide()
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themeToggle")
        self.theme_button.setFixedSize(36, 36)
        self.theme_button.clicked.connect(self.toggle_theme)
        chrome.addWidget(self.theme_button, alignment=Qt.AlignRight)
        outer.addLayout(chrome)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.pages: dict[str, QWidget] = {}
        self.stack.addWidget(self._make_menu())
        for key, title, _sub in MENU_ENTRIES:
            if key == "codex":
                if db is None:
                    from db.loader import CardDatabase
                    db = CardDatabase.load()
                from client.gui.codex import ShikigamiCodexView
                self.pages[key] = ShikigamiCodexView(db)
            elif key in ("builder", "hotseat", "online"):
                if db is None:
                    from db.loader import CardDatabase
                    db = CardDatabase.load()
                kwargs = {} if store_path is None else {"store_path": store_path}
                if key == "builder":
                    from client.gui.builder import DeckBuilderView
                    self.pages[key] = DeckBuilderView(db, **kwargs)
                elif key == "hotseat":
                    from client.gui.battle import HotseatView
                    self.pages[key] = HotseatView(db, on_back=self.go_menu, **kwargs)
                else:
                    from client.gui.online import OnlineView
                    self.pages[key] = OnlineView(db, on_back=self.go_menu, **kwargs)
            else:
                self.pages[key] = self._make_placeholder(title)
            self.stack.addWidget(self.pages[key])
        self.back_button.hide()
        self.set_theme(self.theme)

    def set_theme(self, theme: str):
        self.theme = theme
        self.setStyleSheet(qss(theme))
        self.theme_button.setIcon(_theme_icon(theme))
        self.theme_button.setIconSize(QSize(20, 20))
        self.theme_button.setToolTip("切换到深色主题" if theme == "light" else "切换到浅色主题")
        for key in ("builder", "hotseat", "online"):
            page = self.pages.get(key)
            if hasattr(page, "apply_theme"):
                page.apply_theme(theme, THEMES[theme])

    def toggle_theme(self):
        self.set_theme("dark" if self.theme == "light" else "light")

    def go(self, key: str):
        self.stack.setCurrentWidget(self.pages[key])
        self.back_button.show()
        self.game_menu_button.setVisible(key in ("hotseat", "online"))

    def return_current_game(self) -> None:
        page = self.stack.currentWidget()
        hook = getattr(page, "return_to_menu", None)
        if callable(hook):
            hook()
        else:
            self.go_menu()

    def back(self):
        """统一返回入口；热坐/联机先执行各自的断线与计时器清理。"""
        page = self.stack.currentWidget()
        for hook_name in ("return_to_menu", "leave_to_menu"):
            hook = getattr(page, hook_name, None)
            if callable(hook):
                if hook() is False:
                    return
                self.go_menu()
                return
        self.go_menu()

    def go_menu(self):
        self.stack.setCurrentIndex(0)
        self.back_button.hide()
        self.game_menu_button.hide()

    def closeEvent(self, event):
        page = self.stack.currentWidget()
        for hook_name in ("return_to_menu", "leave_to_menu"):
            hook = getattr(page, hook_name, None)
            if callable(hook):
                if hook() is False:
                    event.ignore()
                    return
                break
        event.accept()

    def _make_menu(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(60, 40, 60, 40)
        title = QLabel("BWPro")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        lay.addSpacing(40)
        for key, name, desc in MENU_ENTRIES:
            btn = QPushButton(f"{name}\n{desc}")
            btn.setMinimumHeight(100)
            btn.clicked.connect(lambda _=False, k=key: self.go(k))
            lay.addWidget(btn)
        lay.addStretch(1)
        foot = QLabel("个人学习项目 · 与官方无关 · 素材版权归属原作者")
        foot.setObjectName("subtitle")
        foot.setAlignment(Qt.AlignCenter)
        lay.addWidget(foot)
        return page

    def _make_placeholder(self, title: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(40, 30, 40, 30)
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
