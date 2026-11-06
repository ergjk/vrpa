"""DSH-WeChat-Agent（Vision-RPA Edition）V1.0。

包结构：docs/技术方案-V1.0.md §3.1
施工顺序：docs/行动清单-V1.0.md（M0 -> M6）
红线：V1.1/V1.2 的具体实现禁止进入本包；最多只在 core/interfaces.py 保留空接口。
"""

__version__ = "0.1.0"
__all__ = ["__version__"]

from dsh_rpa.logging import configure_logging_namespace as _configure_logging_ns

# 应用层注入 logger 命名空间与环境变量优先级（框架默认中性值 dsh_rpa）
_configure_logging_ns("wechat_agent", data_dir_env=("DSH_RPA_DATA_DIR", "WECHAT_AGENT_DATA_DIR"))
