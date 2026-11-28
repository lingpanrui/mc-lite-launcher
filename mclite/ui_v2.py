# -*- coding: utf-8 -*-
"""MC Lite v2 界面

相对 v1 的改动：
1. 全站中英双语（i18n.py），侧边栏底部一键切换并即时重建
2. 内容下载页改成 PCL2 式：左侧分类栏 + 条件筛选 + 带图标/下载量/来源的资源行
3. 新增「功能投票」页（本地票数）
4. 重做配色、间距与组件（深色卡片 + 绿色主色 + 圆角图标）
"""
import datetime
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from . import i18n, imgcache, modrinth, poll, util
from .i18n import t

# ---------------------------------------------------------------- 主题
BG = "#0f1115"
SIDEBAR = "#121419"
SIDEBAR_ON = "#181d26"
CARD = "#171a20"
CARD2 = "#1d222b"
CARD3 = "#252c38"
LINE = "#2a303b"
TXT = "#e9edf4"
SUB = "#8b93a3"
DIM = "#5f6878"
ACC = "#3ddc84"
ACC2 = "#2fb56e"
ACC_HOVER = "#57e796"
WARN = "#f0b429"
DANGER = "#e06c75"

NAV = [
    ("home", "◆"),
    ("versions", "▣"),
    ("content", "◈"),
    ("online", "◉"),
    ("poll", "★"),
    ("settings", "⚙"),
]

CONTENT_TYPES = [
    ("mod", "content.tab.mod", "mods"),
    ("modpack", "content.tab.pack", "modpacks"),
    ("shader", "content.tab.shader", "shaderpacks"),
    ("resourcepack", "content.tab.res", "resourcepacks"),
    ("datapack", "content.tab.data", "datapacks"),
]

GAME_VERSIONS = ["", "1.21.4", "1.21.1", "1.20.6", "1.20.4", "1.20.2", "1.20.1",
                 "1.19.4", "1.18.2", "1.16.5", "1.12.2"]
LOADERS = ["", "fabric", "forge", "neoforge", "quilt"]


def F(size=10, bold=False):
    fam = i18n.font_family()
    return (fam, size, "bold") if bold else (fam, size)


def label(parent, text="", color=TXT, size=10, bold=False, bg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or parent["bg"], fg=color,
                    font=F(size, bold), anchor="w", **kw)


def divider(parent, pady=0):
    f = tk.Frame(parent, bg=LINE, height=1)
    f.pack(fill="x", pady=pady)
    return f


def human_count(n):
    n = int(n or 0)
    if i18n.get_lang() == "en":
        if n >= 1000000:
            return "%.1fM" % (n / 1000000.0)
        if n >= 1000:
            return "%.1fK" % (n / 1000.0)
        return str(n)
    if n >= 100000000:
        return "%.1f 亿" % (n / 100000000.0)
    if n >= 10000:
        return "%.1f 万" % (n / 10000.0)
    return str(n)


def clip_text(text, cn=34, en=78):
    s = " ".join(str(text or "").split())
    is_cn = any("\u4e00" <= ch <= "\u9fff" for ch in s)
    limit = cn if is_cn else en
    return s if len(s) <= limit else s[: limit - 1] + "…"


def latest_mc_version(hit):
    versions = hit.get("versions") or []
    stable = [v for v in versions if re.match(r"^1\.\d+(\.\d+)?$", str(v))]
    return stable[-1] if stable else ""


def ago(iso):
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        days = (datetime.datetime.now(datetime.timezone.utc) - dt).days
        if days <= 0:
            return t("time.today")
        if days < 30:
            return t("time.days", n=days)
        if days < 365:
            return t("time.months", n=days // 30)
        return t("time.years", n=days // 365)
    except Exception:
        return ""


# ---------------------------------------------------------------- 组件
class Btn(tk.Label):
    """扁平按钮（Label 模拟，避免 tk.Button 的系统边框）"""

    KINDS = {
        "primary": (ACC, "#08130c", ACC_HOVER),
        "ghost": (CARD2, TXT, CARD3),
        "outline": (CARD, ACC, CARD2),
        "danger": (CARD, DANGER, CARD2),
        "quiet": (CARD, SUB, CARD2),
    }

    def __init__(self, parent, text, command=None, kind="primary", padx=16, pady=7,
                 size=10, bold=True, **kw):
        bg, fg, hover = self.KINDS.get(kind, self.KINDS["primary"])
        super().__init__(parent, text=text, bg=bg, fg=fg, font=F(size, bold),
                         padx=padx, pady=pady, cursor="hand2", **kw)
        self._bg, self._fg, self._hover = bg, fg, hover
        self.command = command
        self.bind("<Enter>", lambda e: self.config(bg=self._hover) if str(self["state"]) != "disabled" else None)
        self.bind("<Leave>", lambda e: self.config(bg=self._bg) if str(self["state"]) != "disabled" else None)
        self.bind("<ButtonRelease-1>", self._click)

    def _click(self, _=None):
        if str(self["state"]) == "disabled":
            return
        if self.command:
            self.command()

    def set_kind(self, kind):
        bg, fg, hover = self.KINDS.get(kind, self.KINDS["primary"])
        self._bg, self._fg, self._hover = bg, fg, hover
        self.config(bg=bg, fg=fg, cursor="hand2" if kind != "quiet" else "arrow")

    def disable(self, text=None):
        self.command = None
        self.config(bg=CARD2, fg=DIM, cursor="arrow")
        self._bg, self._hover = CARD2, CARD2
        if text:
            self.config(text=text)


class ScrollArea(tk.Frame):
    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _sync(self, _=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _wheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()


class ProgressBar(tk.Canvas):
    def __init__(self, parent, bg=CARD2, fg=ACC, height=8):
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0)
        self.bg_color, self.fg_color, self.value = bg, fg, 0.0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, v):
        self.value = max(0.0, min(1.0, v))
        self._draw()

    def _pill(self, x0, y0, x1, y1, color):
        r = (y1 - y0) / 2.0
        if x1 - x0 < 2 * r:
            x1 = x0 + 2 * r
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color, outline="")
        self.create_oval(x0, y0, x0 + 2 * r, y1, fill=color, outline="")
        self.create_oval(x1 - 2 * r, y0, x1, y1, fill=color, outline="")

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            return
        self.delete("all")
        self._pill(0, 0, w, h, self.bg_color)
        if self.value > 0:
            self._pill(0, 0, w * self.value, h, self.fg_color)


class Select(tk.Menubutton):
    def __init__(self, parent, values, value="", width=14, on_change=None, labels=None):
        super().__init__(parent, text="", bg=CARD2, fg=TXT, font=F(10), relief="flat",
                         bd=0, padx=12, pady=7, cursor="hand2", anchor="w",
                         activebackground=CARD3, activeforeground=TXT, width=width)
        self.values = values
        self.labels = labels or (lambda v: v or t("content.all"))
        self.value = value
        self.on_change = on_change
        self.menu = tk.Menu(self, tearoff=0, bg=CARD2, fg=TXT, font=F(10),
                            activebackground=ACC, activeforeground="#08130c",
                            bd=0, activeborderwidth=0)
        for v in values:
            self.menu.add_command(label=self.labels(v), command=lambda v=v: self.set(v))
        self.configure(menu=self.menu)
        self._sync_text()

    def _sync_text(self):
        self.config(text=self.labels(self.value) + "   ▾")

    def set(self, v):
        self.value = v
        self._sync_text()
        if self.on_change:
            self.on_change(v)


class NavButton(tk.Frame):
    def __init__(self, parent, icon, text, command, active=False):
        super().__init__(parent, bg=SIDEBAR)
        self.command = command
        self.active = active
        self.bar = tk.Frame(self, bg=ACC if active else SIDEBAR, width=3)
        self.bar.pack(side="left", fill="y")
        self.body = tk.Frame(self, bg=SIDEBAR_ON if active else SIDEBAR)
        self.body.pack(side="left", fill="both", expand=True)
        self.icon = tk.Label(self.body, text=icon, bg=self.body["bg"],
                             fg=ACC if active else SUB, font=F(12), width=3)
        self.icon.pack(side="left", padx=(8, 0))
        self.text = tk.Label(self.body, text=text, bg=self.body["bg"],
                             fg=TXT if active else SUB, font=F(10, active), anchor="w")
        self.text.pack(side="left", fill="both", expand=True)
        for w in (self, self.body, self.icon, self.text):
            w.bind("<ButtonRelease-1>", lambda e: self.command())
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
            if w is not self:
                w.configure(cursor="hand2")

    def _enter(self, _=None):
        if self.active:
            return
        for w in (self, self.body):
            w.configure(bg=CARD)
        for w in (self.icon, self.text):
            w.configure(bg=CARD)

    def _leave(self, _=None):
        if self.active:
            return
        for w in (self, self.body):
            w.configure(bg=SIDEBAR)
        for w in (self.icon, self.text):
            w.configure(bg=SIDEBAR)


class SubNav(tk.Frame):
    """内容页左侧的小分类项"""

    def __init__(self, parent, text, count, command, active=False):
        super().__init__(parent, bg=BG, cursor="hand2")
        self.command = command
        self.active = active
        bg = CARD if active else BG
        self.bar = tk.Frame(self, bg=ACC if active else BG, width=3)
        self.bar.pack(side="left", fill="y")
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(side="left", fill="both", expand=True)
        self.text = tk.Label(self.body, text=text, bg=bg, fg=TXT if active else SUB,
                             font=F(10, active), anchor="w")
        self.text.pack(side="left", padx=(10, 6), pady=9)
        self.count = tk.Label(self.body, text=str(count), bg=bg, fg=DIM, font=F(9))
        self.count.pack(side="right", padx=(0, 10))
        for w in (self, self.body, self.text, self.count):
            w.bind("<ButtonRelease-1>", lambda e: self.command())

    def _paint(self, bg):
        for w in (self.body, self.text, self.count):
            w.configure(bg=bg)


# ---------------------------------------------------------------- 主窗口
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        i18n.load_lang()
        self.title("MC Lite")
        self.geometry("1240x820")
        self.minsize(1080, 700)
        self.configure(bg=BG)

        self.cfg = util.load_config()
        self.game_dir = self.cfg.get("game_dir") or os.path.join(util.app_root(), "game")

        self.page = "home"
        self.content_type = "mod"
        self.content_query = ""
        self.content_loader = ""
        self.content_version = ""
        self.content_sort = "relevance"
        self.content_hits = []
        self.content_total = 0
        self.content_busy = False
        self.detail_hit = None

        self._build_chrome()
        self.show_page("home")

    # ------------------------------------------------------------ 框架
    def _build_chrome(self):
        self.sidebar = tk.Frame(self, bg=SIDEBAR, width=232)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo = tk.Frame(self.sidebar, bg=SIDEBAR)
        logo.pack(fill="x", padx=18, pady=(22, 18))
        tk.Label(logo, text="⛏", bg=SIDEBAR, fg=ACC, font=F(20)).pack(side="left")
        box = tk.Frame(logo, bg=SIDEBAR)
        box.pack(side="left", padx=(10, 0))
        tk.Label(box, text="MC Lite", bg=SIDEBAR, fg=TXT, font=F(15, True), anchor="w").pack(anchor="w")
        tk.Label(box, text=t("common.v2badge"), bg=SIDEBAR, fg=SUB, font=F(8), anchor="w").pack(anchor="w")

        tk.Frame(self.sidebar, bg=LINE, height=1).pack(fill="x", padx=18, pady=(0, 12))

        self.nav_items = {}
        for key, icon in NAV:
            nb = NavButton(self.sidebar, icon, t("nav." + key), lambda k=key: self.show_page(k),
                           active=(key == self.page))
            nb.pack(fill="x", pady=1)
            self.nav_items[key] = nb

        bottom = tk.Frame(self.sidebar, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x", padx=16, pady=18)
        tk.Label(bottom, text=t("settings.language"), bg=SIDEBAR, fg=DIM, font=F(8), anchor="w").pack(anchor="w", pady=(0, 6))
        lang_row = tk.Frame(bottom, bg=SIDEBAR)
        lang_row.pack(fill="x")
        self.lang_btns = {}
        for code in i18n.LANGS:
            b = Btn(lang_row, i18n.LANG_NAMES[code], lambda c=code: self.switch_lang(c),
                    kind="primary" if code == i18n.get_lang() else "ghost",
                    padx=12, pady=4, size=9, bold=(code == i18n.get_lang()))
            b.pack(side="left", padx=(0, 6))
            self.lang_btns[code] = b
        tk.Label(bottom, text=t("common.v2badge"), bg=SIDEBAR, fg=DIM, font=F(8), anchor="w").pack(anchor="w", pady=(14, 0))

        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        head = tk.Frame(main, bg=BG)
        head.pack(fill="x", padx=28, pady=(24, 6))
        left = tk.Frame(head, bg=BG)
        left.pack(side="left")
        self.h_title = tk.Label(left, text="", bg=BG, fg=TXT, font=F(21, True), anchor="w")
        self.h_title.pack(anchor="w")
        self.h_sub = tk.Label(left, text="", bg=BG, fg=SUB, font=F(10), anchor="w")
        self.h_sub.pack(anchor="w", pady=(4, 0))

        self.badge = tk.Label(head, text=t("common.v2badge"), bg=CARD2, fg=SUB, font=F(8),
                              padx=12, pady=6)
        self.badge.pack(side="right", padx=(12, 0))
        self.head_right = tk.Frame(head, bg=BG)
        self.head_right.pack(side="right")

        self.page_host = tk.Frame(main, bg=BG)
        self.page_host.pack(fill="both", expand=True, padx=28, pady=(12, 8))

        self.status = tk.Label(main, text="", bg=BG, fg=DIM, font=F(9), anchor="w")
        self.status.pack(fill="x", padx=28, pady=(0, 10))

    def set_status(self, text):
        try:
            self.status.config(text=text)
        except Exception:
            pass

    def switch_lang(self, code):
        if code == i18n.get_lang():
            return
        i18n.save_lang(code)
        self.rebuild()

    def rebuild(self):
        page = self.page
        for w in self.winfo_children():
            w.destroy()
        self._build_chrome()
        self.show_page(page)

    def show_page(self, key):
        self.page = key
        for k, nb in getattr(self, "nav_items", {}).items():
            nb.active = (k == key)
            nb.bar.config(bg=ACC if k == key else SIDEBAR)
            for w in (nb, nb.body):
                w.config(bg=SIDEBAR_ON if k == key else SIDEBAR)
            nb.icon.config(bg=SIDEBAR_ON if k == key else SIDEBAR, fg=ACC if k == key else SUB)
            nb.text.config(bg=SIDEBAR_ON if k == key else SIDEBAR, fg=TXT if k == key else SUB,
                          font=F(10, k == key))

        self.h_title.config(text=t(key + ".title" if key != "home" else "home.title"))
        self.h_sub.config(text=t(key + ".sub" if key != "home" else "home.sub"))

        for w in self.page_host.winfo_children():
            w.destroy()
        for w in self.head_right.winfo_children():
            w.destroy()

        builder = {
            "home": self._page_home,
            "versions": self._page_versions,
            "content": self._page_content,
            "online": self._page_online,
            "poll": self._page_poll,
            "settings": self._page_settings,
        }.get(key, self._page_home)
        builder()

    # ------------------------------------------------------------ 首页
    def _stat_card(self, parent, value, title, color=ACC):
        c = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        c.pack(side="left", fill="both", expand=True, padx=(0, 12))
        tk.Label(c, text=str(value), bg=CARD, fg=color, font=F(20, True), anchor="w").pack(anchor="w", padx=18, pady=(14, 0))
        tk.Label(c, text=title, bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", padx=18, pady=(2, 14))

    def installed_versions(self):
        out = []
        vdir = os.path.join(self.game_dir, "versions")
        try:
            for name in os.listdir(vdir):
                p = os.path.join(vdir, name, name + ".json")
                if os.path.isfile(p):
                    meta = util.read_json(p, {}) or {}
                    out.append((name, meta.get("type") or "release", meta.get("__loader") or ""))
        except Exception:
            pass
        return out

    def _page_home(self):
        data = poll.state()
        installed = self.installed_versions()

        stats = tk.Frame(self.page_host, bg=BG)
        stats.pack(fill="x", pady=(0, 18))
        self._stat_card(stats, len(installed), t("home.stat.installed"))
        self._stat_card(stats, human_count(poll.total_votes(data)), t("home.stat.votes"), ACC)
        self._stat_card(stats, "%d / %d" % (len(data["mine"]), len(poll.FEATURES)), t("poll.mine"), WARN)
        self._stat_card(stats, "Modrinth", t("home.stat.platform"), "#5aa7f0")

        tk.Label(self.page_host, text=t("home.quick"), bg=BG, fg=TXT, font=F(13, True), anchor="w").pack(anchor="w", pady=(0, 10))
        grid = tk.Frame(self.page_host, bg=BG)
        grid.pack(fill="x")
        cards = [
            ("▶", "home.card.play.title", "home.card.play.desc", "versions", ACC),
            ("▤", "home.card.content.title", "home.card.content.desc", "content", "#5aa7f0"),
            ("◎", "home.card.online.title", "home.card.online.desc", "online", WARN),
        ]
        for icon, tk_title, tk_desc, target, color in cards:
            c = tk.Frame(grid, bg=CARD, highlightbackground=LINE, highlightthickness=1, height=190)
            c.pack(side="left", fill="x", expand=True, padx=(0, 12))
            c.pack_propagate(False)
            top = tk.Frame(c, bg=CARD)
            top.pack(fill="x", padx=16, pady=(16, 0))
            ic = tk.Label(top, text=icon, bg=CARD2, fg=color, font=F(14), width=3, pady=6)
            ic.pack(side="left")
            tt = tk.Label(top, text=t(tk_title), bg=CARD, fg=TXT, font=F(11, True), anchor="w")
            tt.pack(side="left", padx=(10, 0))
            btn = Btn(c, t("common.open"), lambda tg=target: self.show_page(tg), kind="outline",
                      padx=14, pady=5, size=9)
            btn.pack(side="bottom", anchor="w", padx=16, pady=(0, 14))
            tk.Label(c, text=t(tk_desc), bg=CARD, fg=SUB, font=F(9), anchor="w",
                     wraplength=258, justify="left", height=2).pack(anchor="w", padx=16, pady=(10, 0))

    # ------------------------------------------------------------ 版本
    def _page_versions(self):
        Btn(self.head_right, t("versions.install"), self.open_install, kind="primary",
            padx=14, pady=6, size=9).pack(side="right")

        installed = self.installed_versions()
        if not installed:
            tk.Label(self.page_host, text=t("versions.empty"), bg=CARD, fg=SUB, font=F(10),
                     padx=18, pady=22).pack(fill="x")
            return

        area = ScrollArea(self.page_host, bg=BG)
        area.pack(fill="both", expand=True)
        for vid, vtype, loader in sorted(installed, reverse=True):
            row = tk.Frame(area.inner, bg=CARD)
            row.pack(fill="x", pady=(0, 8))
            icon_box = tk.Frame(row, bg=CARD2, width=44, height=44)
            icon_box.pack(side="left", padx=(14, 12), pady=12)
            icon_box.pack_propagate(False)
            il = tk.Label(icon_box, bg=CARD2)
            il.pack(fill="both", expand=True)
            ph = imgcache.load_photo(None, vid, 40, 9, on_ready=lambda p, w=il: w.config(image=p))
            if ph:
                il.config(image=ph)

            mid = tk.Frame(row, bg=CARD)
            mid.pack(side="left", fill="both", expand=True, pady=12)
            tk.Label(mid, text=vid, bg=CARD, fg=TXT, font=F(11, True), anchor="w").pack(anchor="w")
            meta = "  ".join([x for x in [vtype, loader or t("versions.vanilla")] if x])
            tk.Label(mid, text=meta, bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", pady=(2, 0))

            Btn(row, t("common.launch"), lambda v=vid: self.launch_version(v), kind="ghost",
                padx=14, pady=6, size=9).pack(side="right", padx=(8, 14))
            Btn(row, t("versions.dir"), lambda v=vid: util.open_path(os.path.join(self.game_dir, "versions", v)),
                kind="quiet", padx=10, pady=6, size=8).pack(side="right")

    def launch_version(self, vid):
        self.set_status(t("versions.launching") % vid)
        cfg = self.cfg

        def work():
            try:
                from . import java as jm, mojang
                exe = cfg.get("java_path")
                if not exe or not os.path.isfile(exe):
                    javas = jm.find_javas() or []
                    exe = javas[0][1] if javas else None
                if not exe:
                    self.after(0, lambda: messagebox.showerror(t("common.preview"), t("versions.nojava")))
                    return
                cmd, vj, root, missing = mojang.build_command(
                    self.game_dir, vid, exe, cfg.get("username") or "Steve",
                    int(cfg.get("memory_mb") or 4096), int(cfg.get("width") or 854), int(cfg.get("height") or 480))
                proc = mojang.launch(cmd, self.game_dir)
                self.after(0, lambda: self.set_status(t("versions.launched") % vid))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: messagebox.showerror(t("common.preview"), msg))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 安装新版本
    def open_install(self):
        """安装新版本向导：选游戏版本 + 加载器，带进度条。"""
        from . import mojang

        win = tk.Toplevel(self)
        win.title(t("versions.install.title"))
        win.configure(bg=BG)
        win.geometry("560x400")
        win.transient(self)
        win.resizable(False, False)

        tk.Label(win, text=t("versions.install.title"), bg=BG, fg=TXT, font=F(16, True),
                 anchor="w").pack(fill="x", padx=24, pady=(22, 4))
        tk.Label(win, text=t("versions.install.sub"), bg=BG, fg=SUB, font=F(9),
                 anchor="w", wraplength=480, justify="left").pack(fill="x", padx=24)

        body = tk.Frame(win, bg=BG)
        body.pack(fill="x", padx=24, pady=(16, 0))

        mc_vals = []
        try:
            for item in (mojang.get_manifest() or {}).get("versions", []):
                if item.get("type") == "release" and item.get("id"):
                    mc_vals.append(item["id"])
        except Exception:
            mc_vals = []
        mc_vals = mc_vals[:40]

        tk.Label(body, text=t("versions.install.mc"), bg=BG, fg=SUB, font=F(9),
                 anchor="w").grid(row=0, column=0, sticky="w", pady=6)
        mc_sel = Select(body, mc_vals or ["—"], mc_vals[0] if mc_vals else "—", width=24)
        mc_sel.grid(row=0, column=1, sticky="w", padx=(16, 0), pady=6)

        tk.Label(body, text=t("versions.loader"), bg=BG, fg=SUB, font=F(9),
                 anchor="w").grid(row=1, column=0, sticky="w", pady=6)
        loader_sel = Select(
            body, ["vanilla", "fabric"], "vanilla", width=24,
            labels=lambda v: t("versions.install.vanilla") if v == "vanilla" else "Fabric")
        loader_sel.grid(row=1, column=1, sticky="w", padx=(16, 0), pady=6)

        bar = ProgressBar(win, height=10)
        bar.pack(fill="x", padx=24, pady=(20, 8))
        state = tk.Label(win, text=t("versions.install.note"), bg=BG, fg=DIM, font=F(9),
                         anchor="w", wraplength=480, justify="left")
        state.pack(fill="x", padx=24)

        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=24, pady=(16, 20))

        busy = {"on": False}

        def refresh_btn():
            busy["on"] = False
            go.set_kind("primary")
            go.config(text=t("versions.install.start"))
            go.command = start

        def start():
            if busy["on"]:
                return
            vid = mc_sel.value
            if not vid or vid == "—":
                return
            busy["on"] = True
            go.disable(t("versions.install.busy"))
            bar.set(0.02)

            def on_status(s):
                self.after(0, lambda: state.config(text=s, fg=SUB))

            def on_progress(f):
                self.after(0, lambda: bar.set(max(0.02, float(f))))

            def work():
                try:
                    mm = mojang.manifest_map(mojang.get_manifest())
                    if loader_sel.value == "fabric":
                        out = mojang.install_fabric(self.game_dir, vid, status=on_status,
                                                    progress=on_progress, manifest=mm)
                    else:
                        out = mojang.Installer(self.game_dir, mm, status=on_status,
                                               progress=on_progress).install(vid)[0]
                except Exception as exc:
                    self.after(0, lambda: done_fail(str(exc)))
                    return
                self.after(0, lambda: done_ok(out))

            def done_ok(out):
                bar.set(1.0)
                state.config(text=t("versions.install.done") % out, fg=ACC)
                refresh_btn()
                if self.page == "versions":
                    self.show_page("versions")

            def done_fail(err):
                bar.set(0)
                state.config(text=t("versions.install.fail") % err, fg=DANGER)
                refresh_btn()

            threading.Thread(target=work, daemon=True).start()

        Btn(row, t("versions.install.close"), win.destroy, kind="quiet",
            padx=16, pady=7, size=9).pack(side="right")
        go = Btn(row, t("versions.install.start"), start, kind="primary",
                 padx=18, pady=7, size=10)
        go.pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------ 内容（PCL2 风格）
    def _page_content(self):
        outer = tk.Frame(self.page_host, bg=BG)
        outer.pack(fill="both", expand=True)

        left = tk.Frame(outer, bg=BG, width=176)
        left.pack(side="left", fill="y", padx=(0, 16))
        left.pack_propagate(False)
        tk.Label(left, text=t("content.types"), bg=BG, fg=DIM, font=F(8, True), anchor="w").pack(anchor="w", pady=(4, 8))
        self.type_navs = {}
        for key, tk_key, folder in CONTENT_TYPES:
            sn = SubNav(left, t(tk_key), "", lambda k=key: self._switch_type(k), active=(key == self.content_type))
            sn.pack(fill="x", pady=1)
            self.type_navs[key] = sn

        right = tk.Frame(outer, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        # 筛选卡
        fcard = tk.Frame(right, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        fcard.pack(fill="x", pady=(0, 12))
        row1 = tk.Frame(fcard, bg=CARD)
        row1.pack(fill="x", padx=16, pady=(14, 8))

        tk.Label(row1, text=t("content.filter.name"), bg=CARD, fg=SUB, font=F(9)).pack(side="left", padx=(0, 8))
        self.search_entry = tk.Entry(row1, bg=CARD2, fg=TXT, insertbackground=TXT, relief="flat", bd=0,
                                     highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC,
                                     font=F(10), width=30)
        self.search_entry.pack(side="left", ipady=6, padx=(0, 16))
        self.search_entry.insert(0, self.content_query)
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        tk.Label(row1, text=t("content.filter.source"), bg=CARD, fg=SUB, font=F(9)).pack(side="left", padx=(0, 8))
        self.source_sel = Select(row1, ["", "modrinth"], "", width=10, labels=lambda v: "Modrinth" if v else t("content.all"))
        self.source_sel.pack(side="left", padx=(0, 16))

        tk.Label(row1, text=t("content.filter.sort"), bg=CARD, fg=SUB, font=F(9)).pack(side="left", padx=(0, 8))
        self.sort_sel = Select(row1, ["relevance", "downloads", "newest", "updated"], self.content_sort,
                               width=11, labels=lambda v: t("sort." + v),
                               on_change=lambda v: self._set_sort(v))
        self.sort_sel.pack(side="left")

        row2 = tk.Frame(fcard, bg=CARD)
        row2.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(row2, text=t("content.filter.version"), bg=CARD, fg=SUB, font=F(9)).pack(side="left", padx=(0, 8))
        self.version_sel = Select(row2, GAME_VERSIONS, self.content_version, width=12,
                                  on_change=lambda v: setattr(self, "content_version", v))
        self.version_sel.pack(side="left", padx=(0, 16))

        tk.Label(row2, text=t("content.filter.loader"), bg=CARD, fg=SUB, font=F(9)).pack(side="left", padx=(0, 8))
        self.loader_sel = Select(row2, LOADERS, self.content_loader, width=10,
                                 on_change=lambda v: setattr(self, "content_loader", v),
                                 labels=lambda v: v.capitalize() if v else t("content.all"))
        self.loader_sel.pack(side="left", padx=(0, 20))

        Btn(row2, t("content.search.btn"), self._do_search, kind="primary", padx=22, pady=5, size=9).pack(side="left", padx=(0, 8))
        Btn(row2, t("content.reset"), self._reset_filters, kind="ghost", padx=16, pady=5, size=9).pack(side="left")

        # 结果区
        self.result_head = tk.Label(right, text="", bg=BG, fg=SUB, font=F(9), anchor="w")
        self.result_head.pack(fill="x", pady=(0, 8))

        self.result_area = ScrollArea(right, bg=BG)
        self.result_area.pack(fill="both", expand=True)

        if self.content_hits:
            self._render_results()
        else:
            self._do_search()

    def _set_sort(self, v):
        self.content_sort = v
        self._do_search()

    def _switch_type(self, key):
        if key == self.content_type:
            return
        self.content_type = key
        self.content_hits = []
        self.show_page("content")

    def _reset_filters(self):
        self.content_query = ""
        self.content_loader = ""
        self.content_version = ""
        self.content_sort = "relevance"
        self.content_hits = []
        self.show_page("content")

    def _do_search(self):
        if self.content_busy:
            return
        self.content_query = self.search_entry.get().strip() if hasattr(self, "search_entry") else self.content_query
        self.content_busy = True
        if hasattr(self, "result_head"):
            self.result_head.config(text=t("content.loading"))
        self.set_status(t("content.loading"))
        params = dict(project_type=self.content_type, query=self.content_query,
                      loader=self.content_loader or None, game_version=self.content_version or None,
                      limit=24, sort=self.content_sort)

        def work():
            try:
                hits, total = modrinth.search(**params)
                err = None
            except Exception as e:
                hits, total, err = [], 0, str(e)

            def done():
                self.content_busy = False
                self.content_hits = hits
                self.content_total = total
                if err:
                    if hasattr(self, "result_head"):
                        self.result_head.config(text=t("content.fail"))
                    self.set_status(t("content.fail"))
                    return
                self._render_results()
            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _render_results(self):
        area = self.result_area
        area.clear()
        self.result_head.config(text=t("content.count", n=self.content_total))
        self.set_status("")
        for hit in self.content_hits:
            self._resource_row(area.inner, hit)

    def _resource_row(self, parent, hit):
        title = hit.get("title") or hit.get("slug") or "?"
        desc = (hit.get("description") or "").strip()
        cats = [c for c in (hit.get("categories") or []) if c in ("fabric", "forge", "neoforge", "quilt")]
        latest = latest_mc_version(hit)

        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x")
        body = tk.Frame(row, bg=CARD)
        body.pack(fill="x")

        icon_box = tk.Frame(body, bg=CARD2, width=48, height=48)
        icon_box.pack(side="left", padx=(14, 12), pady=12)
        icon_box.pack_propagate(False)
        il = tk.Label(icon_box, bg=CARD2)
        il.pack(fill="both", expand=True)
        ph = imgcache.load_photo(hit.get("icon_url"), title, 46, 10,
                                 on_ready=lambda p, w=il: w.config(image=p))
        if ph:
            il.config(image=ph)

        mid = tk.Frame(body, bg=CARD)
        mid.pack(side="left", fill="both", expand=True, pady=11)

        line1 = tk.Frame(mid, bg=CARD)
        line1.pack(fill="x")
        tk.Label(line1, text=title, bg=CARD, fg=TXT, font=F(11, True), anchor="w").pack(side="left")
        if cats:
            for c in cats[:2]:
                b = tk.Label(line1, text=c.capitalize(), bg=CARD2, fg=ACC, font=F(8), padx=6, pady=1)
                b.pack(side="left", padx=(8, 0))

        if desc:
            tk.Label(mid, text=clip_text(desc), bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", pady=(3, 0))

        meta = tk.Frame(mid, bg=CARD)
        meta.pack(fill="x", pady=(5, 0))
        bits = []
        if latest:
            bits.append(latest)
        bits.append(human_count(hit.get("downloads")) + " " + t("content.downloads"))
        if hit.get("date_modified"):
            bits.append(ago(hit.get("date_modified")))
        tk.Label(meta, text="  ·  ".join(bits), bg=CARD, fg=DIM, font=F(8), anchor="w").pack(side="left")
        tk.Label(meta, text="Modrinth", bg=CARD, fg="#5aa7f0", font=F(8, True), anchor="w").pack(side="left", padx=(12, 0))

        Btn(body, t("content.get"), lambda h=hit: self._download(h), kind="outline",
            padx=16, pady=6, size=9).pack(side="right", padx=(10, 14))


        for w in (row, body, mid, line1, meta):
            w.bind("<ButtonRelease-1>", lambda e, h=hit: self._show_detail(h))
            w.configure(cursor="hand2")
        divider(parent)

    def _show_detail(self, hit):
        self.detail_hit = hit
        for w in self.page_host.winfo_children():
            w.destroy()
        self.h_title.config(text=hit.get("title") or "?")
        self.h_sub.config(text=t("content.detail.sub"))

        top = tk.Frame(self.page_host, bg=BG)
        top.pack(fill="x", pady=(0, 12))
        Btn(top, t("content.detail.back"), lambda: self.show_page("content"), kind="ghost",
            padx=14, pady=5, size=9).pack(side="left")

        hero = tk.Frame(self.page_host, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        hero.pack(fill="x")
        hb = tk.Frame(hero, bg=CARD)
        hb.pack(fill="x", padx=18, pady=18)

        icon_box = tk.Frame(hb, bg=CARD2, width=80, height=80)
        icon_box.pack(side="left", padx=(0, 16))
        icon_box.pack_propagate(False)
        il = tk.Label(icon_box, bg=CARD2)
        il.pack(fill="both", expand=True)
        ph = imgcache.load_photo(hit.get("icon_url"), hit.get("title"), 76, 16,
                                 on_ready=lambda p, w=il: w.config(image=p))
        if ph:
            il.config(image=ph)

        info = tk.Frame(hb, bg=CARD)
        info.pack(side="left", fill="both", expand=True)
        tk.Label(info, text=hit.get("title") or "?", bg=CARD, fg=TXT, font=F(15, True), anchor="w").pack(anchor="w")
        tk.Label(info, text=(hit.get("author") or "") , bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", pady=(2, 6))
        line = tk.Frame(info, bg=CARD)
        line.pack(fill="x")
        for txt, color in [(human_count(hit.get("downloads")), ACC),
                           (ago(hit.get("date_modified")), WARN),
                           ("Modrinth", "#5aa7f0")]:
            if txt:
                tk.Label(line, text=txt, bg=CARD, fg=color, font=F(9, True), anchor="w").pack(side="left", padx=(0, 16))

        Btn(hb, t("content.get"), lambda h=hit: self._download(h), kind="primary",
            padx=18, pady=8, size=10).pack(side="right")

        desc = (hit.get("description") or "").strip()
        tk.Label(self.page_host, text=t("content.detail.desc"), bg=BG, fg=DIM, font=F(8, True), anchor="w").pack(anchor="w", pady=(14, 4))
        tk.Label(self.page_host, text=desc, bg=CARD, fg=SUB, font=F(9), anchor="w",
                 wraplength=900, justify="left", padx=16, pady=12).pack(fill="x")

        gv = self.content_version or latest_mc_version(hit)
        head_txt = t("content.detail.versions")
        if gv:
            head_txt += "  ·  " + gv
        tk.Label(self.page_host, text=head_txt, bg=BG, fg=DIM, font=F(8, True), anchor="w").pack(anchor="w", pady=(16, 6))
        area = ScrollArea(self.page_host, bg=BG)
        area.pack(fill="both", expand=True)
        tk.Label(area.inner, text=t("content.loading"), bg=BG, fg=SUB, font=F(9)).pack(anchor="w")

        pid = hit.get("project_id") or hit.get("slug")

        def work():
            try:
                vers = modrinth.get_versions(pid, gv or None, self.content_loader or None)
            except Exception:
                vers = []

            def done():
                area.clear()
                if not vers:
                    tk.Label(area.inner, text=t("content.novers"), bg=BG, fg=SUB, font=F(9)).pack(anchor="w")
                    return
                for v in vers[:30]:
                    vrow = tk.Frame(area.inner, bg=CARD)
                    vrow.pack(fill="x")
                    vb = tk.Frame(vrow, bg=CARD)
                    vb.pack(fill="x", padx=14, pady=9)
                    tk.Label(vb, text=v.get("name") or v.get("version_number") or "?", bg=CARD, fg=TXT,
                             font=F(10, True), anchor="w").pack(side="left")
                    f = modrinth.primary_file(v) or {}
                    extra = "  ·  ".join([x for x in [
                        ", ".join((v.get("loaders") or [])[:2]),
                        ", ".join((v.get("game_versions") or [])[:2]),
                        "%.1f MB" % ((f.get("size") or 0) / 1048576.0) if f.get("size") else "",
                    ] if x])
                    tk.Label(vb, text=extra, bg=CARD, fg=SUB, font=F(8), anchor="w").pack(side="left", padx=(12, 0))
                    Btn(vb, t("common.download"), lambda vv=v: self._download_version(vv), kind="quiet",
                        padx=12, pady=4, size=8).pack(side="right")
                    divider(area.inner)

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 下载
    def _target_folder(self):
        folder = dict((k, f) for k, _, f in CONTENT_TYPES).get(self.content_type, "mods")
        return os.path.join(self.game_dir, folder)

    def _download(self, hit):
        self.set_status(t("content.downloading") % (hit.get("title") or ""))
        pid = hit.get("project_id") or hit.get("slug")
        ptype = hit.get("project_type") or self.content_type
        folder = self._target_folder()

        def work():
            try:
                if ptype == "modpack":
                    dest = modrinth.download_pack(pid, self.game_dir, self.content_version or None,
                                                  self.content_loader or None, status=lambda s: self.after(0, lambda: self.set_status(s)))
                    msg = t("content.done.pack") % os.path.basename(dest)
                else:
                    saved = modrinth.download_project(pid, folder, self.content_version or None,
                                                      self.content_loader or None,
                                                      status=lambda s: self.after(0, lambda: self.set_status(s)))
                    msg = t("content.done") % len(saved)
                self.after(0, lambda: self.set_status(msg))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.set_status(err))

        threading.Thread(target=work, daemon=True).start()

    def _download_version(self, ver):
        entry = modrinth.primary_file(ver) or {}
        if not entry.get("url"):
            return
        folder = self._target_folder()
        self.set_status(t("content.downloading") % entry.get("filename", ""))

        def work():
            try:
                path, _ = modrinth._download_file_entry(entry, folder, status=lambda s: self.after(0, lambda: self.set_status(s)))
                self.after(0, lambda: self.set_status(t("content.done") % 1))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.set_status(err))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 联机
    def _page_online(self):
        from . import tunnel
        card = tk.Frame(self.page_host, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=18, pady=18)

        tk.Label(inner, text=t("online.port"), bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", pady=(0, 6))
        port_row = tk.Frame(inner, bg=CARD)
        port_row.pack(fill="x")
        self.port_var = tk.StringVar(value="25565")
        e = tk.Entry(port_row, textvariable=self.port_var, bg=CARD2, fg=TXT, insertbackground=TXT,
                     relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                     highlightcolor=ACC, font=F(10), width=12)
        e.pack(side="left", ipady=6, padx=(0, 10))
        Btn(port_row, t("online.detect"), lambda: self._detect_port(), kind="ghost", padx=14, pady=5, size=9).pack(side="left")
        self.tunnel_btn = Btn(port_row, t("online.start"), lambda: self._toggle_tunnel(), kind="primary",
                              padx=16, pady=5, size=9)
        self.tunnel_btn.pack(side="left", padx=(8, 0))

        tk.Label(inner, text=t("online.address"), bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", pady=(18, 6))
        addr_row = tk.Frame(inner, bg=CARD)
        addr_row.pack(fill="x")
        self.addr_var = tk.StringVar(value="—")
        tk.Label(addr_row, textvariable=self.addr_var, bg=CARD2, fg=ACC, font=F(11, True),
                 padx=14, pady=9, anchor="w").pack(side="left", fill="x", expand=True)
        Btn(addr_row, t("online.copy"), lambda: self._copy_addr(), kind="ghost", padx=14, pady=5, size=9).pack(side="left", padx=(10, 0))

        tk.Label(self.page_host, text=t("online.hint"), bg=BG, fg=DIM, font=F(9),
                 anchor="w", wraplength=880, justify="left").pack(fill="x", pady=(12, 0))

        self._tunnel_proc = None

    def _detect_port(self):
        from . import tunnel
        try:
            port = tunnel.detect_lan_port(self.game_dir)
        except Exception:
            port = None
        if port:
            self.port_var.set(str(port))
            self.set_status(t("online.portfound") % port)
        else:
            self.set_status(t("online.portmissing"))

    def _copy_addr(self):
        val = self.addr_var.get()
        if val and val != "—":
            self.clipboard_clear()
            self.clipboard_append(val)
            self.set_status(t("common.copied"))

    def _toggle_tunnel(self):
        from . import tunnel
        if self._tunnel_proc:
            try:
                tunnel.stop_bore(self._tunnel_proc)
            except Exception:
                pass
            self._tunnel_proc = None
            self.tunnel_btn.set_kind("primary")
            self.tunnel_btn.config(text=t("online.start"))
            self.addr_var.set("—")
            self.set_status(t("online.stopped"))
            return
        try:
            port = int(self.port_var.get())
        except Exception:
            self.set_status(t("online.badport"))
            return
        self.set_status(t("online.connecting"))

        def work():
            try:
                def on_addr(a):
                    self.addr_var.set(a)
                    self.set_status(t("online.connected"))

                proc = tunnel.start_bore(
                    port,
                    on_line=lambda s: self.after(0, lambda s=s: self.set_status(s)),
                    on_address=lambda a: self.after(0, lambda a=a: on_addr(a)),
                )
                self._tunnel_proc = proc
                self.after(0, lambda: self.tunnel_btn.config(text=t("online.stop")) or self.tunnel_btn.set_kind("danger"))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.set_status(err))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 投票
    def _page_poll(self):
        data = poll.state()
        ranking = poll.ranking(data)
        top = tk.Frame(self.page_host, bg=BG)
        top.pack(fill="x", pady=(0, 14))
        for val, cap, color in [(human_count(poll.total_votes(data)), t("poll.total"), ACC),
                                ("%d / %d" % (len(data["mine"]), len(poll.FEATURES)), t("poll.mine"), WARN)]:
            c = tk.Frame(top, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            c.pack(side="left", padx=(0, 12))
            tk.Label(c, text=str(val), bg=CARD, fg=color, font=F(16, True), padx=18, pady=10).pack(anchor="w")
            tk.Label(c, text=cap, bg=CARD, fg=SUB, font=F(8), padx=18, pady=6).pack(anchor="w")

        Btn(top, t("poll.reset"), lambda: self._reset_votes(), kind="quiet", padx=14, pady=6, size=8).pack(side="right")

        area = ScrollArea(self.page_host, bg=BG)
        area.pack(fill="both", expand=True)

        max_count = max(data["counts"].values()) or 1
        for idx, fid in enumerate(ranking, 1):
            count = data["counts"][fid]
            voted = fid in data["mine"]

            card = tk.Frame(area.inner, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            card.pack(fill="x", pady=(0, 10))
            body = tk.Frame(card, bg=CARD)
            body.pack(fill="x", padx=16, pady=14)

            rank = tk.Label(body, text="#%d" % idx, bg=CARD2, fg=ACC if idx == 1 else SUB,
                            font=F(11, True), width=4, pady=6)
            rank.pack(side="left", padx=(0, 12))

            icon_box = tk.Frame(body, bg=CARD2, width=42, height=42)
            icon_box.pack(side="left", padx=(0, 12))
            icon_box.pack_propagate(False)
            tk.Label(icon_box, text=t("f.%s.icon" % fid), bg=CARD2, fg=TXT, font=F(15)).pack(fill="both", expand=True)

            mid = tk.Frame(body, bg=CARD)
            mid.pack(side="left", fill="both", expand=True)
            tk.Label(mid, text=t("f.%s.title" % fid), bg=CARD, fg=TXT, font=F(11, True), anchor="w").pack(anchor="w")
            tk.Label(mid, text=t("f.%s.desc" % fid), bg=CARD, fg=SUB, font=F(9), anchor="w",
                     wraplength=520, justify="left").pack(anchor="w", pady=(3, 8))
            bar_row = tk.Frame(mid, bg=CARD)
            bar_row.pack(fill="x")
            pb = ProgressBar(bar_row, bg=CARD2, fg=ACC if idx != 1 else ACC, height=7)
            pb.pack(side="left", fill="x", expand=True, padx=(0, 10))
            pb.set(count / float(max_count))
            tk.Label(bar_row, text=human_count(count), bg=CARD, fg=TXT, font=F(10, True), width=8, anchor="e").pack(side="left")

            b = Btn(body, t("poll.voted") if voted else t("poll.vote"),
                    lambda f=fid: self._vote(f), kind="primary" if not voted else "ghost",
                    padx=18, pady=7, size=9)
            b.pack(side="right", padx=(12, 0))
            if voted:
                b.disable(t("poll.voted"))

        tk.Label(area.inner, text=t("poll.note"), bg=BG, fg=DIM, font=F(8),
                 anchor="w", wraplength=860, justify="left").pack(fill="x", pady=(6, 16))

    def _vote(self, fid):
        ok, count = poll.vote(fid)
        self.show_page("poll")
        self.set_status(t("poll.thanks") if ok else t("poll.already"))

    def _reset_votes(self):
        poll.reset_mine()
        self.show_page("poll")
        self.set_status(t("poll.resetdone"))

    # ------------------------------------------------------------ 设置
    def _page_settings(self):
        from . import java as jm

        area = ScrollArea(self.page_host, bg=BG)
        area.pack(fill="both", expand=True)
        parent = area.inner

        def section(title):
            tk.Label(parent, text=title, bg=BG, fg=DIM, font=F(8, True), anchor="w").pack(anchor="w", pady=(6, 6))
            c = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            c.pack(fill="x", pady=(0, 14))
            inner = tk.Frame(c, bg=CARD)
            inner.pack(fill="x", padx=16, pady=16)
            return inner

        # 语言
        box = section(t("settings.language"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        for code in i18n.LANGS:
            Btn(row, i18n.LANG_NAMES[code], lambda c=code: self.switch_lang(c),
                kind="primary" if code == i18n.get_lang() else "ghost",
                padx=18, pady=6, size=9).pack(side="left", padx=(0, 8))

        # 内存
        box = section(t("settings.memory"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        self.mem_var = tk.StringVar(value=str(self.cfg.get("memory_mb") or 4096))
        e = tk.Entry(row, textvariable=self.mem_var, bg=CARD2, fg=TXT, insertbackground=TXT,
                     relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                     highlightcolor=ACC, font=F(10), width=10)
        e.pack(side="left", ipady=5, padx=(0, 10))
        tk.Label(row, text="MB", bg=CARD, fg=SUB, font=F(9)).pack(side="left", padx=(0, 14))
        Btn(row, t("common.save"), self._save_memory, kind="ghost", padx=14, pady=5, size=9).pack(side="left")

        # Java
        box = section(t("settings.java"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        self.java_var = tk.StringVar(value=self.cfg.get("java_path") or "")
        e = tk.Entry(row, textvariable=self.java_var, bg=CARD2, fg=TXT, insertbackground=TXT,
                     relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                     highlightcolor=ACC, font=F(9), width=52)
        e.pack(side="left", ipady=5, padx=(0, 10))
        Btn(row, t("common.browse"), self._pick_java, kind="ghost", padx=12, pady=5, size=9).pack(side="left", padx=(0, 8))
        Btn(row, t("common.save"), self._save_java, kind="ghost", padx=12, pady=5, size=9).pack(side="left")
        detected = jm.find_javas() if False else None  # 避免启动时全盘扫描
        tk.Label(box, text=t("settings.autodetect"), bg=CARD, fg=SUB, font=F(8), anchor="w").pack(anchor="w", pady=(8, 0))

        # 目录
        box = section(t("settings.datadir"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text=self.game_dir, bg=CARD2, fg=TXT, font=F(9), padx=12, pady=7, anchor="w").pack(side="left", fill="x", expand=True)
        Btn(row, t("settings.open"), lambda: util.open_path(self.game_dir), kind="ghost",
            padx=12, pady=5, size=9).pack(side="left", padx=(10, 0))

        # 关于
        box = section(t("settings.about"))
        tk.Label(box, text="MC Lite 正式版 v1.0  ·  MIT  ·  Python + tkinter", bg=CARD, fg=TXT,
                 font=F(10, True), anchor="w").pack(anchor="w")
        tk.Label(box, text=t("settings.about.text"), bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", pady=(4, 0))

    def _save_memory(self):
        try:
            mb = max(1024, int(self.mem_var.get()))
        except Exception:
            self.set_status(t("common.badinput"))
            return
        self.cfg["memory_mb"] = mb
        util.save_config(self.cfg)
        self.set_status(t("common.saved"))

    def _pick_java(self):
        p = filedialog.askopenfilename(title=t("settings.pickjava"), filetypes=[("javaw.exe", "*.exe")])
        if p:
            self.java_var.set(p)

    def _save_java(self):
        self.cfg["java_path"] = self.java_var.get().strip()
        util.save_config(self.cfg)
        self.set_status(t("common.saved"))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()








