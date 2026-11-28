# -*- coding: utf-8 -*-
"""MC Lite 启动器入口"""
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


def main():
    enable_dpi_awareness()
    from mclite.ui_v2 import App
    App().mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        try:
            input("启动器异常退出，按回车关闭…")
        except Exception:
            pass

