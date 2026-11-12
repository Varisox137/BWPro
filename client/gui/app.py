"""主窗口：视图栈 + 主菜单 + 全局浅/深主题。"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

import client.update as update
from client.gui.prewarm import prewarm_iter
from client.gui.widgets import ask_confirmation
from core.logging_config import configure_logging

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
    ("settings", "设置", "缓存与资源管理"),
]


def qss(theme: str) -> str:
    t = THEMES[theme]
    selection_bg = "#cfe5f7" if theme == "light" else "#294c68"
    selection_text = "#17344d" if theme == "light" else t["text"]
    selection_hover = "rgba(207, 229, 247, 128)" if theme == "light" else "rgba(41, 76, 104, 128)"
    return f"""
    QMainWindow, QWidget {{ background: {t['bg']}; color: {t['text']}; }}
    QListWidget, QTreeWidget {{ outline: none; }}
    QListWidget::item, QTreeWidget::item {{ border: none; }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTreeWidget::branch:selected {{
        background: {selection_bg}; color: {selection_text}; border: none;
    }}
    QListWidget::item:hover, QTreeWidget::item:hover, QComboBox QAbstractItemView::item:hover {{
        background: {selection_hover}; color: {selection_text}; border: none;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background: {selection_bg}; color: {selection_text}; border: none;
    }}
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


def _application_icon() -> QIcon:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return QIcon(str(root / "assets" / "app_icon.ico"))


class MainWindow(QMainWindow):
    def __init__(self, db=None, store_path=None):
        super().__init__()
        self.setWindowTitle("BWPro by Varisox137")
        self.setWindowIcon(_application_icon())
        self.resize(1600, 900)
        self.theme = "light"
        self._update_generation = 0
        self._update_closed = False
        self._update_checking = False
        self._update_downloading = False
        self._update_cancel = None
        central = QWidget(self)
        self.outer = outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        self.chrome = chrome = QHBoxLayout()
        self.back_button = QPushButton("返回主菜单")
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
            if key == "settings":
                if db is None:
                    from db.loader import CardDatabase
                    db = CardDatabase.load()
                from client.gui.settings import SettingsView
                self.pages[key] = SettingsView(
                    db, on_check_update=lambda: self.check_for_updates(manual=True))
            elif key == "codex":
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
            self.stack.addWidget(self.pages[key])
        self.pages["hotseat"].stack.currentChanged.connect(self._sync_game_menu_button)
        self.pages["hotseat"].state_changed.connect(self._sync_game_menu_button)
        self.pages["online"].stack.currentChanged.connect(self._sync_game_menu_button)
        self.back_button.hide()
        self.set_theme(self.theme)
        self.db = db
        self._prewarm_timer = QTimer(self)
        self._prewarm_timer.setInterval(0)
        self._prewarm_timer.timeout.connect(self._advance_prewarm)
        self._prewarm_iterator = None

    def prewarm_resources(self) -> None:
        if self._prewarm_timer.isActive():
            return
        self._prewarm_iterator = prewarm_iter(self.db)
        self._prewarm_timer.start()

    def _advance_prewarm(self) -> None:
        try:
            current, total = next(self._prewarm_iterator)
        except StopIteration:
            self._finish_prewarm()
        else:
            self.statusBar().showMessage(f"卡图后台同步 {current}/{total}")

    def _finish_prewarm(self) -> None:
        self._prewarm_timer.stop()
        self._prewarm_iterator = None
        self.statusBar().clearMessage()
        self.pages["settings"].refresh_status()

    def set_theme(self, theme: str):
        self.theme = theme
        QApplication.instance().setProperty("bwpro_theme", theme)
        self.setStyleSheet(qss(theme))
        self.theme_button.setIcon(_theme_icon(theme))
        self.theme_button.setIconSize(QSize(20, 20))
        self.theme_button.setToolTip("切换到深色主题" if theme == "light" else "切换到浅色主题")
        for key in ("builder", "codex", "hotseat", "online", "settings"):
            page = self.pages.get(key)
            if hasattr(page, "apply_theme"):
                page.apply_theme(theme, THEMES[theme])

    def toggle_theme(self):
        self.set_theme("dark" if self.theme == "light" else "light")

    def _sync_game_menu_button(self, *_args) -> None:
        page = self.stack.currentWidget()
        online = self.pages["online"]
        hotseat_battle = (
            page is self.pages["hotseat"]
            and self.pages["hotseat"].stack.currentWidget()
                is self.pages["hotseat"].battle_page
        )
        online_battle = page is online and online.stack.currentWidget() is online.battle
        in_battle = hotseat_battle or online_battle
        self.game_menu_button.setVisible(in_battle)
        self.game_menu_button.setText("游戏设置" if hotseat_battle else "退出对局")
        hotseat = self.pages["hotseat"]
        hotseat_finished = (hotseat_battle and hotseat.game is not None
                            and hotseat.game.state.winner is not None)
        self.back_button.setText(
            "返回主菜单" if not hotseat_battle or hotseat_finished else "退出对局")
        margin = 0 if in_battle else 12
        self.outer.setContentsMargins(margin, margin, margin, margin)
        chrome_margin = 12 if in_battle else 0
        self.chrome.setContentsMargins(chrome_margin, chrome_margin, chrome_margin, 0)

    def go(self, key: str):
        self.stack.setCurrentWidget(self.pages[key])
        self.back_button.show()
        self._sync_game_menu_button()

    def return_current_game(self) -> None:
        page = self.stack.currentWidget()
        hook_name = "open_settings" if page is self.pages["hotseat"] else "leave_to_menu"
        hook = getattr(page, hook_name, None)
        if callable(hook):
            hook()
        else:
            self.go_menu()

    def back(self):
        """统一返回入口；联机页保留连接与房间状态，其余页面沿用原清理。"""
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
        self._sync_game_menu_button()

    def closeEvent(self, event):
        self._finish_prewarm()
        page = self.stack.currentWidget()
        for hook_name in ("return_to_menu", "leave_to_menu"):
            hook = getattr(page, hook_name, None)
            if callable(hook):
                if hook() is False:
                    event.ignore()
                    return
                break
        self._update_closed = True
        self._update_generation += 1
        if self._update_cancel is not None:
            self._update_cancel.set()
        event.accept()

    def in_battle(self) -> bool:
        page = self.stack.currentWidget()
        hotseat = self.pages["hotseat"]
        online = self.pages["online"]
        return ((page is hotseat and hotseat.stack.currentWidget() is hotseat.battle_page)
                or (page is online and online.stack.currentWidget() is online.battle))

    def _update_callback_valid(self, generation: int) -> bool:
        return not self._update_closed and generation == self._update_generation

    def _post_update_callback(self, generation: int, callback, *args) -> None:
        def deliver():
            if self._update_callback_valid(generation):
                callback(generation, *args)
        QTimer.singleShot(0, self, deliver)

    def _start_update_worker(self, generation: int, action, callback) -> None:
        def run():
            try:
                result = action()
            except Exception as error:
                self._post_update_callback(generation, callback, None, error)
            else:
                self._post_update_callback(generation, callback, result, None)
        threading.Thread(target=run, daemon=True).start()

    def check_for_updates(self, manual: bool = True) -> None:
        if self._update_closed or self._update_checking or self._update_downloading:
            return
        self._update_generation += 1
        generation = self._update_generation
        self._update_checking = True
        settings = self.pages["settings"]
        settings.update_button.setEnabled(False)
        if manual:
            settings.update_status_label.setText("正在检查更新…")
        self._start_update_worker(
            generation, update.check_for_update, self._update_check_finished)

    def _update_check_finished(self, generation: int, available, error) -> None:
        self._update_checking = False
        settings = self.pages["settings"]
        settings.update_button.setEnabled(True)
        if error is not None:
            if settings.update_status_label.text():
                settings.update_status_label.setText(f"检查更新失败：{error}")
            return
        if available is None:
            if settings.update_status_label.text():
                settings.update_status_label.setText("当前已是最新版本")
            return
        settings.update_status_label.setText(f"发现新版本：{available.tag}")
        answer = ask_confirmation(
            self, "发现新版本", f"当前版本 v{update.VERSION}，发现 {available.tag}。是否下载更新？")
        if answer == QMessageBox.Yes:
            self._start_update_download(generation, available)

    def _update_staging_path(self, available) -> Path:
        if getattr(sys, "frozen", False):
            executable = Path(sys.executable).resolve()
            return executable.with_name(executable.name + ".new")
        return Path.home() / ".bwpro" / "downloads" / (available.exe_name + ".new")

    def _start_update_download(self, generation: int, available) -> None:
        self._update_downloading = True
        self._update_cancel = threading.Event()
        staged = self._update_staging_path(available)
        settings = self.pages["settings"]
        settings.update_button.setEnabled(False)
        settings.update_status_label.setText(f"正在下载 {available.tag}…")
        self._start_update_worker(
            generation,
            lambda: update.download_update(available, staged, cancel_event=self._update_cancel),
            self._update_download_finished)

    def _update_download_finished(self, generation: int, downloaded, error) -> None:
        self._update_downloading = False
        self._update_cancel = None
        settings = self.pages["settings"]
        settings.update_button.setEnabled(True)
        if error is not None:
            settings.update_status_label.setText(f"更新下载未完成：{error}")
            return
        if not getattr(sys, "frozen", False):
            settings.update_status_label.setText(
                f"更新已下载并校验：{downloaded.path}\n开发环境不替换或重启当前程序")
            return
        warning = "\n当前对局将随主程序退出。" if self.in_battle() else ""
        answer = ask_confirmation(
            self, "重启并安装更新",
            f"{downloaded.available.tag} 已下载并通过 SHA-256 校验。{warning}\n"
            "是否现在退出主程序、替换旧版本并重启？")
        if answer != QMessageBox.Yes:
            settings.update_status_label.setText("更新已下载；未确认重启，当前程序继续运行")
            return
        try:
            update.launch_update(downloaded.path, downloaded.sha256)
        except Exception as error:
            settings.update_status_label.setText(f"无法启动更新程序：{error}")
            return
        QApplication.quit()

    def _make_menu(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(60, 40, 60, 40)
        title = QLabel(
            'BWPro by <a href="https://github.com/Varisox137/BWPro" '
            'style="text-decoration:underline">Varisox137</a>')
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        title.setOpenExternalLinks(True)
        lay.addWidget(title)
        lay.addSpacing(24)
        for key, name, desc in MENU_ENTRIES:
            btn = QPushButton(f"{name}\n{desc}")
            btn.setMinimumHeight(100)
            btn.clicked.connect(lambda _=False, k=key: self.go(k))
            lay.addWidget(btn)
        lay.addStretch(1)
        return page

def main(*, cleanup=None) -> int:
    configure_logging("gui")
    if cleanup is not None:
        update.schedule_update_cleanup(*cleanup)
    app = QApplication(sys.argv)
    app.setWindowIcon(_application_icon())
    win = MainWindow()
    win.show()
    win.prewarm_resources()
    win.check_for_updates(manual=False)
    return app.exec()
