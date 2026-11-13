"""设置：卡背选择、卡图缓存状态与确认后的全量重建。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from client.gui.loading import LoadingIndicator, LoadingOverlay
from client.gui.prewarm import MANIFEST_NAME, prewarm_all
from client.gui.ui_assets import (
    animation_variants, load_gui_settings, named_cardbacks, normalize_player_name,
    save_gui_settings, turn_button_variants, ui_pixmap, unnamed_misc_images,
)
from client.gui.widgets import ask_confirmation, polish_dialog_buttons
from core.version import VERSION


class CardbackPreviewDialog(QDialog):
    """每页五张的卡背预览；仅确认后由设置页保存。"""

    page_size = 5

    def __init__(self, names: list[str], current: str, parent=None, *,
                 asset_dir="cardbacks", asset_prefix="", icon_size=QSize(132, 188),
                 button_size=(154, 232), title="选择卡背"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.names = names
        self.asset_dir = asset_dir
        self.asset_prefix = asset_prefix
        self.icon_size = icon_size
        self.button_size = button_size
        self.selected = current if current in names else (names[0] if names else "")
        self.page = max(0, names.index(self.selected) // self.page_size) if self.selected else 0
        self.card_buttons = []
        layout = QVBoxLayout(self)
        self.cards_layout = QHBoxLayout()
        self.cards_layout.setSpacing(10)
        layout.addLayout(self.cards_layout)
        pager = QHBoxLayout()
        self.previous_button = QPushButton("上一页")
        self.next_button = QPushButton("下一页")
        for button in (self.previous_button, self.next_button):
            button.setObjectName("small")
        self.previous_button.clicked.connect(lambda: self.turn_page(-1))
        self.next_button.clicked.connect(lambda: self.turn_page(1))
        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignCenter)
        pager.addWidget(self.previous_button)
        pager.addWidget(self.page_label, 1)
        pager.addWidget(self.next_button)
        layout.addLayout(pager)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet("""
            QToolButton#cardbackPreview { padding: 6px; border: 2px solid transparent; }
            QToolButton#cardbackPreview:checked {
                background: #cfe5f7; color: #17344d; border: 2px solid #75a9d0;
                border-radius: 6px;
            }
        """)
        self._render_page()

    def _render_page(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.card_buttons = []
        start = self.page * self.page_size
        for name in self.names[start:start + self.page_size]:
            button = QToolButton()
            button.setObjectName("cardbackPreview")
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setText(name)
            button.setIcon(QIcon(ui_pixmap(
                f"{self.asset_dir}/{self.asset_prefix}{name}.png")))
            button.setIconSize(self.icon_size)
            button.setFixedSize(*self.button_size)
            button.setCheckable(True)
            button.setChecked(name == self.selected)
            button.clicked.connect(lambda _checked=False, name=name: self._select(name))
            self.cards_layout.addWidget(button)
            self.card_buttons.append(button)
        pages = max(1, (len(self.names) + self.page_size - 1) // self.page_size)
        self.page_label.setText(f"{self.page + 1} / {pages}")
        self.previous_button.setEnabled(self.page > 0)
        self.next_button.setEnabled(self.page + 1 < pages)
        self.adjustSize()
        QTimer.singleShot(0, self._center_on_screen)

    def _center_on_screen(self) -> None:
        screen = self.screen()
        if screen is not None:
            self.setGeometry(QStyle.alignedRect(
                Qt.LeftToRight, Qt.AlignCenter, self.size(), screen.availableGeometry()))

    def _select(self, name: str) -> None:
        self.selected = name
        for button in self.card_buttons:
            button.setChecked(button.text() == name)

    def turn_page(self, delta: int) -> None:
        pages = max(1, (len(self.names) + self.page_size - 1) // self.page_size)
        page = min(max(0, self.page + delta), pages - 1)
        if page != self.page:
            self.page = page
            self._render_page()


class SettingsView(QWidget):
    def __init__(self, db, parent=None, on_change=None, on_check_update=None):
        super().__init__(parent)
        self.db = db
        self.on_change = on_change
        self.cache_dir = Path.home() / ".bwpro" / "cardart"
        self.loading_overlay = LoadingOverlay(self)
        self.loading = LoadingIndicator("正在重建卡图", self.loading_overlay.set_text, self)
        layout = QVBoxLayout(self)
        title = QLabel("设置")
        title.setObjectName("viewTitle")
        layout.addWidget(title)
        update_row = QHBoxLayout()
        self.version_label = QLabel(f"当前版本：{VERSION}")
        self.update_button = QPushButton("检查更新")
        self.update_button.setObjectName("small")
        if on_check_update is not None:
            self.update_button.clicked.connect(lambda: on_check_update())
        update_row.addWidget(self.version_label)
        update_row.addWidget(self.update_button)
        update_row.addStretch(1)
        layout.addLayout(update_row)
        self.update_status_label = QLabel()
        self.update_status_label.setWordWrap(True)
        layout.addWidget(self.update_status_label)
        settings = load_gui_settings()
        self.cardback_buttons = {}
        self.option_buttons = {}
        self.option_rows = []

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("玩家名"))
        self.player_name_edit = QLineEdit(settings["player_name"])
        self.player_name_edit.setMaxLength(32)
        self.player_name_edit.setMaximumWidth(240)
        self.player_name_edit.editingFinished.connect(self.save_player_name)
        name_row.addWidget(self.player_name_edit)
        name_row.addStretch(1)
        layout.addLayout(name_row)

        def add_option_row(entries):
            row = QHBoxLayout()
            for key, label in entries:
                button = QPushButton(settings[key] or "无")
                button.setObjectName("small")
                button.setMaximumWidth(150)
                if key == "own_cardback":
                    button.clicked.connect(
                        lambda _checked=False, key=key: self.choose_cardback(key))
                    self.cardback_buttons[key] = button
                else:
                    button.clicked.connect(
                        lambda _checked=False, key=key: self.choose_visual_option(key))
                    self.option_buttons[key] = button
                row.addWidget(QLabel(label))
                row.addWidget(button)
            row.addStretch(1)
            layout.addLayout(row)
            self.option_rows.append(row)

        add_option_row((("own_cardback", "己方卡背"),))
        add_option_row((("turn_background", "回合按钮底图"),
                        ("end_turn_variant", "结束回合样式"),
                        ("opponent_turn_variant", "对手回合样式")))
        add_option_row((("upgrade_variant", "升级样式"), ("defeated_variant", "气绝样式")))
        self.end_turn_background_button = self.option_buttons["turn_background"]
        self.opponent_turn_background_button = self.end_turn_background_button
        self.option_buttons["end_turn_background"] = self.end_turn_background_button
        self.option_buttons["opponent_turn_background"] = self.end_turn_background_button
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.rebuild_button = QPushButton("重新合成全部卡图资源")
        self.rebuild_button.setObjectName("small")
        self.rebuild_button.clicked.connect(self.rebuild)
        layout.addWidget(self.rebuild_button)
        layout.addStretch(1)
        self.refresh_status()

    def save_player_name(self) -> None:
        name = normalize_player_name(self.player_name_edit.text())
        self.player_name_edit.setText(name)
        save_gui_settings({"player_name": name})

    def choose_cardback(self, key: str) -> None:
        button = self.cardback_buttons[key]
        dialog = CardbackPreviewDialog(named_cardbacks(), button.text(), self)
        if dialog.exec() == QDialog.Accepted and dialog.selected:
            button.setText(dialog.selected)
            save_gui_settings({key: dialog.selected})
            if self.on_change is not None:
                self.on_change()

    def choose_visual_option(self, key: str) -> None:
        button = self.option_buttons[key]
        background = key in ("turn_background", "end_turn_background", "opponent_turn_background")
        turn_style = key in ("end_turn_variant", "opponent_turn_variant")
        prefix = {"defeated_variant": "defeat", "upgrade_variant": "up"}.get(
            key, key.split("_")[0])
        names = (["无"] + unnamed_misc_images() if background
                 else turn_button_variants(key == "opponent_turn_variant") if turn_style
                 else animation_variants(prefix))
        asset_prefix = ("" if background else
                        "opponent_turn_button_" if key == "opponent_turn_variant" else
                        "end_turn_button_" if turn_style else prefix + "_")
        dialog = CardbackPreviewDialog(
            names, button.text(), self,
            asset_dir="turn_buttons" if background or turn_style else "animations",
            asset_prefix=asset_prefix,
            icon_size=QSize(128, 128), button_size=(150, 172),
            title="选择" + {
                "turn_background": "回合按钮底图",
                "end_turn_background": "回合结束底图",
                "opponent_turn_background": "对手回合底图",
                "end_turn_variant": "结束回合样式",
                "opponent_turn_variant": "对手回合样式",
                "defeated_variant": "气绝样式", "upgrade_variant": "升级样式",
            }[key])
        if dialog.exec() == QDialog.Accepted:
            selected = dialog.selected
            button.setText(selected)
            save_gui_settings({key: "" if selected == "无" else selected})
            if self.on_change is not None:
                self.on_change()

    def choose_end_turn_background(self) -> None:
        self.choose_visual_option("turn_background")

    def refresh_status(self) -> None:
        path = self.cache_dir / MANIFEST_NAME
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            entries = manifest.get("entries", [])
            updated = manifest.get("updated_at", "未知")
            stats = manifest.get("stats")
            if stats:
                status = (f"卡图缓存：共 {stats['total']} 项，成功 {stats['succeeded']} 项，"
                          f"失败 {stats['failed']} 项，跳过 {stats.get('skipped', 0)} 项")
            else:
                status = f"卡图缓存：{len(entries)} 项"
            lines = [status, f"最近合成：{updated}"]
            if stats:
                for failure in manifest.get("failures", [])[:3]:
                    lines.append(
                        f"失败：{failure.get('kind', '未知')} {failure.get('id', '未知')}"
                        f"（{failure.get('version', '未知')}）：{failure.get('reason', '渲染失败')}")
            lines.append(f"Manifest：{path}")
            self.status_label.setText("\n".join(lines))
        except (OSError, ValueError, TypeError):
            self.status_label.setText("卡图缓存：尚未生成\n启动时会自动检查并合成已配置资源")

    def rebuild(self) -> None:
        if getattr(self.window(), "_prewarm_running", False):
            self.status_label.setText("卡图后台预热进行中，请稍候")
            return
        answer = ask_confirmation(self, "重新合成全部卡图资源",
                                  "将清除现有卡图缓存并重新合成，是否继续？")
        if answer != QMessageBox.Yes:
            return
        self.rebuild_button.setEnabled(False)
        self.loading.start()
        self.loading_overlay.show()
        try:
            prewarm_all(self.db, clear=True,
                        on_progress=lambda current, total: (
                            self.loading.set_progress(current, total), self.loading.tick()))
        finally:
            self.loading.stop()
            self.loading_overlay.hide()
            self.rebuild_button.setEnabled(True)
            self.refresh_status()

    def apply_theme(self, theme: str, colors: dict) -> None:
        self.setStyleSheet(f"""
            QLabel#viewTitle {{ color: {colors['gold']}; font-size: 28px; }}
            QLabel#loadingOverlayText {{ color: {colors['gold']}; font-size: 30px; }}
            LoadingOverlay {{ background: {colors['bg']}; }}
        """)
