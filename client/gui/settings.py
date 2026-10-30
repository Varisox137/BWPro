"""设置：卡图缓存状态与确认后的全量重建。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from client.gui.loading import LoadingIndicator, LoadingOverlay
from client.gui.prewarm import MANIFEST_NAME, prewarm_all
from client.gui.widgets import ask_confirmation


class SettingsView(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.cache_dir = Path.home() / ".bwpro" / "cardart"
        self.loading_overlay = LoadingOverlay(self)
        self.loading = LoadingIndicator("正在重建卡图", self.loading_overlay.set_text, self)
        layout = QVBoxLayout(self)
        title = QLabel("设置")
        title.setObjectName("viewTitle")
        layout.addWidget(title)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.rebuild_button = QPushButton("重新合成全部卡图资源")
        self.rebuild_button.setObjectName("small")
        self.rebuild_button.clicked.connect(self.rebuild)
        layout.addWidget(self.rebuild_button)
        layout.addStretch(1)
        self.refresh_status()

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
        timer = getattr(self.window(), "_prewarm_timer", None)
        if timer is not None and timer.isActive():
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
