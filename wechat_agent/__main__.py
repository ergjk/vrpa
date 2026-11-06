"""`python -m wechat_agent` 的入口。

本文件只做两件事：调用 main()、把返回值转成进程退出码。
所有业务逻辑都在 wechat_agent.main 与各层模块中；本文件保持稳定，不承载逻辑。
"""

from wechat_agent.main import main

if __name__ == "__main__":
    raise SystemExit(main())
