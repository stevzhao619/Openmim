"""兼容主入口。

仓库默认入口已切换到 `app.main`。
保留这个文件是为了兼容现有启动脚本、部署配置与手工执行方式。
"""

from app.main import main


if __name__ == "__main__":
    main()
