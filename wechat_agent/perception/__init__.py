"""感知层：假 UIA 树定位（M1）与「框选 + 剪贴板」采集解析（M2）。

红线（违反即返工）：
1. 假 UIA 树只服务「操作界面」（切会话 / 点击 / 框选区域），不读取消息内容；
2. 消息内容唯一来源 = capture() 的「鼠标框选 + Ctrl+C」剪贴板文本；
3. capture.py / parser.py / dedup.py 禁止 import cv2 / anchor_match / vision。
"""

__all__: list[str] = []
