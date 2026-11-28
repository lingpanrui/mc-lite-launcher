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
from . import doctor, instances, accounts, forge, quilt
from . import theme
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
ON_ACC = "#08130c"
WARN = "#f0b429"
DANGER = "#e06c75"

NAV = [
    ("home", "◆"),
    ("versions", "▣"),
    ("instances", "❖"),
    ("accounts", "☺"),
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


def label(parent, text="", color=None, size=10, bold=False, bg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or parent["bg"], fg=color or TXT,
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


def parse_jvm_args(text):
    """把界面输入的额外 JVM 参数拆成列表（支持引号），失败则按空白拆分。"""
    import shlex
    s = str(text or "").strip()
    if not s:
        return []
    try:
        return [a for a in shlex.split(s, posix=True) if a]
    except Exception:
        return [a for a in s.split() if a]


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
    def __init__(self, parent, bg=None):
        bg = bg or BG
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
    def __init__(self, parent, bg=None, fg=None, height=8):
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0)
        self.bg_color, self.fg_color, self.value = bg or CARD2, fg or ACC, 0.0
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

    def set_values(self, values, value=None):
        """异步刷新下拉选项（保留当前 on_change/labels）。"""
        self.values = list(values)
        self.menu.delete(0, "end")
        for v in self.values:
            self.menu.add_command(label=self.labels(v), command=lambda v=v: self.set(v))
        if value is not None:
            self.value = value
        self._sync_text()


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
        instances.migrate(self.cfg)
        self._apply_theme()
        self.game_dir = instances.current(self.cfg)["game_dir"]

        self.page = "home"
        self.inst_selected = None
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

    # ------------------------------------------------------------ 主题
    def _apply_theme(self):
        """把选中的配色写回模块级常量，随后重建界面即可生效"""
        th = theme.load(self.cfg)
        g = globals()
        for key in ("BG", "SIDEBAR", "SIDEBAR_ON", "CARD", "CARD2", "CARD3", "LINE",
                    "TXT", "SUB", "DIM", "WARN", "DANGER", "ACC", "ACC2", "ACC_HOVER", "ON_ACC"):
            if key in th:
                g[key] = th[key]
        Btn.KINDS = {
            "primary": (g["ACC"], g["ON_ACC"], g["ACC_HOVER"]),
            "ghost": (g["CARD2"], g["TXT"], g["CARD3"]),
            "outline": (g["CARD"], g["ACC"], g["CARD2"]),
            "danger": (g["CARD"], g["DANGER"], g["CARD2"]),
            "quiet": (g["CARD"], g["SUB"], g["CARD2"]),
        }

    def switch_theme(self, key):
        self.cfg["theme"] = key
        util.save_config(self.cfg)
        self.rebuild()

    def switch_accent(self, key):
        self.cfg["accent"] = key
        util.save_config(self.cfg)
        self.rebuild()

    def switch_lang(self, code):
        if code == i18n.get_lang():
            return
        i18n.save_lang(code)
        self.rebuild()

    def rebuild(self):
        self._apply_theme()
        page = self.page
        for w in self.winfo_children():
            w.destroy()
        self.configure(bg=BG)
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
            "instances": self._page_instances,
            "accounts": self._page_accounts,
            "content": self._page_content,
            "online": self._page_online,
            "poll": self._page_poll,
            "settings": self._page_settings,
        }.get(key, self._page_home)
        builder()

    # ------------------------------------------------------------ 首页
    def _stat_card(self, parent, value, title, color=None):
        c = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        c.pack(side="left", fill="both", expand=True, padx=(0, 12))
        tk.Label(c, text=str(value), bg=CARD, fg=color or ACC, font=F(20, True), anchor="w").pack(anchor="w", padx=18, pady=(14, 0))
        tk.Label(c, text=title, bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", padx=18, pady=(2, 14))

    def current_inst(self):
        return instances.current(self.cfg)

    def inst_display_name(self, inst):
        if inst and inst.get("id") == instances.DEFAULT_ID:
            return t("inst.default_name")
        return (inst or {}).get("name") or "?"

    def installed_versions(self, game_dir=None):
        out = []
        vdir = os.path.join(game_dir or self.game_dir, "versions")
        try:
            for name in os.listdir(vdir):
                p = os.path.join(vdir, name, name + ".json")
                if os.path.isfile(p):
                    meta = util.read_json(p, {}) or {}
                    ld = forge.detect_loader(meta)
                    if ld == "vanilla":
                        ld = ""
                    out.append((name, meta.get("type") or "release", ld))
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

        # 当前实例条：切换后首页统计 / 版本列表 / 诊断都读这个实例目录
        cur = self.current_inst()
        bar = tk.Frame(self.page_host, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        bar.pack(fill="x", pady=(0, 18))
        bb = tk.Frame(bar, bg=CARD)
        bb.pack(fill="x", padx=16, pady=12)
        tk.Label(bb, text="❖", bg=CARD, fg=ACC, font=F(13, True)).pack(side="left", padx=(0, 10))
        tk.Label(bb, text=t("inst.home.bar") % (self.inst_display_name(cur), cur.get("game_dir", "")),
                 bg=CARD, fg=SUB, font=F(9), anchor="w").pack(side="left", fill="x", expand=True)
        Btn(bb, t("inst.manage"), lambda: self.show_page("instances"), kind="outline",
            padx=14, pady=5, size=9).pack(side="right")

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
    def _instance_strip(self, parent):
        """版本页顶部的横向实例卡片条：点卡片切换当前实例。"""
        cur = self.current_inst()
        strip = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        strip.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(strip, bg=CARD)
        inner.pack(fill="x", padx=14, pady=10)
        tk.Label(inner, text=t("inst.current.label"), bg=CARD, fg=DIM, font=F(8, True),
                 anchor="w").pack(side="left", padx=(0, 12))
        for inst in instances.list_instances(self.cfg):
            active = inst["id"] == cur["id"]
            chip = tk.Frame(inner, bg=CARD2 if active else CARD,
                            highlightbackground=ACC if active else LINE, highlightthickness=1,
                            cursor="hand2")
            chip.pack(side="left", padx=(0, 8))
            cnt = instances.version_count(inst.get("game_dir"))
            txt = "%s  ·  %d" % (self.inst_display_name(inst), cnt)
            lab = tk.Label(chip, text=txt, bg=chip["bg"], fg=ACC if active else TXT,
                           font=F(9, active), padx=12, pady=7, anchor="w")
            lab.pack()
            for w in (chip, lab):
                w.bind("<ButtonRelease-1>", lambda e, iid=inst["id"]: self._switch_instance(iid))
        Btn(inner, t("inst.manage"), lambda: self.show_page("instances"), kind="quiet",
            padx=12, pady=5, size=8).pack(side="right")

    def _page_versions(self):
        Btn(self.head_right, t("versions.install"), self.open_install, kind="primary",
            padx=14, pady=6, size=9).pack(side="right")

        self._instance_strip(self.page_host)

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
        cfg = self.cfg
        inst = self.current_inst()
        self.set_status(t("versions.launching") % vid)
        auto = bool(cfg.get("auto_repair", True))

        def work():
            from . import java as jm, mojang

            try:
                # 启动参数全部取「当前实例」，缺失时回退顶层 cfg（兼容旧配置）
                exe = (inst.get("java_path") or cfg.get("java_path") or "").strip()
                if not exe or not os.path.isfile(exe):
                    javas = jm.find_javas() or []
                    try:
                        vj, _root = mojang.resolve_version(self.game_dir, vid)
                        major = mojang.guess_java_major(vj)
                    except Exception:
                        major = 17
                    exe = jm.pick_java(major, all_javas=javas) or (javas[0]["path"] if javas else None)
                if not exe:
                    self.after(0, lambda: messagebox.showerror(t("common.v2badge"), t("versions.nojava")))
                    return

                memory = int(inst.get("memory_mb") or cfg.get("memory_mb") or 4096)
                width = int(inst.get("width") or cfg.get("width") or 854)
                height = int(inst.get("height") or cfg.get("height") or 480)
                extra_jvm = parse_jvm_args(inst.get("jvm_args") or cfg.get("jvm_args") or "")

                # 账户：用当前账户组装 auth；外置账户额外拼 -javaagent 注入参数
                acc = accounts.current(cfg)
                auth = accounts.launch_auth(acc)
                if acc.get("mode") == accounts.MODE_AUTHLIB:
                    try:
                        self.after(0, lambda: self.set_status(t("acc.authlib.inject")))
                        jar = accounts.ensure_authlib_jar(
                            status=lambda s: self.after(0, lambda s=s: self.set_status(s)))
                        agent = accounts.javaagent_arg(acc, jar)
                        if agent:
                            extra_jvm.insert(0, agent)
                    except Exception as e:
                        self.after(0, lambda m=str(e): self.set_status("authlib-injector: " + m))

                # 1) 启动前体检 + 自动补齐
                if auto:
                    self.after(0, lambda: self.set_status(t("launch.checking")))
                    try:
                        info = doctor.inspect(self.game_dir, vid)
                        if not info.get("ok"):
                            desc = doctor.describe_missing(info)
                            self.after(0, lambda d=desc: self.set_status(t("launch.fixing") % d))
                            doctor.repair(
                                self.game_dir, vid,
                                status=lambda s: self.after(0, lambda s=s: self.set_status(s)),
                            )
                            self.after(0, lambda: self.set_status(t("launch.fixed")))
                    except Exception as e:
                        msg = str(e)
                        self.after(0, lambda m=msg: self.set_status(t("launch.repairfail") % m))

                # 2) 组装命令并启动（内存/宽高/额外 JVM/账户均来自当前实例与当前账户）
                cmd, _vj, _root, _missing = mojang.build_command(
                    self.game_dir, vid, exe, auth.get("name") or cfg.get("username") or "Steve",
                    memory, width, height, extra_jvm=extra_jvm, auth=auth)
                lines = []
                proc = mojang.launch(cmd, self.game_dir, on_output=lines.append)
                # 记录最后启动版本到当前实例（供导出导入提示）
                try:
                    inst["last_version"] = vid
                    instances.update(self.cfg, inst["id"], last_version=vid)
                except Exception:
                    pass
                self.after(0, lambda: self.set_status(t("versions.launched") % vid))

                # 3) 等待退出，非正常就分析
                rc = proc.wait()
                fresh_crash = doctor.latest_crash(self.game_dir, max_age=180)
                if rc not in (0, None) or fresh_crash:
                    res = doctor.analyze(self.game_dir, vid, rc, lines)
                    self.after(0, lambda r=res: self._open_crash(r, vid))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda m=msg: messagebox.showerror(t("common.v2badge"), m))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 崩溃诊断
    def _open_crash(self, result, vid):
        sev_color = {"error": DANGER, "warn": WARN, "info": ACC}
        win = tk.Toplevel(self)
        win.title(t("crash.title"))
        win.configure(bg=BG)
        win.geometry("700x660")
        win.minsize(620, 520)
        win.transient(self)

        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=26, pady=(20, 2))
        tk.Label(head, text=t("crash.title"), bg=BG, fg=TXT, font=F(17, True),
                 anchor="w").pack(anchor="w")
        n = len([f for f in result.get("findings") or [] if f["code"] != "summary"])
        tk.Label(head, text=t("crash.sub") % (result.get("exit_code"), n), bg=BG, fg=SUB,
                 font=F(9), anchor="w").pack(anchor="w", pady=(4, 0))

        area = ScrollArea(win, bg=BG)
        area.pack(fill="both", expand=True, padx=18, pady=(10, 4))
        parent = area.inner

        findings = result.get("findings") or []
        if not findings:
            tk.Label(parent, text=t("crash.none"), bg=BG, fg=SUB, font=F(9), anchor="w",
                     wraplength=600, justify="left").pack(anchor="w", pady=(2, 10))

        for f in findings:
            card = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            card.pack(fill="x", pady=(0, 10))
            tk.Frame(card, bg=sev_color.get(f["sev"], ACC), width=4).pack(side="left", fill="y")
            body = tk.Frame(card, bg=CARD)
            body.pack(side="left", fill="both", expand=True, padx=16, pady=13)
            tk.Label(body, text=f["title"], bg=CARD, fg=TXT, font=F(11, True), anchor="w",
                     wraplength=560, justify="left").pack(anchor="w")
            if f.get("detail"):
                tk.Label(body, text=f["detail"], bg=CARD, fg=SUB, font=F(9), anchor="w",
                         wraplength=560, justify="left").pack(anchor="w", pady=(6, 0))
            if f.get("fix"):
                tk.Label(body, text=t("crash.fixlabel"), bg=CARD, fg=DIM, font=F(8, True),
                         anchor="w").pack(anchor="w", pady=(10, 2))
                tk.Label(body, text=f["fix"], bg=CARD, fg="#96f0be", font=F(9), anchor="w",
                         wraplength=560, justify="left").pack(anchor="w")

        tail = result.get("tail") or []
        if tail:
            tk.Label(parent, text=t("crash.tail"), bg=BG, fg=DIM, font=F(8, True),
                     anchor="w").pack(anchor="w", pady=(2, 4))
            box = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            box.pack(fill="x", pady=(0, 10))
            tk.Label(box, text="\n".join(tail), bg=CARD, fg=SUB, font=("Consolas", 8),
                     anchor="w", justify="left", wraplength=600).pack(anchor="w", padx=12, pady=10)

        state = tk.Label(win, text="", bg=BG, fg=ACC, font=F(9), anchor="w")
        state.pack(fill="x", padx=26, pady=(0, 2))

        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=24, pady=(2, 18))

        need_repair = any(f.get("action") == "repair" for f in findings)

        def do_save():
            p = doctor.save_report(self.game_dir, result, vid)
            state.config(text=t("crash.saved") % p if p else "")

        if need_repair:
            rep = Btn(row, t("crash.repair"), kind="primary", padx=16, pady=8, size=9)
            rep.pack(side="left", padx=(0, 8))

            def run_repair(btn=rep):
                btn.disable(t("crash.retrying"))
                state.config(text=t("crash.retrying"), fg=SUB)

                def restore(text, color=ACC):
                    btn.set_kind("primary")
                    btn.config(text=t("crash.repair"))
                    btn.command = run_repair
                    state.config(text=text, fg=color)

                def w():
                    try:
                        doctor.repair(self.game_dir, vid)
                        self.after(0, lambda: restore(t("crash.repaired")))
                    except Exception as e:
                        msg = t("launch.repairfail") % str(e)
                        self.after(0, lambda m=msg: restore(m, DANGER))

                threading.Thread(target=w, daemon=True).start()

            rep.command = run_repair

        Btn(row, t("crash.save"), do_save, kind="ghost", padx=14, pady=8, size=9).pack(side="left", padx=(0, 8))
        Btn(row, t("crash.openlogs"),
            lambda: util.open_path(os.path.join(self.game_dir, "logs")),
            kind="ghost", padx=14, pady=8, size=9).pack(side="left", padx=(0, 8))
        Btn(row, t("crash.close"), win.destroy, kind="quiet", padx=16, pady=8,
            size=9).pack(side="right")

    # ------------------------------------------------------------ 实例管理
    def _page_instances(self):
        Btn(self.head_right, t("inst.import"), self._inst_import, kind="ghost",
            padx=14, pady=6, size=9).pack(side="right")
        Btn(self.head_right, t("inst.new"), self._inst_new_dialog, kind="primary",
            padx=14, pady=6, size=9).pack(side="right", padx=(0, 8))

        # 顶部横向实例选择条
        self.inst_selector_host = tk.Frame(self.page_host, bg=BG)
        self.inst_selector_host.pack(fill="x", pady=(0, 14))
        self._render_inst_selector()

        # 下方全宽详情（与设置页同款 ScrollArea 结构，避免嵌套溢出）
        self.inst_detail_host = tk.Frame(self.page_host, bg=BG)
        self.inst_detail_host.pack(fill="both", expand=True)
        self._render_inst_detail()

    def _select_inst(self, iid):
        self.inst_selected = iid
        self._render_inst_selector()
        self._render_inst_detail()

    def _render_inst_selector(self):
        host = getattr(self, "inst_selector_host", None)
        if host is None:
            return
        for w in host.winfo_children():
            w.destroy()
        insts = instances.list_instances(self.cfg)
        cur = self.current_inst()
        if not self.inst_selected or not instances.get_instance(self.cfg, self.inst_selected):
            self.inst_selected = cur["id"]
        card = tk.Frame(host, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=14, pady=10)
        tk.Label(inner, text=t("inst.current.label"), bg=CARD, fg=DIM, font=F(8, True),
                 anchor="w").pack(side="left", padx=(0, 12))
        if not insts:
            tk.Label(inner, text=t("inst.empty"), bg=CARD, fg=SUB, font=F(9),
                     anchor="w").pack(side="left")
            return
        for inst in insts:
            active = inst["id"] == self.inst_selected
            chip = tk.Frame(inner, bg=CARD2 if active else CARD,
                            highlightbackground=ACC if active else LINE, highlightthickness=1,
                            cursor="hand2")
            chip.pack(side="left", padx=(0, 8))
            cnt = instances.version_count(inst.get("game_dir"))
            lab = tk.Label(chip, text="%s  ·  %d" % (self.inst_display_name(inst), cnt),
                           bg=chip["bg"], fg=ACC if active else TXT, font=F(9, active),
                           padx=12, pady=7, anchor="w")
            lab.pack()
            for w in (chip, lab):
                w.bind("<ButtonRelease-1>", lambda e, iid=inst["id"]: self._select_inst(iid))

    def _render_inst_detail(self):
        host = getattr(self, "inst_detail_host", None)
        if host is None:
            return
        for w in host.winfo_children():
            w.destroy()
        inst = instances.get_instance(self.cfg, self.inst_selected)
        if not inst:
            tk.Label(host, text=t("inst.noselect"), bg=BG, fg=SUB, font=F(10),
                     anchor="w").pack(anchor="w", pady=40)
            return

        cur = self.current_inst()
        is_current = inst["id"] == cur["id"]
        area = ScrollArea(host, bg=BG)
        area.pack(fill="both", expand=True)
        p = area.inner

        def card(title):
            tk.Label(p, text=title, bg=BG, fg=DIM, font=F(8, True), anchor="w").pack(anchor="w", pady=(4, 6))
            c = tk.Frame(p, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            c.pack(fill="x", pady=(0, 14))
            inner = tk.Frame(c, bg=CARD)
            inner.pack(fill="x", padx=16, pady=14)
            return inner

        def entry(parent, var, width=20, expand=False):
            e = tk.Entry(parent, textvariable=var, bg=CARD2, fg=TXT, insertbackground=TXT,
                         relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                         highlightcolor=ACC, font=F(10), width=width)
            e.pack(side="left", ipady=5, fill="x", expand=expand)
            return e

        def flabel(parent, text, width=None):
            # 不固定宽度：中文标签按自然宽度排布，避免被字符宽度裁切
            return tk.Label(parent, text=text, bg=CARD, fg=SUB, font=F(9), anchor="w")

        # ---- 基本信息
        box = card(t("inst.basic"))
        name_var = tk.StringVar(value=inst.get("name") or "")
        icon_var = tk.StringVar(value=inst.get("icon") or "◈")
        dir_var = tk.StringVar(value=inst.get("game_dir") or "")

        r1 = tk.Frame(box, bg=CARD); r1.pack(fill="x", pady=4)
        flabel(r1, t("inst.name")).pack(side="left", padx=(0, 10))
        entry(r1, name_var, 18, expand=True)
        flabel(r1, t("inst.icon"), 8).pack(side="left", padx=(16, 10))
        entry(r1, icon_var, 6)

        r2 = tk.Frame(box, bg=CARD); r2.pack(fill="x", pady=4)
        flabel(r2, t("inst.dir")).pack(side="left", padx=(0, 10))
        entry(r2, dir_var, 22, expand=True)
        Btn(r2, t("inst.browse"), lambda: self._pick_dir(dir_var), kind="ghost",
            padx=10, pady=5, size=9).pack(side="left", padx=(8, 0))
        Btn(r2, t("inst.open"), lambda: util.open_path(dir_var.get()), kind="quiet",
            padx=10, pady=5, size=9).pack(side="left", padx=(6, 0))

        # ---- 启动参数
        box = card(t("inst.launch"))
        java_var = tk.StringVar(value=inst.get("java_path") or "")
        mem_var = tk.StringVar(value=str(inst.get("memory_mb") or 4096))
        w_var = tk.StringVar(value=str(inst.get("width") or 854))
        h_var = tk.StringVar(value=str(inst.get("height") or 480))
        jvm_var = tk.StringVar(value=inst.get("jvm_args") or "")

        r3 = tk.Frame(box, bg=CARD); r3.pack(fill="x", pady=4)
        flabel(r3, t("inst.java")).pack(side="left", padx=(0, 10))
        entry(r3, java_var, 22, expand=True)
        Btn(r3, t("inst.browse"), lambda: self._pick_java(java_var), kind="ghost",
            padx=10, pady=5, size=9).pack(side="left", padx=(8, 0))

        r4 = tk.Frame(box, bg=CARD); r4.pack(fill="x", pady=4)
        flabel(r4, t("inst.memory"), 9).pack(side="left", padx=(0, 8))
        entry(r4, mem_var, 8)
        tk.Label(r4, text="MB", bg=CARD, fg=SUB, font=F(9)).pack(side="left", padx=(6, 20))
        flabel(r4, t("inst.width"), 7).pack(side="left", padx=(0, 8))
        entry(r4, w_var, 8)
        flabel(r4, t("inst.height"), 7).pack(side="left", padx=(20, 8))
        entry(r4, h_var, 8)

        r5 = tk.Frame(box, bg=CARD); r5.pack(fill="x", pady=4)
        flabel(r5, t("inst.jvm"), 9).pack(side="left", padx=(0, 10))
        entry(r5, jvm_var, 22, expand=True)

        r6 = tk.Frame(box, bg=CARD); r6.pack(fill="x", pady=(10, 0))
        Btn(r6, t("inst.save"), lambda: do_save(), kind="primary", padx=18, pady=6, size=9).pack(side="left")

        def do_save():
            try:
                mem = int(mem_var.get())
                ww = int(w_var.get())
                hh = int(h_var.get())
            except Exception:
                messagebox.showerror(t("common.v2badge"), t("inst.wh.bad"))
                return
            if mem < 1024:
                messagebox.showerror(t("common.v2badge"), t("inst.mem.bad"))
                return
            if ww <= 0 or hh <= 0:
                messagebox.showerror(t("common.v2badge"), t("inst.wh.bad"))
                return
            try:
                instances.update(
                    self.cfg, inst["id"], name=name_var.get(), icon=icon_var.get(),
                    game_dir=dir_var.get(), java_path=java_var.get(), memory_mb=mem,
                    width=ww, height=hh, jvm_args=jvm_var.get())
            except Exception as e:
                messagebox.showerror(t("common.v2badge"), str(e))
                return
            self.game_dir = self.current_inst()["game_dir"]
            self.set_status(t("inst.saved"))
            self._render_inst_selector()
            self._render_inst_detail()

        # ---- 存档备份 / 恢复
        box = card(t("inst.backup"))
        opt_var = tk.BooleanVar(value=True)
        cfg_var = tk.BooleanVar(value=False)
        cr = tk.Frame(box, bg=CARD); cr.pack(fill="x", pady=2)
        tk.Checkbutton(cr, text=t("inst.backup.opts"), variable=opt_var, bg=CARD, fg=TXT,
                       selectcolor=CARD2, activebackground=CARD, activeforeground=TXT,
                       font=F(9), bd=0, highlightthickness=0).pack(side="left", padx=(0, 18))
        tk.Checkbutton(cr, text=t("inst.backup.config"), variable=cfg_var, bg=CARD, fg=TXT,
                       selectcolor=CARD2, activebackground=CARD, activeforeground=TXT,
                       font=F(9), bd=0, highlightthickness=0).pack(side="left")
        br = tk.Frame(box, bg=CARD); br.pack(fill="x", pady=(8, 0))
        Btn(br, t("inst.backup.now"), lambda: self._inst_backup(inst, opt_var.get(), cfg_var.get()),
            kind="primary", padx=16, pady=6, size=9).pack(side="left", padx=(0, 8))
        Btn(br, t("inst.restore"), lambda: self._inst_restore(inst), kind="ghost",
            padx=16, pady=6, size=9).pack(side="left", padx=(0, 8))
        Btn(br, t("inst.open"), lambda: util.open_path(instances.backups_dir(inst["game_dir"])),
            kind="quiet", padx=14, pady=6, size=9).pack(side="left")

        backups = instances.list_backups(inst["game_dir"])[:5]
        if backups:
            tk.Label(box, text=t("inst.backup.list"), bg=CARD, fg=DIM, font=F(8, True),
                     anchor="w").pack(anchor="w", pady=(12, 4))
            for zp in backups:
                tk.Label(box, text="·  " + os.path.basename(zp), bg=CARD, fg=SUB, font=F(8),
                         anchor="w").pack(anchor="w")
        else:
            tk.Label(box, text=t("inst.backup.empty"), bg=CARD, fg=DIM, font=F(8),
                     anchor="w").pack(anchor="w", pady=(10, 0))

        # ---- 实例操作
        box = card(t("inst.actions"))
        ar = tk.Frame(box, bg=CARD); ar.pack(fill="x")
        if not is_current:
            Btn(ar, t("inst.switch"), lambda: self._switch_instance(inst["id"]), kind="primary",
                padx=16, pady=6, size=9).pack(side="left", padx=(0, 8))
        Btn(ar, t("inst.duplicate"), lambda: self._inst_duplicate(inst), kind="ghost",
            padx=14, pady=6, size=9).pack(side="left", padx=(0, 8))
        Btn(ar, t("inst.export"), lambda: self._inst_export(inst), kind="ghost",
            padx=14, pady=6, size=9).pack(side="left", padx=(0, 8))
        Btn(ar, t("inst.delete"), lambda: self._inst_delete(inst), kind="danger",
            padx=14, pady=6, size=9).pack(side="left")
        tk.Label(box, text=t("inst.dup.note"), bg=CARD, fg=DIM, font=F(8), anchor="w",
                 wraplength=620, justify="left").pack(anchor="w", pady=(10, 0))
        if inst.get("builtin"):
            tk.Label(box, text=t("inst.delete.default"), bg=CARD, fg=WARN, font=F(8),
                     anchor="w", wraplength=620, justify="left").pack(anchor="w", pady=(8, 0))

    # ---- 实例动作
    def _pick_dir(self, var):
        p = filedialog.askdirectory(title=t("inst.dir"))
        if p:
            var.set(p)

    def _pick_java(self, var):
        p = filedialog.askopenfilename(title=t("inst.java.browse"),
                                      filetypes=[("javaw.exe", "*.exe"), ("所有文件", "*.*")])
        if p:
            var.set(p)

    def _switch_instance(self, iid):
        try:
            inst = instances.switch(self.cfg, iid)
        except Exception as e:
            messagebox.showerror(t("common.v2badge"), str(e))
            return
        self.game_dir = inst["game_dir"]
        self.inst_selected = iid
        self.set_status(t("inst.switch.done") % self.inst_display_name(inst))
        if self.page in ("versions", "home", "instances", "settings"):
            self.show_page(self.page)

    def _inst_new_dialog(self):
        win = tk.Toplevel(self)
        win.title(t("inst.new.title"))
        win.configure(bg=BG)
        win.geometry("580x300")
        win.transient(self)
        win.resizable(False, False)

        tk.Label(win, text=t("inst.new.title"), bg=BG, fg=TXT, font=F(16, True),
                 anchor="w").pack(fill="x", padx=24, pady=(22, 4))
        tk.Label(win, text=t("inst.new.dirhint"), bg=BG, fg=SUB, font=F(9),
                 anchor="w", wraplength=520, justify="left").pack(fill="x", padx=24)

        body = tk.Frame(win, bg=BG)
        body.pack(fill="x", padx=24, pady=(18, 0))
        body.columnconfigure(1, weight=1)
        name_var = tk.StringVar(value="")
        dir_var = tk.StringVar(value="")
        icon_var = tk.StringVar(value="◈")

        def grid_row(r, label, var, width=24, browse=None):
            tk.Label(body, text=label, bg=BG, fg=SUB, font=F(9), anchor="w").grid(
                row=r, column=0, sticky="w", pady=7, padx=(0, 10))
            e = tk.Entry(body, textvariable=var, bg=CARD2, fg=TXT, insertbackground=TXT, relief="flat",
                         bd=0, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC,
                         font=F(10), width=width)
            e.grid(row=r, column=1, sticky="ew", pady=7, padx=(4, 0), ipady=4)
            if browse:
                Btn(body, t("inst.browse"), browse, kind="ghost", padx=12, pady=5, size=9).grid(
                    row=r, column=2, sticky="w", padx=(8, 0))
            return e

        name_entry = grid_row(0, t("inst.new.name"), name_var, 26)
        grid_row(1, t("inst.icon"), icon_var, 6)
        grid_row(2, t("inst.new.dir"), dir_var, 26, lambda: self._pick_dir(dir_var))

        state = tk.Label(win, text="", bg=BG, fg=DANGER, font=F(9), anchor="w")
        state.pack(fill="x", padx=24, pady=(10, 0))

        def create():
            name = name_var.get().strip()
            if not name:
                state.config(text=t("inst.new.name"))
                return
            try:
                inst = instances.create(self.cfg, name, game_dir=dir_var.get().strip(),
                                        icon=icon_var.get().strip() or "◈")
            except Exception as e:
                state.config(text=str(e))
                return
            self.inst_selected = inst["id"]
            self.game_dir = inst["game_dir"]
            win.destroy()
            self.show_page("instances")
            self.set_status(t("inst.switch.done") % self.inst_display_name(inst))

        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x", padx=24, pady=(16, 20))
        Btn(foot, t("common.close"), win.destroy, kind="quiet", padx=16, pady=7, size=9).pack(side="right")
        Btn(foot, t("inst.new"), create, kind="primary", padx=18, pady=7, size=10).pack(side="right", padx=(0, 8))
        name_entry.focus_set()
        win.update_idletasks()
        win.geometry("580x%d" % win.winfo_reqheight())

    def _inst_rename_dialog(self, inst):
        win = tk.Toplevel(self)
        win.title(t("inst.rename.title"))
        win.configure(bg=BG)
        win.geometry("420x180")
        win.transient(self)
        win.resizable(False, False)
        tk.Label(win, text=t("inst.rename.title"), bg=BG, fg=TXT, font=F(14, True),
                 anchor="w").pack(fill="x", padx=22, pady=(20, 10))
        var = tk.StringVar(value=inst.get("name") or "")
        e = tk.Entry(win, textvariable=var, bg=CARD2, fg=TXT, insertbackground=TXT, relief="flat",
                      bd=0, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC, font=F(10))
        e.pack(fill="x", padx=22, ipady=6)
        e.focus_set()

        def ok():
            try:
                instances.rename(self.cfg, inst["id"], var.get())
            except Exception as ex:
                messagebox.showerror(t("common.v2badge"), str(ex))
                return
            win.destroy()
            self._render_inst_selector()
            self._render_inst_detail()

        foot = tk.Frame(win, bg=BG)
        foot.pack(fill="x", padx=22, pady=16)
        Btn(foot, t("common.close"), win.destroy, kind="quiet", padx=14, pady=6, size=9).pack(side="right")
        Btn(foot, t("common.save"), ok, kind="primary", padx=16, pady=6, size=9).pack(side="right", padx=(0, 8))
        win.bind("<Return>", lambda ev: ok())

    def _inst_delete(self, inst):
        if inst.get("builtin") or inst["id"] == instances.DEFAULT_ID:
            messagebox.showinfo(t("common.v2badge"), t("inst.delete.default"))
            return
        ok = messagebox.askyesno(
            t("inst.delete"),
            t("inst.delete.confirm") % (self.inst_display_name(inst), inst.get("game_dir", "")))
        if not ok:
            return
        try:
            removed = instances.delete(self.cfg, inst["id"])
        except Exception as e:
            messagebox.showerror(t("common.v2badge"), str(e))
            return
        self.game_dir = self.current_inst()["game_dir"]
        self.inst_selected = self.current_inst()["id"]
        self.set_status(t("inst.delete.done") + "：" + removed)
        self.show_page("instances")

    def _inst_duplicate(self, inst):
        try:
            new = instances.duplicate(self.cfg, inst["id"])
        except Exception as e:
            messagebox.showerror(t("common.v2badge"), str(e))
            return
        self.inst_selected = new["id"]
        self.game_dir = new["game_dir"]
        self.show_page("instances")
        messagebox.showinfo(t("common.v2badge"), t("inst.duplicate.done") % self.inst_display_name(new))

    def _inst_export(self, inst):
        default_name = (inst.get("name") or "instance") + "-instance.json"
        p = filedialog.asksaveasfilename(title=t("inst.export.pick"), defaultextension=".json",
                                         initialfile=default_name,
                                         filetypes=[("JSON", "*.json")])
        if not p:
            return
        try:
            instances.export_instance(self.cfg, inst["id"], p)
        except Exception as e:
            messagebox.showerror(t("common.v2badge"), str(e))
            return
        messagebox.showinfo(t("common.v2badge"), t("inst.export.done") % p)

    def _inst_import(self):
        p = filedialog.askopenfilename(title=t("inst.import.pick"),
                                       filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if not p:
            return
        try:
            inst, missing = instances.import_instance(self.cfg, p)
        except Exception as e:
            messagebox.showerror(t("common.v2badge"), t("inst.import.bad") + "\n" + str(e))
            return
        self.inst_selected = inst["id"]
        self.game_dir = inst["game_dir"]
        if missing:
            go = messagebox.askyesno(t("inst.import.missing.title"),
                                     t("inst.import.missing") % missing)
            self.show_page("instances")
            if go:
                self.open_install()
        else:
            self.show_page("instances")
            messagebox.showinfo(t("common.v2badge"), t("inst.import.done") % self.inst_display_name(inst))

    def _inst_backup(self, inst, include_options, include_config):
        self.set_status(t("inst.backup.now") + "…")

        def work():
            try:
                zp, n = instances.backup_saves(inst["game_dir"],
                                               include_options=include_options,
                                               include_config=include_config)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(t("common.v2badge"), str(e)))
                self.after(0, lambda: self.set_status(""))
                return
            self.after(0, lambda: messagebox.showinfo(t("common.v2badge"),
                                                      t("inst.backup.done") % zp))
            self.after(0, self._render_inst_detail)
            self.after(0, lambda: self.set_status(""))

        threading.Thread(target=work, daemon=True).start()

    def _inst_restore(self, inst):
        initial = instances.backups_dir(inst["game_dir"])
        try:
            os.makedirs(initial, exist_ok=True)
        except Exception:
            pass
        p = filedialog.askopenfilename(title=t("inst.restore.pick"), initialdir=initial,
                                       filetypes=[("ZIP", "*.zip"), ("所有文件", "*.*")])
        if not p:
            return
        if not messagebox.askyesno(t("inst.restore"), t("inst.restore.confirm")):
            return

        def work():
            try:
                res = instances.restore_saves(inst["game_dir"], p)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(t("common.v2badge"), str(e)))
                return
            pre = res.get("pre_backup") or "—"
            self.after(0, lambda: messagebox.showinfo(
                t("common.v2badge"), t("inst.restore.done") % (res["extracted"], pre)))
            self.after(0, self._render_inst_detail)

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 账户
    def _page_accounts(self):
        area = ScrollArea(self.page_host, bg=BG)
        area.pack(fill="both", expand=True)
        self._acc_area = area
        p = area.inner
        cur = accounts.current(self.cfg)

        def card(title):
            tk.Label(p, text=title, bg=BG, fg=DIM, font=F(8, True), anchor="w").pack(
                anchor="w", pady=(4, 6))
            c = tk.Frame(p, bg=CARD, highlightbackground=LINE, highlightthickness=1)
            c.pack(fill="x", pady=(0, 14))
            inner = tk.Frame(c, bg=CARD)
            inner.pack(fill="x", padx=16, pady=14)
            return inner

        def entry(parent, var, width=24, show=None):
            e = tk.Entry(parent, textvariable=var, bg=CARD2, fg=TXT, insertbackground=TXT,
                         relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                         highlightcolor=ACC, font=F(10), width=width, show=show or "")
            e.pack(side="left", ipady=5, fill="x", expand=True)
            return e

        def mode_text(mode):
            return t("acc.mode." + mode) if mode in ("offline", "authlib", "msa") else mode

        def mode_glyph(mode):
            return {"offline": "☺", "authlib": "◉", "msa": "⊞"}.get(mode, "☺")

        # ---- 当前账户
        box = card(t("acc.current.label"))
        top = tk.Frame(box, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=mode_glyph(cur.get("mode")), bg=CARD2, fg=ACC, font=F(16, True),
                 width=3, pady=8).pack(side="left", padx=(0, 12))
        info = tk.Frame(top, bg=CARD)
        info.pack(side="left", fill="x", expand=True)
        line1 = tk.Frame(info, bg=CARD)
        line1.pack(fill="x")
        tk.Label(line1, text=cur.get("name") or "?", bg=CARD, fg=TXT, font=F(13, True),
                 anchor="w").pack(side="left")
        tk.Label(line1, text=mode_text(cur.get("mode")), bg=CARD2, fg=ACC, font=F(8, True),
                 padx=8, pady=2).pack(side="left", padx=(10, 0))
        sub = cur.get("uuid") or ""
        if cur.get("mode") == "authlib" and cur.get("api"):
            sub = "%s   ·   %s" % (cur.get("api"), cur.get("uuid") or "")
        tk.Label(info, text=sub, bg=CARD, fg=SUB, font=F(8), anchor="w").pack(anchor="w", pady=(4, 0))

        # ---- 账户列表
        box = card(t("acc.list.title"))
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", pady=(0, 8))
        Btn(head, t("acc.offline.add"), self._acc_add_dialog, kind="primary",
            padx=14, pady=5, size=9).pack(side="right")
        accs = accounts.list_accounts(self.cfg)
        if not accs:
            tk.Label(box, text=t("acc.empty"), bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w")
        for acc in accs:
            row = tk.Frame(box, bg=CARD2, highlightbackground=LINE, highlightthickness=1)
            row.pack(fill="x", pady=(0, 8))
            rb = tk.Frame(row, bg=CARD2)
            rb.pack(fill="x", padx=12, pady=9)
            tk.Label(rb, text=mode_glyph(acc.get("mode")), bg=CARD2, fg=ACC, font=F(12),
                     width=2).pack(side="left")
            mid = tk.Frame(rb, bg=CARD2)
            mid.pack(side="left", fill="x", expand=True)
            l1 = tk.Frame(mid, bg=CARD2)
            l1.pack(fill="x")
            tk.Label(l1, text=acc.get("name") or "?", bg=CARD2, fg=TXT, font=F(10, True),
                     anchor="w").pack(side="left")
            tk.Label(l1, text=mode_text(acc.get("mode")), bg=CARD2, fg=SUB, font=F(8),
                     padx=6).pack(side="left", padx=(8, 0))
            if acc["id"] == cur["id"]:
                tk.Label(l1, text="● " + t("acc.current.label"), bg=CARD2, fg=ACC, font=F(8, True),
                         padx=6).pack(side="left")
            if acc.get("api"):
                tk.Label(mid, text=acc.get("api"), bg=CARD2, fg=DIM, font=F(8), anchor="w").pack(
                    anchor="w", pady=(2, 0))
            if acc["id"] != cur["id"]:
                Btn(rb, t("acc.set_current"), lambda a=acc["id"]: self._acc_set_current(a),
                    kind="ghost", padx=12, pady=5, size=8).pack(side="right", padx=(6, 0))
            if acc.get("mode") == "offline":
                Btn(rb, t("acc.rename"), lambda a=acc: self._acc_rename_dialog(a),
                    kind="quiet", padx=10, pady=5, size=8).pack(side="right", padx=(6, 0))
            Btn(rb, t("acc.delete"), lambda a=acc: self._acc_delete(a),
                kind="danger", padx=10, pady=5, size=8).pack(side="right")

        # ---- 外置登录
        box = card(t("acc.online.title"))
        api_var = tk.StringVar(value=self.cfg.get("authlib_api") or "https://littleskin.cn/api/yggdrasil")
        r1 = tk.Frame(box, bg=CARD); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("acc.authlib.api"), bg=CARD, fg=SUB, font=F(9), width=12, anchor="w").pack(side="left")
        entry(r1, api_var, 30)
        test_btn = Btn(r1, t("acc.test"), lambda: None, kind="ghost", padx=12, pady=5, size=9)
        test_btn.pack(side="left", padx=(8, 0))
        test_state = tk.Label(box, text="", bg=CARD, fg=SUB, font=F(8), anchor="w", wraplength=640, justify="left")
        test_state.pack(anchor="w", pady=(2, 4))

        user_var = tk.StringVar(value="")
        pass_var = tk.StringVar(value="")
        r2 = tk.Frame(box, bg=CARD); r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("acc.authlib.user"), bg=CARD, fg=SUB, font=F(9), width=12, anchor="w").pack(side="left")
        entry(r2, user_var, 24)
        r3 = tk.Frame(box, bg=CARD); r3.pack(fill="x", pady=4)
        tk.Label(r3, text=t("acc.authlib.pass"), bg=CARD, fg=SUB, font=F(9), width=12, anchor="w").pack(side="left")
        entry(r3, pass_var, 24, show="*")
        r4 = tk.Frame(box, bg=CARD); r4.pack(fill="x", pady=(8, 0))
        login_btn = Btn(r4, t("acc.login"), lambda: None, kind="primary", padx=18, pady=6, size=9)
        login_btn.pack(side="left")
        tk.Label(box, text=t("acc.authlib.note"), bg=CARD, fg=DIM, font=F(8), anchor="w",
                 wraplength=660, justify="left").pack(anchor="w", pady=(10, 0))
        tk.Label(box, text=t("acc.authlib.inject"), bg=CARD, fg=DIM, font=F(8), anchor="w",
                 wraplength=660, justify="left").pack(anchor="w", pady=(4, 0))

        def do_test():
            test_btn.disable(t("acc.testing"))
            test_state.config(text=t("acc.testing"), fg=SUB)

            def work():
                try:
                    name = accounts.test_api(api_var.get())
                    msg = t("acc.test.ok") % name
                    color = ACC
                except Exception as e:
                    msg = t("acc.test.fail") % str(e)
                    color = DANGER

                def done():
                    try:
                        test_state.config(text=msg, fg=color)
                        test_btn.set_kind("ghost")
                        test_btn.config(text=t("acc.test"))
                        test_btn.command = do_test
                    except Exception:
                        pass
                self.after(0, done)

            threading.Thread(target=work, daemon=True).start()

        test_btn.command = do_test

        def do_login():
            api = api_var.get().strip()
            user = user_var.get().strip()
            pwd = pass_var.get()
            if not api or not user or not pwd:
                test_state.config(text=t("acc.authlib.user") + " / " + t("acc.authlib.pass"), fg=WARN)
                return
            login_btn.disable(t("acc.logging"))
            test_state.config(text=t("acc.logging"), fg=SUB)

            def work():
                try:
                    acc = accounts.login_authlib(self.cfg, api, user, pwd,
                                                 status=lambda s: self.after(0, lambda: self.set_status(s)))
                    msg = t("acc.authlib.success") % (acc.get("name"), acc.get("api"))
                    self.after(0, lambda: self.set_status(msg))
                    self.after(0, lambda: self.show_page("accounts"))
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: self._acc_login_fail(login_btn, err, test_state))

            threading.Thread(target=work, daemon=True).start()

        login_btn.command = do_login
        login_btn._do_login = do_login

        # ---- 微软正版
        box = card(t("acc.msa.title"))
        msa_var = tk.StringVar(value=self.cfg.get("msa_client_id") or "")
        r = tk.Frame(box, bg=CARD); r.pack(fill="x", pady=4)
        tk.Label(r, text=t("acc.msa.clientid"), bg=CARD, fg=SUB, font=F(9), width=14, anchor="w").pack(side="left")
        entry(r, msa_var, 34)
        Btn(r, t("acc.msa.save"), lambda: self._acc_msa_save(msa_var), kind="ghost",
            padx=12, pady=5, size=9).pack(side="left", padx=(8, 0))

        cid = (self.cfg.get("msa_client_id") or "").strip()
        if not cid:
            tk.Label(box, text=t("acc.msa.disabled"), bg=CARD, fg=WARN, font=F(8), anchor="w",
                     wraplength=660, justify="left").pack(anchor="w", pady=(8, 0))
        tk.Label(box, text=t("acc.msa.howto"), bg=CARD, fg=SUB, font=F(8), anchor="w",
                 wraplength=660, justify="left").pack(anchor="w", pady=(8, 0))
        Btn(box, t("acc.msa.howto.link"), self._acc_open_docs, kind="quiet",
            padx=12, pady=5, size=8).pack(anchor="w", pady=(6, 0))

        code_state = tk.Label(box, text="", bg=CARD2, fg=ACC, font=F(9, True), anchor="w",
                              wraplength=660, justify="left", padx=12, pady=10)
        code_state.pack(fill="x", pady=(10, 0))
        code_row = tk.Frame(box, bg=CARD)
        code_row.pack(fill="x", pady=(8, 0))
        copy_btn = Btn(code_row, t("acc.msa.copy"), lambda: None, kind="ghost",
                       padx=12, pady=5, size=9)
        copy_btn.pack(side="left")
        copy_btn.disable(t("acc.msa.copy"))
        self._msa_code = ""

        msa_btn = Btn(code_row, t("acc.msa.login"), lambda: None, kind="primary",
                     padx=18, pady=6, size=9)
        msa_btn.pack(side="left", padx=(8, 0))
        if not cid:
            msa_btn.disable(t("acc.msa.login"))

        def do_msa():
            cid_now = msa_var.get().strip()
            if not cid_now:
                code_state.config(text=t("acc.msa.needid"), fg=WARN)
                return
            self.cfg["msa_client_id"] = cid_now
            util.save_config(self.cfg)
            msa_btn.disable(t("acc.msa.logging"))
            code_state.config(text=t("acc.msa.logging"), fg=SUB)
            self._msa_code = ""

            def on_code(code, uri):
                self._msa_code = code or ""
                msg = t("acc.msa.code") % (uri or "https://www.microsoft.com/link", code or "")

                def show():
                    try:
                        code_state.config(text=msg, fg=ACC)
                        copy_btn.set_kind("ghost")
                        copy_btn.config(text=t("acc.msa.copy"))
                        copy_btn.command = lambda: self._copy_msa_code()
                    except Exception:
                        pass
                self.after(0, show)

            def work():
                try:
                    acc = accounts.login_msa(self.cfg, cid_now, status=lambda s: self.after(0, lambda: self.set_status(s)),
                                             on_code=on_code)
                    self.after(0, lambda: self.set_status(t("acc.authlib.success") % (acc.get("name"), "Microsoft")))
                    self.after(0, lambda: self.show_page("accounts"))
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: self._acc_msa_fail(msa_btn, code_state, err))

            threading.Thread(target=work, daemon=True).start()

        msa_btn.command = do_msa
        msa_btn._do_msa = do_msa

    def _copy_msa_code(self):
        if self._msa_code:
            self.clipboard_clear()
            self.clipboard_append(self._msa_code)
            self.set_status(t("acc.msa.copied"))

    def _acc_login_fail(self, btn, err, state):
        try:
            btn.set_kind("primary")
            btn.config(text=t("acc.login"))
            btn.command = getattr(btn, "_do_login", None)
        except Exception:
            pass
        try:
            state.config(text=t("acc.msa.failed") % err, fg=DANGER)
        except Exception:
            pass
        messagebox.showerror(t("common.v2badge"), err)

    def _acc_msa_fail(self, btn, state, err):
        try:
            btn.set_kind("primary")
            btn.config(text=t("acc.msa.login"))
            btn.command = getattr(btn, "_do_msa", None)
        except Exception:
            pass
        try:
            state.config(text=t("acc.msa.failed") % err, fg=DANGER)
        except Exception:
            pass
        messagebox.showerror(t("common.v2badge"), err)

    def _acc_open_docs(self):
        util.open_path("https://learn.microsoft.com/entra/identity-platform/v2-oauth2-device-code")

    def _acc_msa_save(self, var):
        cid = var.get().strip()
        self.cfg["msa_client_id"] = cid
        util.save_config(self.cfg)
        self.set_status(t("acc.msa.saved"))
        self.show_page("accounts")

    def _acc_set_current(self, aid):
        try:
            acc = accounts.set_current(self.cfg, aid)
        except Exception as e:
            messagebox.showerror(t("common.v2badge"), str(e))
            return
        self.set_status(t("acc.switch.done") % acc.get("name"))
        self.show_page("accounts")

    def _acc_delete(self, acc):
        if not messagebox.askyesno(t("acc.delete"), t("acc.delete.confirm") % acc.get("name")):
            return
        try:
            accounts.delete(self.cfg, acc["id"])
        except Exception as e:
            messagebox.showerror(t("common.v2badge"), str(e))
            return
        self.set_status(t("acc.deleted"))
        self.show_page("accounts")

    def _acc_add_dialog(self):
        win = tk.Toplevel(self)
        win.title(t("acc.offline.title"))
        win.configure(bg=BG)
        win.geometry("460x210")
        win.transient(self)
        win.resizable(False, False)
        tk.Label(win, text=t("acc.offline.title"), bg=BG, fg=TXT, font=F(15, True),
                 anchor="w").pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(win, text=t("acc.offline.name"), bg=BG, fg=SUB, font=F(9),
                 anchor="w").pack(fill="x", padx=24)
        var = tk.StringVar(value="")
        e = tk.Entry(win, textvariable=var, bg=CARD2, fg=TXT, insertbackground=TXT, relief="flat",
                     bd=0, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC, font=F(11))
        e.pack(fill="x", padx=24, ipady=6, pady=(8, 0))
        state = tk.Label(win, text="", bg=BG, fg=DANGER, font=F(9), anchor="w")
        state.pack(fill="x", padx=24, pady=(8, 0))

        def ok():
            name = var.get().strip()
            if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
                state.config(text=t("acc.offline.badname"))
                return
            try:
                acc = accounts.add_offline(self.cfg, name)
            except Exception as ex:
                state.config(text=str(ex))
                return
            win.destroy()
            self.set_status(t("acc.added") % acc.get("name"))
            self.show_page("accounts")

        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x", padx=24, pady=16)
        Btn(foot, t("common.close"), win.destroy, kind="quiet", padx=16, pady=7, size=9).pack(side="right")
        Btn(foot, t("acc.offline.add"), ok, kind="primary", padx=18, pady=7, size=10).pack(side="right", padx=(0, 8))
        e.focus_set()
        win.bind("<Return>", lambda ev: ok())

    def _acc_rename_dialog(self, acc):
        win = tk.Toplevel(self)
        win.title(t("acc.rename.title"))
        win.configure(bg=BG)
        win.geometry("420x190")
        win.transient(self)
        win.resizable(False, False)
        tk.Label(win, text=t("acc.rename.title"), bg=BG, fg=TXT, font=F(14, True),
                 anchor="w").pack(fill="x", padx=22, pady=(20, 10))
        var = tk.StringVar(value=acc.get("name") or "")
        e = tk.Entry(win, textvariable=var, bg=CARD2, fg=TXT, insertbackground=TXT, relief="flat",
                     bd=0, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC, font=F(10))
        e.pack(fill="x", padx=22, ipady=6)
        e.focus_set()

        def ok():
            name = var.get().strip()
            if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
                messagebox.showerror(t("common.v2badge"), t("acc.offline.badname"))
                return
            try:
                accounts.rename_offline(self.cfg, acc["id"], name)
            except Exception as ex:
                messagebox.showerror(t("common.v2badge"), str(ex))
                return
            win.destroy()
            self.set_status(t("acc.renamed"))
            self.show_page("accounts")

        foot = tk.Frame(win, bg=BG)
        foot.pack(fill="x", padx=22, pady=16)
        Btn(foot, t("common.close"), win.destroy, kind="quiet", padx=14, pady=6, size=9).pack(side="right")
        Btn(foot, t("common.save"), ok, kind="primary", padx=16, pady=6, size=9).pack(side="right", padx=(0, 8))
        win.bind("<Return>", lambda ev: ok())

    # ------------------------------------------------------------ 安装新版本
    def open_install(self):
        """安装新版本向导：选游戏版本 + 加载器，带进度条。"""
        from . import mojang

        win = tk.Toplevel(self)
        win.title(t("versions.install.title"))
        win.configure(bg=BG)
        win.geometry("680x660")
        win.minsize(620, 560)
        win.transient(self)

        tk.Label(win, text=t("versions.install.title"), bg=BG, fg=TXT, font=F(16, True),
                 anchor="w").pack(fill="x", padx=24, pady=(22, 4))
        tk.Label(win, text=t("versions.install.sub"), bg=BG, fg=SUB, font=F(9),
                 anchor="w", wraplength=600, justify="left").pack(fill="x", padx=24)

        body = tk.Frame(win, bg=BG)
        body.pack(fill="x", padx=24, pady=(14, 0))
        body.columnconfigure(1, weight=1)

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

        def loader_label(v):
            return {"vanilla": t("versions.install.vanilla"), "fabric": "Fabric",
                    "forge": "Forge", "neoforge": "NeoForge", "quilt": "Quilt"}.get(v, v)

        loader_sel = Select(body, ["vanilla", "fabric", "forge", "neoforge", "quilt"],
                            "vanilla", width=24, labels=loader_label)
        loader_sel.grid(row=1, column=1, sticky="w", padx=(16, 0), pady=6)

        # 加载器专属选项（版本下拉 / 测试版 / 本地 installer），随加载器切换重建
        opts_host = tk.Frame(body, bg=BG)
        opts_host.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        opts = {"ver_var": tk.StringVar(value=""), "local_jar": "",
                "beta": tk.BooleanVar(value=False), "ver_sel": None, "local_label": None}

        def opt_row(parent, label, width=14):
            r = tk.Frame(parent, bg=BG)
            r.pack(fill="x", pady=4)
            tk.Label(r, text=label, bg=BG, fg=SUB, font=F(9), width=width, anchor="w").pack(side="left")
            return r

        def load_loader_versions():
            ld = loader_sel.value
            mc = mc_sel.value
            if ld not in ("forge", "neoforge", "quilt") or not mc or mc == "—":
                return
            ver_sel = opts.get("ver_sel")
            if ver_sel is None:
                return
            ver_sel.set_values([t("versions.install.loadingvers")], t("versions.install.loadingvers"))

            def work():
                vals = []
                err = None
                try:
                    if ld == "forge":
                        vals = forge.list_forge(mc)
                    elif ld == "neoforge":
                        vals = forge.list_neoforge(mc)
                    else:
                        vals = quilt.list_loaders(mc, include_beta=opts["beta"].get())
                except Exception as e:
                    err = str(e)

                def done():
                    try:
                        if err:
                            ver_sel.set_values([], "")
                            opts["ver_var"].set("")
                            return
                        ver_sel.set_values(vals, vals[0] if vals else "")
                        if vals:
                            opts["ver_var"].set(vals[0])
                    except Exception:
                        pass
                self.after(0, done)

            threading.Thread(target=work, daemon=True).start()

        def rebuild_opts():
            for w in opts_host.winfo_children():
                w.destroy()
            opts["ver_sel"] = None
            opts["local_label"] = None
            ld = loader_sel.value

            if ld == "vanilla":
                tk.Label(opts_host, text=t("versions.install.vanilla.hint"), bg=BG, fg=DIM,
                         font=F(8), anchor="w", wraplength=580, justify="left").pack(anchor="w", pady=4)
                return
            if ld == "fabric":
                tk.Label(opts_host, text=t("versions.install.fabric.hint"), bg=BG, fg=DIM,
                         font=F(8), anchor="w", wraplength=580, justify="left").pack(anchor="w", pady=4)
                return

            # forge / neoforge / quilt：版本选择
            r = opt_row(opts_host, t("versions.install.loaderver"))
            ver_entry = tk.Entry(r, textvariable=opts["ver_var"], bg=CARD2, fg=TXT, insertbackground=TXT,
                                 relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                                 highlightcolor=ACC, font=F(10), width=18)
            ver_entry.pack(side="left", ipady=5, padx=(0, 8))
            ver_sel = Select(r, ["…"], "…", width=20,
                             labels=lambda v: v, on_change=lambda v: opts["ver_var"].set(v))
            ver_sel.pack(side="left")
            opts["ver_sel"] = ver_sel
            Btn(r, t("versions.install.refresh"), load_loader_versions, kind="quiet",
                padx=10, pady=5, size=8).pack(side="left", padx=(8, 0))

            if ld == "quilt":
                br = tk.Frame(opts_host, bg=BG)
                br.pack(fill="x", pady=(6, 0))
                tk.Checkbutton(br, text=t("versions.install.beta"), variable=opts["beta"], bg=BG, fg=TXT,
                               selectcolor=CARD2, activebackground=BG, activeforeground=TXT, font=F(9),
                               bd=0, highlightthickness=0,
                               command=load_loader_versions).pack(side="left")
                tk.Label(opts_host, text=t("versions.install.quilt.hint"), bg=BG, fg=DIM, font=F(8),
                         anchor="w", wraplength=580, justify="left").pack(anchor="w", pady=(6, 0))
            else:
                # forge / neoforge：本地 installer 兜底
                lr = opt_row(opts_host, "")
                Btn(lr, t("versions.install.localjar"), lambda: self._pick_local_installer(opts),
                    kind="ghost", padx=12, pady=5, size=8).pack(side="left")
                lab = tk.Label(lr, text="", bg=BG, fg=SUB, font=F(8), anchor="w", wraplength=420, justify="left")
                lab.pack(side="left", padx=(10, 0), fill="x", expand=True)
                opts["local_label"] = lab
                if ld == "neoforge":
                    tk.Label(opts_host, text=t("versions.install.neo.warn"), bg=BG, fg=WARN, font=F(8),
                             anchor="w", wraplength=580, justify="left").pack(anchor="w", pady=(6, 0))
                    tk.Label(opts_host, text=t("versions.install.neo.hint"), bg=BG, fg=DIM, font=F(8),
                             anchor="w", wraplength=580, justify="left").pack(anchor="w", pady=(4, 0))
                else:
                    tk.Label(opts_host, text=t("versions.install.forge.hint"), bg=BG, fg=DIM, font=F(8),
                             anchor="w", wraplength=580, justify="left").pack(anchor="w", pady=(6, 0))

            load_loader_versions()

        def on_mc_change(_v=None):
            rebuild_opts()

        mc_sel.on_change = on_mc_change
        loader_sel.on_change = lambda v: rebuild_opts()
        rebuild_opts()

        bar = ProgressBar(win, height=10)
        bar.pack(fill="x", padx=24, pady=(18, 8))
        state = tk.Label(win, text=t("versions.install.note"), bg=BG, fg=DIM, font=F(9),
                         anchor="w", wraplength=600, justify="left")
        state.pack(fill="x", padx=24)

        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=24, pady=(16, 20))

        busy = {"on": False}

        def refresh_btn():
            busy["on"] = False
            go.set_kind("primary")
            go.config(text=t("versions.install.start"))
            go.command = start

        def mc_required_major(mc):
            m = re.match(r"1\.(\d+)(?:\.(\d+))?", str(mc))
            if not m:
                return 17
            minor, patch = int(m.group(1)), int(m.group(2) or 0)
            if minor <= 16:
                return 8
            if minor == 17:
                return 17
            if minor <= 20:
                return 17 if not (minor == 20 and patch >= 5) else 21
            return 21

        def start():
            if busy["on"]:
                return
            vid = mc_sel.value
            ld = loader_sel.value
            if not vid or vid == "—":
                return
            lv = (opts["ver_var"].get().strip() or None)
            local_jar = opts.get("local_jar") or None
            if ld in ("forge", "neoforge") and not lv and not local_jar:
                state.config(text=t("versions.install.loaderver"), fg=WARN)
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
                    if ld == "fabric":
                        out = mojang.install_fabric(self.game_dir, vid, status=on_status,
                                                    progress=on_progress, manifest=mm)
                    elif ld == "quilt":
                        out = quilt.install_quilt(self.game_dir, vid, loader_version=lv,
                                                  include_beta=opts["beta"].get(),
                                                  status=on_status, progress=on_progress, manifest=mm)
                    elif ld in ("forge", "neoforge"):
                        from . import java as jm
                        javas = jm.find_javas()
                        exe = jm.pick_java(mc_required_major(vid), all_javas=javas)
                        if not exe:
                            raise RuntimeError(t("versions.install.needjava"))
                        out = forge.install_loader(self.game_dir, vid, ld, lv or "", exe,
                                                   status=on_status, progress=on_progress,
                                                   local_jar=local_jar)
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

    def _pick_local_installer(self, opts):
        p = filedialog.askopenfilename(title=t("versions.install.localjar.pick"),
                                      filetypes=[("installer jar", "*.jar"), ("所有文件", "*.*")])
        if p:
            opts["local_jar"] = p
            lab = opts.get("local_label")
            if lab is not None:
                try:
                    lab.config(text=t("versions.install.localjar.set") % os.path.basename(p), fg=ACC)
                except Exception:
                    pass

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

        cur = self.current_inst()
        tk.Label(parent, text=t("inst.settings.note"), bg=BG, fg=SUB, font=F(8),
                 anchor="w", wraplength=880, justify="left").pack(anchor="w", pady=(0, 4))
        tk.Label(parent, text="%s：%s" % (t("inst.current.label"), self.inst_display_name(cur)),
                 bg=BG, fg=ACC, font=F(9, True), anchor="w").pack(anchor="w", pady=(0, 10))

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

        # 外观：主题 + 强调色
        box = section(t("settings.appearance"))
        tk.Label(box, text=t("settings.theme"), bg=CARD, fg=SUB, font=F(8),
                 anchor="w").pack(anchor="w", pady=(0, 6))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        cur_theme = self.cfg.get("theme") or "dark"
        for key in ("dark", "light", "midnight", "system"):
            Btn(row, t("theme." + key), lambda k=key: self.switch_theme(k),
                kind="primary" if key == cur_theme else "ghost",
                padx=14, pady=6, size=9).pack(side="left", padx=(0, 8))

        tk.Label(box, text=t("settings.accent"), bg=CARD, fg=SUB, font=F(8),
                 anchor="w").pack(anchor="w", pady=(14, 6))
        arow = tk.Frame(box, bg=CARD)
        arow.pack(fill="x")
        cur_accent = self.cfg.get("accent") or "green"
        for key, cols in theme.ACCENTS.items():
            chip = tk.Label(arow, text="   ", bg=cols[0], width=4, pady=7, cursor="hand2",
                            highlightthickness=2,
                            highlightbackground=(TXT if key == cur_accent else cols[0]))
            chip.pack(side="left", padx=(0, 10))
            chip.bind("<ButtonRelease-1>", lambda e, k=key: self.switch_accent(k))

        # 内存（作用于当前实例）
        box = section(t("settings.memory"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        self.mem_var = tk.StringVar(value=str(cur.get("memory_mb") or 4096))
        e = tk.Entry(row, textvariable=self.mem_var, bg=CARD2, fg=TXT, insertbackground=TXT,
                     relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                     highlightcolor=ACC, font=F(10), width=10)
        e.pack(side="left", ipady=5, padx=(0, 10))
        tk.Label(row, text="MB", bg=CARD, fg=SUB, font=F(9)).pack(side="left", padx=(0, 14))
        Btn(row, t("common.save"), self._save_memory, kind="ghost", padx=14, pady=5, size=9).pack(side="left")

        # Java（作用于当前实例）
        box = section(t("settings.java"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        self.java_var = tk.StringVar(value=cur.get("java_path") or "")
        e = tk.Entry(row, textvariable=self.java_var, bg=CARD2, fg=TXT, insertbackground=TXT,
                     relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
                     highlightcolor=ACC, font=F(9), width=52)
        e.pack(side="left", ipady=5, padx=(0, 10))
        Btn(row, t("common.browse"), self._pick_java, kind="ghost", padx=12, pady=5, size=9).pack(side="left", padx=(0, 8))
        Btn(row, t("common.save"), self._save_java, kind="ghost", padx=12, pady=5, size=9).pack(side="left")
        detected = jm.find_javas() if False else None  # 避免启动时全盘扫描
        tk.Label(box, text=t("settings.autodetect"), bg=CARD, fg=SUB, font=F(8), anchor="w").pack(anchor="w", pady=(8, 0))

        # 启动与诊断
        box = section(t("settings.diag"))
        st = {"on": bool(self.cfg.get("auto_repair", True))}
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text=t("settings.autorepair"), bg=CARD, fg=TXT, font=F(10),
                 anchor="w").pack(side="left")
        tog = Btn(row, t("settings.on") if st["on"] else t("settings.off"),
                  kind="primary" if st["on"] else "ghost", padx=16, pady=5, size=9)
        tog.pack(side="right")

        def flip():
            st["on"] = not st["on"]
            self.cfg["auto_repair"] = st["on"]
            util.save_config(self.cfg)
            tog.set_kind("primary" if st["on"] else "ghost")
            tog.config(text=t("settings.on") if st["on"] else t("settings.off"))

        tog.command = flip

        tk.Label(box, text=t("settings.autorepair.desc"), bg=CARD, fg=SUB, font=F(8), anchor="w",
                 wraplength=680, justify="left").pack(anchor="w", pady=(8, 0))
        tk.Label(box, text=t("settings.crashdesc"), bg=CARD, fg=SUB, font=F(8), anchor="w",
                 wraplength=680, justify="left").pack(anchor="w", pady=(4, 0))
        Btn(box, t("crash.openlogs"),
            lambda: util.open_path(os.path.join(self.game_dir, "logs")),
            kind="quiet", padx=14, pady=5, size=9).pack(anchor="w", pady=(10, 0))

        # 目录
        box = section(t("settings.datadir"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text=self.game_dir, bg=CARD2, fg=TXT, font=F(9), padx=12, pady=7, anchor="w").pack(side="left", fill="x", expand=True)
        Btn(row, t("settings.open"), lambda: util.open_path(self.game_dir), kind="ghost",
            padx=12, pady=5, size=9).pack(side="left", padx=(10, 0))

        # 关于
        box = section(t("settings.about"))
        tk.Label(box, text="MC Lite 正式版 v1.4.0  ·  MIT  ·  Python + tkinter", bg=CARD, fg=TXT,
                 font=F(10, True), anchor="w").pack(anchor="w")
        tk.Label(box, text=t("settings.about.text"), bg=CARD, fg=SUB, font=F(9), anchor="w").pack(anchor="w", pady=(4, 0))

    def _save_memory(self):
        try:
            mb = max(1024, int(self.mem_var.get()))
        except Exception:
            self.set_status(t("common.badinput"))
            return
        try:
            instances.update(self.cfg, self.current_inst()["id"], memory_mb=mb)
        except Exception as e:
            self.set_status(str(e))
            return
        self.game_dir = self.current_inst()["game_dir"]
        self.set_status(t("common.saved"))

    def _pick_java(self):
        p = filedialog.askopenfilename(title=t("settings.pickjava"), filetypes=[("javaw.exe", "*.exe")])
        if p:
            self.java_var.set(p)

    def _save_java(self):
        try:
            instances.update(self.cfg, self.current_inst()["id"],
                              java_path=self.java_var.get().strip())
        except Exception as e:
            self.set_status(str(e))
            return
        self.set_status(t("common.saved"))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()









