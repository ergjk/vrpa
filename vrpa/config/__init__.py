"""VRPA 配置内核（平台无关）。

模块划分：
    env.py        环境变量解析：``VRPA_*`` 优先，旧名回退并打 DeprecationWarning
    validators.py 通用校验原语（映射 / 布尔 / 数字 / 字符串 / 区间 / 比例 / 列表）
    plugin.py     平台配置插件契约 ``PlatformPlugin`` 与注册表 ``PlatformRegistry``
    loader.py     YAML 文档加载、schema 版本检查、v1 -> v2 自动升级、默认值深度合并

本包不依赖应用层；``vrpa/logging.py`` 只依赖 ``env.py``，避免循环导入。
"""
