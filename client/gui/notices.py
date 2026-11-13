"""操作说明与随版本发布的更新内容。"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from client.gui.widgets import polish_dialog_buttons

HELP_TEXT = """基本操作
- 右键点击式神、牌手、手牌或场上的卡牌，查看详情。
- 卡组构筑与式神录中，使用左侧列表和下拉框筛选内容；点击式神查看其卡牌。
- 设置页可调整玩家名、主题、卡背与对局素材样式。

本地热坐
- 升级阶段点击高亮式神进行升级。
- 主要阶段拖动式神出击，或拖动手牌使用卡牌；出现合法目标时按高亮提示选择。
- 多择牌会并列显示所有使用方式；选择不可用项时会显示原因。
- 回合结束或调度完成后，使用“切换玩家”按钮交接操作。

联机对战
- 输入服务器地址与玩家名后连接服务器，再创建房间或输入房码加入。
- 双方选择卡组并准备后开始对战；断线时可凭房码与重连令牌恢复。
- 对局记录按钮可回看已公开的操作与结算信息。

其他
- 主界面右上角切换亮暗主题。
- 卡图在后台合成；后台更新完成前暂不能进入对战。
- 服务器日志可通过独立运维端查看：python -m client.log_admin。"""

RELEASE_NOTES = {
    "0.3.0": """- 新增完整的图形对局界面、卡组构筑与式神录。
- 支持本地热坐和客户端—服务端联机对战。
- 加入卡框、卡背、对局动画与亮暗主题设置。
- 完善卡牌详情、对局记录、开局及交接流程。
- 提供服务端日志运维端、自动检查更新与独立 EXE 发布。
- 修复多项战斗结算、动画顺序、缓存与界面交互问题。""",
}


def show_text_dialog(parent, title: str, text: str) -> None:
    """以固定尺寸只读窗口展示说明，长文本由滚动区域承载。"""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(680, 520)
    layout = QVBoxLayout(dialog)
    browser = QTextBrowser(dialog)
    browser.setPlainText(text)
    browser.setOpenExternalLinks(True)
    layout.addWidget(browser, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
    polish_dialog_buttons(buttons)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
