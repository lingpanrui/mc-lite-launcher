# -*- coding: utf-8 -*-
"""mclite:// URL 协议 + 单实例判断（批次5）

- 注册到 HKCU\\Software\\Classes\\mclite（当前用户，无需管理员），
  shell\\open\\command 指向 exe 且路径正确加引号："C:\\...\\MCLite-v2.exe" "%1"。
- 支持 mclite://launch?instance=X 与 mclite://join?host=&port=（join 真正联机在批次7，本批解析+提示）。
- 单实例：主实例绑定 127.0.0.1:47821；第二个实例启动时把 URL/FOCUS 发给主实例后退出，
  避免重复开一堆窗口。
"""
import collections
import os
import socket
import sys
import threading
import urllib.parse

PROTOCOL = "mclite"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 47821
_CLASSES_KEY = r"Software\Classes\mclite"

_pending = collections.deque()
_listener_started = False
_server_sock = None
_mutex_handle = None


# ---------------------------------------------------------------- 注册表
def _winreg():
    try:
        import winreg
        return winreg
    except Exception:
        return None


def current_exe():
    """打包后返回 exe 路径；开发态返回 None（由 UI 传入实际 exe）。"""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return None


def register(exe_path=None):
    """注册协议（HKCU，无需管理员）。返回 (ok, command)。"""
    winreg = _winreg()
    if winreg is None:
        return False, "非 Windows"
    exe = os.path.abspath(exe_path or current_exe() or "")
    if not exe or not os.path.isfile(exe):
        return False, "找不到 exe 路径"
    command = '"%s" "%%1"' % exe
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _CLASSES_KEY, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:MCLite Launcher Protocol")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _CLASSES_KEY + r"\shell\open\command",
                                0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)
        return True, command
    except Exception as e:
        return False, str(e)


def unregister():
    """删除协议注册树。返回 (ok, msg)。"""
    winreg = _winreg()
    if winreg is None:
        return False, "非 Windows"

    def _delete_tree(root, path):
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    _delete_tree(root, path + "\\" + sub)
        except FileNotFoundError:
            return
        try:
            winreg.DeleteKey(root, path)
        except OSError:
            pass

    try:
        _delete_tree(winreg.HKEY_CURRENT_USER, _CLASSES_KEY)
        return True, "已取消注册"
    except Exception as e:
        return False, str(e)


def is_registered(exe_path=None):
    """返回 (registered, command)。registered 要求命令指向当前 exe（若提供）。"""
    winreg = _winreg()
    if winreg is None:
        return False, ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CLASSES_KEY + r"\shell\open\command",
                            0, winreg.KEY_READ) as k:
            cmd, _ = winreg.QueryValueEx(k, "")
    except FileNotFoundError:
        return False, ""
    except OSError:
        return False, ""
    exe = os.path.abspath(exe_path or current_exe() or "")
    if exe:
        return (exe.lower() in cmd.lower()), cmd
    return True, cmd


# ---------------------------------------------------------------- URL 解析
def parse_url(url):
    """解析 mclite://... 。返回 {action, instance, host, port, raw}；非法抛 ValueError。"""
    if not url or not str(url).lower().startswith(PROTOCOL + "://"):
        raise ValueError("不是 mclite:// 链接：%r" % url)
    parsed = urllib.parse.urlparse(url)
    action = (parsed.netloc or "").lower()
    if action not in ("launch", "join"):
        raise ValueError("不支持的协议动作：%s" % action)
    qs = urllib.parse.parse_qs(parsed.query)
    out = {"action": action, "instance": "", "host": "", "port": "", "raw": url}
    if action == "launch":
        out["instance"] = (qs.get("instance", [""])[0] or "").strip()
        if not out["instance"]:
            raise ValueError("launch 缺少 instance 参数")
    else:
        out["host"] = (qs.get("host", [""])[0] or "").strip()
        out["port"] = (qs.get("port", [""])[0] or "").strip()
        if not out["host"]:
            raise ValueError("join 缺少 host 参数")
    return out


# ---------------------------------------------------------------- 单实例
def acquire_single_instance(port=LISTEN_PORT):
    """单实例判定 + IPC 监听 socket。返回 (sock, is_primary)。

    Windows 用命名互斥量做权威判定（SO_REUSEADDR 在 Windows 允许重复绑定，不能靠端口）；
    非 Windows 退化为端口绑定。主实例持有 sock 用于接收第二实例消息；
    第二实例 is_primary=False，应 notify_primary 后退出。
    """
    global _mutex_handle
    is_primary = True
    if sys.platform.startswith("win"):
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.CreateMutexW.restype = ctypes.c_void_p
            k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
            _mutex_handle = k32.CreateMutexW(None, True, "Local\\MCLiteLauncher_v1_7_SingleInstance")
            if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                is_primary = False
        except Exception:
            is_primary = True

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((LISTEN_HOST, port))
        s.listen(8)
    except OSError:
        s.close()
        s = None
        if not sys.platform.startswith("win"):
            is_primary = False
    return s, is_primary


def release_single_instance():
    global _mutex_handle
    if _mutex_handle is not None:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        except Exception:
            pass
        _mutex_handle = None


def notify_primary(payload, port=LISTEN_PORT, timeout=2.0):
    """第二实例把 URL/FOCUS 发给主实例。返回是否送达。"""
    try:
        with socket.create_connection((LISTEN_HOST, port), timeout=timeout) as c:
            c.sendall(str(payload).encode("utf-8"))
        return True
    except OSError:
        return False


def start_listener(server_sock):
    """主实例后台线程接收第二实例消息，放入待处理队列。"""
    global _listener_started, _server_sock
    if _listener_started or server_sock is None:
        return
    _listener_started = True
    _server_sock = server_sock

    def _serve():
        while True:
            try:
                conn, _addr = server_sock.accept()
            except OSError:
                break
            try:
                data = conn.recv(4096)
                if data:
                    _pending.append(data.decode("utf-8", "replace"))
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    threading.Thread(target=_serve, daemon=True).start()


def pop_pending():
    try:
        return _pending.popleft()
    except IndexError:
        return None


def has_pending():
    return bool(_pending)
