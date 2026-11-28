# -*- coding: utf-8 -*-
"""MC Lite 启动器入口

启动顺序（批次5）：
1. 先解析 CLI（--list-instances / --launch / --help），命中则执行并退出；
2. 否则进入 GUI；mclite:// 协议参数先走单实例判断，第二实例转发给主实例后退出；
3. 主实例启动 Tk 界面，并在后台监听协议消息。
"""
import os
import sys
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def enable_dpi_awareness():
    """Windows 高分屏下避免界面模糊"""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            from ctypes import windll
            windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _extract_protocol_arg(argv):
    for a in argv:
        if str(a).lower().startswith("mclite://"):
            return a
    return None


def main():
    enable_dpi_awareness()
    argv = list(sys.argv[1:])
    proto_arg = _extract_protocol_arg(argv)
    # CLI 不处理协议 URL（交给 GUI 单实例/协议层）
    cli_argv = [a for a in argv if not str(a).lower().startswith("mclite://")]

    from mclite import cli
    rc = cli.main(cli_argv)
    if rc is not None:
        sys.exit(rc)

    # GUI 路径：单实例判断
    from mclite import protocol
    sock, is_primary = protocol.acquire_single_instance()
    if not is_primary:
        # 已有主实例：把协议 URL（或仅聚焦信号）转发过去，本进程退出，避免多开窗口
        protocol.notify_primary(proto_arg or "FOCUS")
        return
    protocol.start_listener(sock)

    from mclite.ui_v2 import App
    app = App()
    app._protocol_sock = sock
    app.after(300, app._poll_protocol)
    if proto_arg:
        app.after(600, lambda: app._handle_protocol_url(proto_arg))
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        try:
            input("启动器异常退出，按回车关闭…")
        except Exception:
            pass
