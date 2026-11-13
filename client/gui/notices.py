"""操作说明与随版本发布的更新内容。"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from client.gui.widgets import polish_dialog_buttons

HELP_TEXT = """基本操作
- 右键点击式神、牌手、手牌或场上的卡牌，查看详情。
- 卡组构筑与式神录中，使用左侧列表和下拉框筛选内容；点击式神查看其卡牌。
- 设置页可调整玩家名、主题、卡背与对局素材样式。

本地热坐
- 开局前可选择平衡性环境，并按需启用 DIY 内容。
- 升级阶段点击高亮式神进行升级。
- 主要阶段拖动式神出击，或拖动手牌使用卡牌；出现合法目标时按高亮提示选择。
- 多择牌会并列显示所有使用方式；选择不可用项时会显示原因。
- 回合结束或调度完成后，使用“切换玩家”按钮交接操作。

联机对战
- 输入服务器地址与玩家名后连接服务器，再创建房间或输入房码加入。
- 正式开局后掉线会使用公网 IP 与本人识别码自动重连；准备阶段掉线不保留座位。
- 对局记录按钮可回看已公开的操作与结算信息。

其他
- 主界面右上角切换亮暗主题。
- 卡图在后台合成；后台更新完成前暂不能进入对战。
- 服务器日志可通过独立运维端查看：python -m client.log_admin。"""

RELEASE_NOTES = {
    "0.3.4": """- 数据环境与卡组规则拆分为独立选项，自由规则可校验并使用非标准 DIY 卡组。
- 修复热坐/联机 DIY 卡组过滤与式神录首次点击 DIY 跳选问题。
- 统一下拉框、勾选框的亮暗主题背景、边框和选中样式。
- 等待对手的房主断线后保留房间，避免短时间自动回收。""",
    "0.3.3": """- 本地热坐新增环境与 DIY 选项，联机支持按 DIY 勾选刷新卡组。
- 优化联机大厅状态与退出服务器流程。
- 公网 IP 改用 ipify/ifconfig.me 查询，正式开局后支持识别码自动重连。
- 屏蔽含凭证和私密状态的 WebSocket DEBUG 帧日志。""",
    "0.3.2": """- 新增可分包扩展的 DIY 内容运行时与首个移动主题内容包。
- 联机支持准备后的 DIY 完整包双向同步、冲突校验和下载内容清理。
- 修复手牌动画终点、爆能结算、觉醒动画与详情增强文本。
- 优化卡图角标、爆能选项、机制框对齐及牌手破甲图标。
- 服务端日志提取码输出增加秒级时间。""",
    "0.3.1": """- 设置页新增操作说明，并加入按版本首次启动的更新提示。
- 优化开局阵容与先后手动画的节奏、尺寸和画面裁剪。
- 修复 EXE 任务栏图标与热坐交接按钮位置。
- 过滤 WebSocket 心跳日志噪声，日志按 15 天、两类各 10 份保留。
- 联机默认服务器地址更新为 bwpro.varisox137.top。""",
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
