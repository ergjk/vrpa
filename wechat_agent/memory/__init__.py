"""记忆层：双库（chat_history / memory）读写、去重对齐、长期记忆提炼。

交付里程碑：M0-06（建库与迁移）、M3（流水读写 / dedup / 多端判定 / 提炼）。
纪律：消息内容只从 conversation 字符串流入，不得引入视觉识别。
"""

__all__: list[str] = []
