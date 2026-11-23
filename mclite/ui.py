# -*- coding: utf-8 -*-
"""界面：tkinter 深色主题启动器"""
import os
import queue
import threading
import time
import tkinter as tk
import urllib.parse
import webbrowser
from tkinter import ttk, filedialog, messagebox

from . import util, mojang, java as javamod, modrinth, bedrock, tunnel, forge, auth

BG = "#0f1115"
SIDEBAR = "#121419"
CARD = "#171a20"
CARD2 = "#212630"
LINE = "#2c323d"
TXT = "#e9edf4"
SUB = "#8b93a3"
ACC = "#3ddc84"
ACC_DARK = "#2fb56e"

FONT = ("Microsoft YaHei UI", 10)
FONT_S = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 10, "bold")
FONT_H = ("Microsoft YaHei UI", 12, "bold")
FONT_T = ("Microsoft YaHei UI", 19, "bold")
MONO = ("Consolas", 9)

NAV = [
    ("home", "启动游戏"),
    ("jversions", "Java 版版本"),
    ("bversions", "基岩版版本"),
    ("mods", "模组下载"),
    ("shaders", "光影下载"),
    ("packs", "资源包"),
    ("online", "联机"),
    ("account", "账号"),
    ("settings", "设置"),
]


# --------------------------------------------------------------------------- #
# 小控件封装
# --------------------------------------------------------------------------- #
def label(parent, text="", color=TXT, font=FONT, bg=None, **kw):
    return tk.Label(parent, text=text, fg=color, bg=bg or CARD, font=font, anchor="w", justify="left", **kw)


def button(parent, text, cmd, kind="primary", **kw):
    if kind == "primary":
        kw.setdefault("bg", ACC)
        kw.setdefault("fg", "#08150d")
        kw.setdefault("activebackground", ACC_DARK)
        kw.setdefault("activeforeground", "#08150d")
        font = FONT_B
    elif kind == "ghost":
        kw.setdefault("bg", CARD2)
        kw.setdefault("fg", TXT)
        kw.setdefault("activebackground", LINE)
        kw.setdefault("activeforeground", TXT)
        font = FONT
    else:  # link
        kw.setdefault("bg", CARD)
        kw.setdefault("fg", ACC)
        kw.setdefault("activebackground", CARD)
        kw.setdefault("activeforeground", ACC_DARK)
        font = FONT
    return tk.Button(
        parent, text=text, command=cmd, relief="flat", bd=0, padx=14, pady=7,
        font=kw.pop("font", font), cursor="hand2", highlightthickness=0, **kw
    )


def entry(parent, var=None, width=24, bg=CARD2):
    return tk.Entry(
        parent, textvariable=var, width=width, bg=bg, fg=TXT, insertbackground=TXT,
        relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE,
        highlightcolor=ACC, font=FONT, disabledbackground=CARD2, disabledforeground=SUB,
    )


def card(parent, bg=CARD):
    return tk.Frame(parent, bg=bg, highlightbackground=LINE, highlightthickness=1)


def scrollable_tree(parent, columns, widths, height=14):
    frame = tk.Frame(parent, bg=CARD)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height, style="Dark.Treeview")
    for c, w in zip(columns, widths):
        tree.heading(c, text=c)
        tree.column(c, width=w, anchor="w", stretch=(c == columns[-1]))
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Dark.Vertical.TScrollbar")
    tree.configure(yscrollcommand=vsb.set)
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    return frame, tree


# --------------------------------------------------------------------------- #
# 主应用
# --------------------------------------------------------------------------- #
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = util.load_config()
        self.q = queue.Queue()
        self.pages = {}
        self.nav = {}
        self._canvases = {}
        self.manifest = None
        self.java_list = []
        self.proc = None
        self.content = {}
        self.clients = []
        self.tunnel_proc = None
        self.lan_port = None
        self.tunnel_address = ""
        self.account = {"mode": "offline", "name": self.cfg.get("username", "Steve")}
        self.current_page = None

        self.title("MC Lite 启动器")
        self.geometry("1080x740")
        self.minsize(960, 660)
        self.configure(bg=BG)

        self._setup_style()
        self._build_layout()
        self._build_pages()

        self.after(60, self._tick)
        self.after(250, self._boot)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_page("home")

    # -- 基础样式 -----------------------------------------------------------
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "TCombobox", fieldbackground=CARD2, background=CARD2, foreground=TXT, arrowcolor=TXT,
            bordercolor=LINE, lightcolor=CARD2, darkcolor=CARD2, insertcolor=TXT, padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", CARD2)],
            foreground=[("readonly", TXT)],
            bordercolor=[("focus", ACC)],
        )
        style.configure("TSpinbox", fieldbackground=CARD2, background=CARD2, foreground=TXT,
                        arrowcolor=TXT, bordercolor=LINE, lightcolor=CARD2, darkcolor=CARD2, padding=3)
        style.configure("Dark.Treeview", background=CARD, fieldbackground=CARD, foreground=TXT,
                        rowheight=27, borderwidth=0, font=FONT_S)
        style.configure("Dark.Treeview.Heading", background=CARD2, foreground=SUB, font=FONT_B,
                        relief="flat", borderwidth=0)
        style.map("Dark.Treeview", background=[("selected", "#2b4f3c")],
                  foreground=[("selected", TXT)])
        style.configure("Dark.Vertical.TScrollbar", background=CARD2, troughcolor=CARD,
                        arrowcolor=SUB, bordercolor=CARD, lightcolor=CARD2, darkcolor=CARD2)
        style.configure("Green.Horizontal.TProgressbar", troughcolor=CARD2, background=ACC,
                        bordercolor=CARD2, borderwidth=0, thickness=8, lightcolor=ACC, darkcolor=ACC)
        style.configure("TCheckbutton", background=CARD, foreground=TXT, font=FONT_S)

    # -- 布局 ---------------------------------------------------------------
    def _build_layout(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        header = tk.Frame(self, bg=SIDEBAR, height=68)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.pack_propagate(False)
        left = tk.Frame(header, bg=SIDEBAR)
        left.pack(side="left", padx=22)
        tk.Label(left, text="MC LITE", bg=SIDEBAR, fg=ACC, font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        tk.Label(left, text="  Minecraft 启动器 · Java & 基岩版", bg=SIDEBAR, fg=SUB, font=FONT_S).pack(side="left", pady=(6, 0))

        right = tk.Frame(header, bg=SIDEBAR)
        right.pack(side="right", padx=20)
        self.header_dir = tk.Label(right, text="", bg=SIDEBAR, fg=SUB, font=FONT_S)
        self.header_dir.pack(side="left", padx=(0, 10))
        button(right, "打开目录", self.open_game_dir, "ghost").pack(side="left")
        self.header_dir.configure(text="游戏目录：%s" % self.cfg["game_dir"])

        # 侧边栏
        side = tk.Frame(self, bg=SIDEBAR, width=196)
        side.grid(row=1, column=0, sticky="ns")
        side.pack_propagate(False)
        tk.Frame(side, bg=LINE, height=1).pack(fill="x")
        for key, text in NAV:
            b = tk.Button(side, text=text, command=lambda k=key: self.show_page(k), anchor="w",
                          bg=SIDEBAR, fg=SUB, activebackground=CARD, activeforeground=TXT,
                          relief="flat", bd=0, padx=24, pady=9, font=FONT, cursor="hand2",
                          highlightthickness=0)
            b.pack(fill="x", pady=1)
            self.nav[key] = b

        # 主区域
        main = tk.Frame(self, bg=BG)
        main.grid(row=1, column=1, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self.body = tk.Frame(main, bg=BG)
        self.body.grid(row=0, column=0, sticky="nsew")

        console = tk.Frame(main, bg=SIDEBAR, height=124)
        console.grid(row=1, column=0, sticky="ew")
        console.pack_propagate(False)
        bar = tk.Frame(console, bg=SIDEBAR)
        bar.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(bar, text="运行日志", bg=SIDEBAR, fg=SUB, font=FONT_S).pack(side="left")
        tk.Button(bar, text="清空", command=self.clear_log, bg=SIDEBAR, fg=SUB, relief="flat",
                  bd=0, font=FONT_S, activebackground=SIDEBAR, activeforeground=TXT,
                  cursor="hand2").pack(side="right")

        text_wrap = tk.Frame(console, bg=SIDEBAR)
        text_wrap.pack(fill="both", expand=True, padx=12, pady=(2, 8))
        self.console = tk.Text(text_wrap, bg="#0b0e12", fg="#b9c3d0", insertbackground=TXT,
                               relief="flat", bd=0, font=MONO, wrap="word", height=7,
                               highlightthickness=1, highlightbackground=LINE, state="disabled")
        sb = ttk.Scrollbar(text_wrap, orient="vertical", command=self.console.yview,
                           style="Dark.Vertical.TScrollbar")
        self.console.configure(yscrollcommand=sb.set)
        self.console.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # 状态栏
        status = tk.Frame(self, bg=SIDEBAR, height=34)
        status.grid(row=2, column=0, columnspan=2, sticky="ew")
        status.pack_propagate(False)
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(status, textvariable=self.status_var, bg=SIDEBAR, fg=SUB, font=FONT_S,
                 anchor="w").pack(side="left", padx=20)
        self.pct_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self.pct_var, bg=SIDEBAR, fg=SUB, font=FONT_S).pack(side="right", padx=(0, 16))
        self.progress_canvas = tk.Canvas(status, bg=CARD2, height=8, width=240,
                                        highlightthickness=0, bd=0)
        self.progress_canvas.pack(side="right", padx=10, pady=13)
        self._progress_rect = self.progress_canvas.create_rectangle(0, 0, 0, 8, fill=ACC, width=0)

    # -- 页面容器 -----------------------------------------------------------
    def _new_page(self, key, title, subtitle=""):
        f = tk.Frame(self.body, bg=BG)
        self.pages[key] = f
        head = tk.Frame(f, bg=BG)
        head.pack(fill="x", padx=24, pady=(16, 4))
        tk.Label(head, text=title, bg=BG, fg=TXT, font=FONT_T, anchor="w").pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, bg=BG, fg=SUB, font=FONT_S).pack(side="left", padx=(12, 0), pady=(9, 0))

        outer = tk.Frame(f, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=(4, 16))
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        sb.grid(row=0, column=1, sticky="ns")

        inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _refresh(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if inner.winfo_reqheight() > canvas.winfo_height() + 1:
                sb.grid()
            else:
                canvas.yview_moveto(0)
                sb.grid_remove()

        inner.bind("<Configure>", _refresh)
        canvas.bind("<Configure>", lambda e: (canvas.itemconfigure(win, width=e.width), _refresh()))

        def _wheel(e):
            if inner.winfo_reqheight() <= canvas.winfo_height() + 1:
                return
            canvas.yview_scroll(-1 if getattr(e, "delta", 0) > 0 else 1, "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._canvases[key] = canvas
        return f, inner

    def _build_pages(self):
        self._build_home()
        self._build_java_versions()
        self._build_content("mods", "模组下载", "联网即预取热门模组 · 双击条目查看项目页与直链 · 支持 Fabric / Quilt / Forge / NeoForge",
                            "mod", "mods",
                            "下载后放入 mods 文件夹；Fabric 版本记得同时安装 Fabric API。")
        self._build_content("shaders", "光影下载", "联网即预取热门光影 · 双击条目查看项目页与直链",
                            "shader", "shaderpacks",
                            "光影需要 Iris（Fabric）或 OptiFine 才能加载。")
        self._build_content("packs", "资源包", "联网即预取热门资源包 · 双击条目查看项目页与直链",
                            "resourcepack", "resourcepacks", "")
        self._build_bedrock_versions()
        self._build_online()
        self._build_account()
        self._build_settings()

    # -- 首页 ---------------------------------------------------------------
    def _build_home(self):
        f, inner = self._new_page("home", "启动 Minecraft", "原版 · Fabric · 基岩版")
        inner.grid_columnconfigure(0, weight=3, uniform="home")
        inner.grid_columnconfigure(1, weight=2, uniform="home")
        inner.grid_rowconfigure(0, weight=1)
        inner.grid_rowconfigure(1, weight=0)

        # Java 卡片
        cj = card(inner)
        cj.grid(row=0, column=0, sticky="nsew", padx=(0, 14), pady=(0, 14))
        label(cj, "Java 版", TXT, FONT_H).pack(anchor="w", padx=18, pady=(12, 0))
        label(cj, "原版与 Fabric，自动补齐依赖库与资源文件", SUB, FONT_S).pack(anchor="w", padx=18)

        form = tk.Frame(cj, bg=CARD)
        form.pack(fill="both", expand=True, padx=18, pady=(8, 0))
        form.grid_columnconfigure(1, weight=1)

        label(form, "游戏版本", SUB, FONT_S).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.home_version = ttk.Combobox(form, state="readonly", values=[], font=FONT)
        self.home_version.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(0, 4))

        label(form, "玩家名", SUB, FONT_S).grid(row=1, column=0, sticky="w", pady=4)
        self.home_user = tk.StringVar(value=self.cfg.get("username", "Steve"))
        e = entry(form, self.home_user, width=18)
        e.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=4, ipady=5)

        label(form, "最大内存", SUB, FONT_S).grid(row=2, column=0, sticky="w", pady=4)
        memrow = tk.Frame(form, bg=CARD)
        memrow.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=4)
        self.home_mem = tk.StringVar(value=str(self.cfg.get("memory_mb", 4096)))
        entry(memrow, self.home_mem, width=8).pack(side="left", ipady=4)
        label(memrow, "MB", SUB, FONT_S).pack(side="left", padx=8)

        self.home_launch_btn = button(form, "启动游戏", self.launch_java, "primary")
        self.home_launch_btn.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 6), ipady=7)

        self.home_java_tip = label(form, "正在检测 Java…", SUB, FONT_S, wraplength=430)
        self.home_java_tip.grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 8))

        # 基岩卡片
        cb = card(inner)
        cb.grid(row=0, column=1, sticky="nsew", pady=(0, 14))
        label(cb, "基岩版", TXT, FONT_H).pack(anchor="w", padx=18, pady=(16, 0))
        label(cb, "Windows 版 Minecraft（Microsoft Store 版本）", SUB, FONT_S).pack(anchor="w", padx=18)
        self.home_bedrock_status = label(cb, "正在检测…", SUB, FONT_S)
        self.home_bedrock_status.pack(anchor="w", padx=18, pady=(18, 6))
        self.home_bedrock_btn = button(cb, "启动基岩版", self.launch_bedrock_home, "ghost")
        self.home_bedrock_btn.pack(fill="x", padx=18, pady=(0, 8), ipady=3)
        button(cb, "下载基岩版服务端 →", lambda: self.show_page("bversions"), "link").pack(anchor="w", padx=12, pady=(0, 4))
        label(cb, "基岩版通过系统协议启动，无需启动器接管进程。", SUB, FONT_S, wraplength=300).pack(anchor="w", padx=18, pady=(8, 12))

        # 快捷入口
        quick = card(inner)
        quick.grid(row=1, column=0, columnspan=2, sticky="ew")
        label(quick, "快捷入口", TXT, FONT_B).pack(side="left", padx=(18, 14), pady=14)
        for text, key in (("浏览模组", "mods"), ("浏览光影", "shaders"), ("Java 版版本", "jversions"),
                          ("基岩版版本", "bversions"), ("联机开房", "online")):
            button(quick, text, lambda k=key: self.show_page(k), "ghost").pack(side="left", padx=4, pady=10)
        self.home_quick_versions = label(quick, "", SUB, FONT_S)
        self.home_quick_versions.pack(side="right", padx=18)

    # -- 版本页 -------------------------------------------------------------
    def _build_java_versions(self):
        f, inner = self._new_page("jversions", "Java 版版本", "原版 / 快照 / Fabric")
        inner.columnconfigure(0, weight=3, uniform="v")
        inner.columnconfigure(1, weight=2, uniform="v")
        inner.rowconfigure(0, weight=1)

        left = card(inner)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        head = tk.Frame(left, bg=CARD)
        head.pack(fill="x", padx=16, pady=(14, 6))
        label(head, "已安装版本", TXT, FONT_B).pack(side="left")
        button(head, "刷新", self.refresh_installed, "link").pack(side="right")

        tree_wrap, self.version_tree = scrollable_tree(left, ("版本", "类型"), (280, 120), height=13)
        tree_wrap.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.version_tree.bind("<Double-1>", lambda e: self.use_selected_version())

        row = tk.Frame(left, bg=CARD)
        row.pack(fill="x", padx=16, pady=(0, 14))
        button(row, "设为启动版本", self.use_selected_version, "ghost").pack(side="left")
        button(row, "打开 versions", lambda: util.open_path(os.path.join(self.cfg["game_dir"], "versions")),
               "link").pack(side="left", padx=8)

        right = tk.Frame(inner, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        # 安装原版
        c1 = card(right)
        c1.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        label(c1, "安装游戏版本", TXT, FONT_B).pack(anchor="w", padx=16, pady=(14, 2))
        label(c1, "官方版本清单，自动下载核心、依赖库与资源文件", SUB, FONT_S).pack(anchor="w", padx=16)
        self.install_pick = ttk.Combobox(c1, state="readonly", values=[], font=FONT)
        self.install_pick.pack(fill="x", padx=16, pady=(10, 6))
        opt = tk.Frame(c1, bg=CARD)
        opt.pack(fill="x", padx=16)
        self.show_snapshot = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="显示快照与旧版本", variable=self.show_snapshot,
                        command=self.refresh_version_choices, style="TCheckbutton").pack(side="left")
        self.install_btn = button(c1, "安装", self.install_vanilla, "primary")
        self.install_btn.pack(fill="x", padx=16, pady=(10, 14))

        # 安装 Fabric
        c2 = card(right)
        c2.grid(row=1, column=0, sticky="ew")
        label(c2, "安装 Fabric", TXT, FONT_B).pack(anchor="w", padx=16, pady=(14, 2))
        label(c2, "自动选择最新稳定加载器，并装好对应原版基础", SUB, FONT_S).pack(anchor="w", padx=16)
        self.fabric_note = label(c2, "将安装到：%s" % self.cfg["game_dir"], SUB, FONT_S, wraplength=330)
        self.fabric_note.pack(anchor="w", padx=16, pady=(8, 4))
        self.fabric_btn = button(c2, "安装 Fabric", self.install_fabric_version, "ghost")
        self.fabric_btn.pack(fill="x", padx=16, pady=(4, 14))

        # 安装 Forge / NeoForge
        c3 = card(right)
        c3.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        label(c3, "安装 Forge / NeoForge", TXT, FONT_B).pack(anchor="w", padx=16, pady=(12, 2))
        label(c3, "官方安装器，需先装好对应原版；国内走 BMCLAPI 镜像", SUB, FONT_S).pack(anchor="w", padx=16)
        pick2 = tk.Frame(c3, bg=CARD)
        pick2.pack(fill="x", padx=16, pady=(8, 4))
        self.loader_pick = ttk.Combobox(pick2, state="readonly", values=["Forge", "NeoForge"], width=9, font=FONT)
        self.loader_pick.current(0)
        self.loader_pick.pack(side="left")
        self.loader_ver = ttk.Combobox(pick2, state="normal", values=[], font=FONT)
        self.loader_ver.pack(side="left", fill="x", expand=True, padx=8)
        button(pick2, "获取版本", self.refresh_loader_versions, "link").pack(side="left")
        self.forge_btn = button(c3, "安装所选加载器", self.install_forge_loader, "ghost")
        self.forge_btn.pack(fill="x", padx=16, pady=(4, 12))

    # -- 内容下载页（模组 / 光影 / 资源包） --------------------------------
    def _build_content(self, key, title, subtitle, ptype, folder, note):
        f, inner = self._new_page(key, title, subtitle)

        if ptype == "shader":
            self._build_shader_support(inner)

        bar = card(inner)
        bar.pack(fill="x", pady=(0, 10))
        inner_row = tk.Frame(bar, bg=CARD)
        inner_row.pack(fill="x", padx=14, pady=12)
        inner_row.columnconfigure(0, weight=1)

        query = tk.StringVar()
        qe = entry(inner_row, query, width=32)
        qe.grid(row=0, column=0, sticky="ew", ipady=6)
        qe.bind("<Return>", lambda e: self.search_content(key))

        gv = ttk.Combobox(inner_row, width=12, font=FONT)
        gv.grid(row=0, column=1, padx=8)
        label(inner_row, "游戏版本", SUB, FONT_S, bg=CARD).grid(row=1, column=1, sticky="w", padx=10, pady=(2, 0))

        loader = None
        if ptype == "mod":
            loader = ttk.Combobox(inner_row, state="readonly", values=["Fabric", "Quilt", "Forge", "NeoForge"],
                                  width=10, font=FONT)
            loader.grid(row=0, column=2, padx=(0, 8))
            label(inner_row, "加载器", SUB, FONT_S, bg=CARD).grid(row=1, column=2, sticky="w", padx=2, pady=(2, 0))

        button(inner_row, "搜索", lambda: self.search_content(key), "primary").grid(
            row=0, column=3, padx=(4, 0), ipady=2)

        tree_wrap, tree = scrollable_tree(inner, ("名称", "作者", "下载", "简介"),
                                          (230, 110, 70, 420), height=12)
        tree_wrap.pack(fill="both", expand=True)
        tree.bind("<Double-1>", lambda e: self.open_content_detail(key))
        tree.bind("<Return>", lambda e: self.open_content_detail(key))

        foot = tk.Frame(inner, bg=BG)
        foot.pack(fill="x", pady=(10, 0))
        self.content[key] = {"ptype": ptype, "folder": folder, "tree": tree, "query": query,
                             "gv": gv, "loader": loader, "note": note, "status": None}
        button(foot, "下载所选", lambda: self.download_content(key), "primary").pack(side="left")
        button(foot, "项目页 / 直链", lambda: self.open_content_detail(key), "ghost").pack(side="left", padx=8)
        button(foot, "打开 %s 文件夹" % folder,
               lambda: util.open_path(os.path.join(self.cfg["game_dir"], folder)), "ghost").pack(side="left", padx=8)
        st = label(foot, note, SUB, FONT_S, bg=BG)
        st.pack(side="right", padx=8)
        self.content[key]["status"] = st

    def _build_shader_support(self, parent):
        c = card(parent)
        c.pack(fill="x", pady=(0, 10))
        label(c, "光影前置：一键安装", TXT, FONT_B).pack(anchor="w", padx=16, pady=(12, 2))
        label(c, "Fabric → Iris + Sodium；Forge → Oculus + Embeddium；NeoForge → Iris", SUB, FONT_S,
              wraplength=820).pack(anchor="w", padx=16)
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=16, pady=(8, 12))
        self.shader_ver = ttk.Combobox(row, state="readonly", values=[], font=FONT, width=24)
        self.shader_ver.pack(side="left")
        self.shader_btn = button(row, "安装光影前置", self.install_shader_support, "primary")
        self.shader_btn.pack(side="left", padx=8)
        button(row, "OptiFine 官网", lambda: webbrowser.open("https://optifine.net/downloads"), "link").pack(
            side="left", padx=4)
        label(row, "装好前置后，光影包会出现在游戏内的光影选项中", SUB, FONT_S).pack(side="left", padx=8)
    def _build_bedrock_versions(self):
        f, inner = self._new_page("bversions", "基岩版版本", "客户端 · 服务端多版本下载")

        c1 = card(inner)
        c1.pack(fill="x", pady=(0, 12))
        label(c1, "基岩版客户端（Windows）", TXT, FONT_B).pack(anchor="w", padx=18, pady=(14, 2))
        label(c1, "客户端由 Microsoft Store 分发，启动器负责检测并拉起已安装的游戏", SUB, FONT_S).pack(
            anchor="w", padx=18)
        self.bedrock_status = label(c1, "正在检测…", SUB, FONT_S)
        self.bedrock_status.pack(anchor="w", padx=18, pady=(8, 6))
        self.bc_pick = ttk.Combobox(c1, state="readonly", values=[], font=FONT_S)
        self.bc_pick.pack(fill="x", padx=18, pady=(0, 8))
        self.bc_map = {}
        row = tk.Frame(c1, bg=CARD)
        row.pack(fill="x", padx=18, pady=(0, 14))
        button(row, "启动基岩版", self.launch_bedrock_page, "primary").pack(side="left")
        button(row, "重新检测", self.detect_bedrock, "ghost").pack(side="left", padx=8)
        button(row, "打开 Microsoft Store", self.open_store, "link").pack(side="left", padx=6)

        c2 = card(inner)
        c2.pack(fill="both", expand=True)
        label(c2, "服务端版本下载（BDS）", TXT, FONT_B).pack(anchor="w", padx=18, pady=(14, 2))
        label(c2, "官方正式版 / 预览版列表，也可按版本号补下历史版本", SUB, FONT_S).pack(anchor="w", padx=18)

        pickrow = tk.Frame(c2, bg=CARD)
        pickrow.pack(fill="x", padx=18, pady=(10, 4))
        self.bv_pick = ttk.Combobox(pickrow, state="readonly", values=[], font=FONT)
        self.bv_pick.pack(side="left", fill="x", expand=True)
        button(pickrow, "刷新列表", self.refresh_bds_versions, "ghost").pack(side="left", padx=6)
        button(pickrow, "下载", self.download_bds_selected, "primary").pack(side="left")

        manrow = tk.Frame(c2, bg=CARD)
        manrow.pack(fill="x", padx=18, pady=(4, 6))
        self.bv_manual = tk.StringVar()
        entry(manrow, self.bv_manual, width=16).pack(side="left", ipady=5)
        button(manrow, "下载指定版本号", self.download_bds_manual, "ghost").pack(side="left", padx=8)
        label(manrow, "例：1.21.51.02", SUB, FONT_S).pack(side="left")

        self.bv_status = label(c2, "正在读取官方版本列表…", SUB, FONT_S, wraplength=760)
        self.bv_status.pack(anchor="w", padx=18, pady=(2, 6))

        tree_wrap, self.bds_tree = scrollable_tree(c2, ("版本", "安装目录"), (140, 520), height=7)
        tree_wrap.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        foot = tk.Frame(c2, bg=CARD)
        foot.pack(fill="x", padx=18, pady=(0, 14))
        button(foot, "启动所选服务端", self.run_bds_selected, "ghost").pack(side="left")
        button(foot, "打开目录",
               lambda: util.open_path(bedrock.servers_root()), "link").pack(side="left", padx=8)
        button(foot, "删除所选", self.remove_bds_selected, "link").pack(side="left")
        self.bds_count = label(foot, "", SUB, FONT_S)
        self.bds_count.pack(side="right")

    # -- 联机页 -------------------------------------------------------------
    def _build_online(self):
        f, inner = self._new_page("online", "联机", "Java 版 · 免费公网隧道")

        c1 = card(inner)
        c1.pack(fill="x", pady=(0, 12))
        label(c1, "① 在游戏里开房", TXT, FONT_B).pack(anchor="w", padx=18, pady=(14, 2))
        label(c1, "进入世界后按 Esc → 对局域网开放 → 创建局域网世界", SUB, FONT_S).pack(anchor="w", padx=18)
        self.lan_label = label(c1, "正在检测局域网端口…", SUB, FONT_S, wraplength=800)
        self.lan_label.pack(anchor="w", padx=18, pady=(8, 6))
        row = tk.Frame(c1, bg=CARD)
        row.pack(fill="x", padx=18, pady=(0, 14))
        button(row, "检测端口", self.detect_lan_port_click, "ghost").pack(side="left")
        button(row, "复制内网地址", self.copy_lan_address, "link").pack(side="left", padx=8)
        label(row, "同一 WiFi 下的朋友用这个地址直连", SUB, FONT_S).pack(side="left", padx=6)

        c2 = card(inner)
        c2.pack(fill="both", expand=True)
        label(c2, "② 开公网隧道，邀请好友", TXT, FONT_B).pack(anchor="w", padx=18, pady=(14, 2))
        label(c2, "使用开源项目 bore 的免费公共服务器，无需注册；延迟取决于线路", SUB, FONT_S).pack(
            anchor="w", padx=18)
        self.tunnel_port = tk.StringVar(value="")
        rowp = tk.Frame(c2, bg=CARD)
        rowp.pack(fill="x", padx=18, pady=(10, 4))
        label(rowp, "端口", SUB, FONT_S).pack(side="left")
        entry(rowp, self.tunnel_port, width=10).pack(side="left", padx=8, ipady=5)
        self.tunnel_btn = button(rowp, "开启隧道", self.toggle_tunnel, "primary")
        self.tunnel_btn.pack(side="left", padx=4)
        button(rowp, "复制联机地址", self.copy_tunnel_address, "ghost").pack(side="left", padx=6)

        self.tunnel_addr = label(c2, "尚未开启隧道", TXT, ("Consolas", 13), wraplength=800)
        self.tunnel_addr.pack(anchor="w", padx=18, pady=(10, 2))
        self.tunnel_state = label(c2, "好友在 多人游戏 → 直接连接 里输入上面的地址即可加入", SUB, FONT_S,
                                  wraplength=800)
        self.tunnel_state.pack(anchor="w", padx=18, pady=(0, 8))
        label(c2, tunnel.udp_note(), SUB, FONT_S, wraplength=800).pack(anchor="w", padx=18, pady=(0, 14))

    def detect_lan_port_click(self):
        self.lan_label.configure(text="检测中…", fg=SUB)

        def done(res):
            port, path = res
            if port:
                self.lan_port = port
                ip = tunnel.local_ip()
                self.lan_label.configure(
                    text="检测到局域网端口 %d（内网地址 %s:%d）" % (port, ip, port), fg=TXT)
                if not self.tunnel_port.get():
                    self.tunnel_port.set(str(port))
                if not getattr(self, "_port_logged", None) or self._port_logged != port:
                    self.log("检测到局域网端口 %d" % port)
                    self._port_logged = port
            else:
                self.lan_port = None
                self.lan_label.configure(
                    text="未检测到——先在游戏里按 Esc → 对局域网开放，然后再点检测", fg=SUB)

        self.bg(lambda: tunnel.detect_lan_port(self.cfg["game_dir"]), done=done,
                err=lambda e: self.lan_label.configure(text="检测失败：%s" % e, fg=SUB))

    def copy_lan_address(self):
        port = getattr(self, "lan_port", None)
        if not port:
            messagebox.showinfo("还没有端口", "先开好局域网世界并点“检测端口”。")
            return
        addr = "%s:%d" % (tunnel.local_ip(), port)
        self.clipboard_clear()
        self.clipboard_append(addr)
        self.log("已复制内网地址 %s" % addr)
        self.set_status("已复制 %s" % addr)

    def toggle_tunnel(self):
        proc = getattr(self, "tunnel_proc", None)
        if proc and proc.poll() is None:
            tunnel.stop_bore(proc)
            self.tunnel_proc = None
            self.tunnel_btn.configure(text="开启隧道")
            self.tunnel_addr.configure(text="隧道已关闭")
            self.tunnel_state.configure(text="好友在 多人游戏 → 直接连接 里输入地址即可加入")
            self.tunnel_address = ""
            self.set_status("联机隧道已关闭")
            return

        try:
            port = int((self.tunnel_port.get() or "").strip())
            if not (0 < port < 65536):
                raise ValueError
        except Exception:
            messagebox.showinfo("端口无效", "先检测端口，或手动填入 1-65535 的端口号。")
            return

        self.tunnel_btn.configure(state="disabled", text="连接中…")
        self.tunnel_state.configure(text="正在连接 bore.pub…")

        def work():
            tunnel.ensure_bore(status=self.status_cb, progress=self.progress_cb)
            return tunnel.start_bore(
                port,
                on_line=None,
                on_address=lambda a: self.post(lambda: self._tunnel_address(a)),
            )

        def done(p):
            self.tunnel_proc = p
            self.tunnel_btn.configure(state="normal", text="关闭隧道")
            self.set_status("联机隧道运行中")

            def waiter():
                code = p.wait()
                self.post(lambda: self._tunnel_exit(p, code))

            threading.Thread(target=waiter, daemon=True).start()

        def err(e):
            self.tunnel_btn.configure(state="normal", text="开启隧道")
            self.tunnel_state.configure(text="隧道启动失败：%s" % e)
            self.log("联机隧道失败：%s" % e)
            messagebox.showerror("联机隧道失败", str(e))

        self.bg(work, done=done, err=err)

    def _tunnel_address(self, address):
        self.tunnel_address = address
        self.tunnel_addr.configure(text=address)
        self.tunnel_state.configure(text="已连接：把 %s 发给好友，在多人游戏里直接连接" % address)
        self.log("公网联机地址：%s" % address)

    def _tunnel_exit(self, proc, code):
        if getattr(self, "tunnel_proc", None) is proc:
            self.tunnel_proc = None
            self.tunnel_btn.configure(state="normal", text="开启隧道")
            self.tunnel_state.configure(text="隧道已断开（退出码 %s），可重新开启" % code)
            self.log("联机隧道已断开（退出码 %s）" % code)

    def copy_tunnel_address(self):
        addr = getattr(self, "tunnel_address", "")
        if not addr:
            messagebox.showinfo("还没有地址", "先点“开启隧道”，等出现公网地址后再复制。")
            return
        self.clipboard_clear()
        self.clipboard_append(addr)
        self.log("已复制联机地址 %s" % addr)
        self.set_status("已复制 %s" % addr)

    # -- 账号页 -------------------------------------------------------------
    def _build_account(self):
        f, inner = self._new_page("account", "账号", "离线 · 外置登录 · 微软正版")

        c0 = card(inner)
        c0.pack(fill="x", pady=(0, 10))
        label(c0, "当前账号", TXT, FONT_B).pack(anchor="w", padx=18, pady=(12, 2))
        self.account_label = label(c0, "", ACC, FONT, wraplength=820)
        self.account_label.pack(anchor="w", padx=18, pady=(0, 6))
        row0 = tk.Frame(c0, bg=CARD)
        row0.pack(fill="x", padx=18, pady=(0, 12))
        button(row0, "退出登录（回到离线）", self.logout_account, "ghost").pack(side="left")

        c1 = card(inner)
        c1.pack(fill="x", pady=(0, 10))
        label(c1, "离线登录", TXT, FONT_B).pack(anchor="w", padx=18, pady=(12, 2))
        label(c1, "只改玩家名，不需要账号密码；适合单机和局域网联机", SUB, FONT_S).pack(anchor="w", padx=18)
        row1 = tk.Frame(c1, bg=CARD)
        row1.pack(fill="x", padx=18, pady=(8, 12))
        self.acc_offline = tk.StringVar(value=self.cfg.get("username", "Steve"))
        entry(row1, self.acc_offline, width=18).pack(side="left", ipady=5)
        button(row1, "使用离线账号", self.use_offline_account, "ghost").pack(side="left", padx=8)

        c2 = card(inner)
        c2.pack(fill="x", pady=(0, 10))
        label(c2, "外置登录（authlib-injector）", TXT, FONT_B).pack(anchor="w", padx=18, pady=(12, 2))
        label(c2, "适用于支持 authlib-injector 的服务器 / 皮肤站，例如 LittleSkin", SUB, FONT_S).pack(
            anchor="w", padx=18)
        grid2 = tk.Frame(c2, bg=CARD)
        grid2.pack(fill="x", padx=18, pady=(8, 4))
        grid2.columnconfigure(1, weight=1)
        label(grid2, "API 地址", SUB, FONT_S).grid(row=0, column=0, sticky="w", pady=3)
        self.acc_api = tk.StringVar(value=self.cfg.get("authlib_api", "https://littleskin.cn/api/yggdrasil"))
        entry(grid2, self.acc_api, width=40).grid(row=0, column=1, sticky="ew", padx=8, pady=3, ipady=4)
        label(grid2, "邮箱/用户名", SUB, FONT_S).grid(row=1, column=0, sticky="w", pady=3)
        self.acc_user = tk.StringVar()
        entry(grid2, self.acc_user, width=28).grid(row=1, column=1, sticky="ew", padx=8, pady=3, ipady=4)
        label(grid2, "密码", SUB, FONT_S).grid(row=2, column=0, sticky="w", pady=3)
        self.acc_pass = tk.StringVar()
        pw = tk.Entry(grid2, textvariable=self.acc_pass, show="*", width=28, bg=CARD2, fg=TXT,
                       insertbackground=TXT, relief="flat", bd=0, highlightthickness=1,
                       highlightbackground=LINE, highlightcolor=ACC, font=FONT)
        pw.grid(row=2, column=1, sticky="ew", padx=8, pady=3, ipady=4)
        row2 = tk.Frame(c2, bg=CARD)
        row2.pack(fill="x", padx=18, pady=(6, 12))
        button(row2, "登录外置账号", self.login_authlib, "primary").pack(side="left")
        label(row2, "密码只用于本次登录，不会保存", SUB, FONT_S).pack(side="left", padx=8)

        c3 = card(inner)
        c3.pack(fill="x")
        label(c3, "微软正版登录（设备码）", TXT, FONT_B).pack(anchor="w", padx=18, pady=(12, 2))
        label(c3, "需要一个自备的 Azure 应用 Client ID（公开客户端，开启设备码流程），"
                  "登录后即可用正版账号进入服务器", SUB, FONT_S, wraplength=820).pack(anchor="w", padx=18)
        row3 = tk.Frame(c3, bg=CARD)
        row3.pack(fill="x", padx=18, pady=(8, 4))
        self.acc_client = tk.StringVar(value=self.cfg.get("msa_client_id", ""))
        entry(row3, self.acc_client, width=42).pack(side="left", ipady=5)
        button(row3, "微软登录", self.login_msa, "primary").pack(side="left", padx=8)
        self.msa_note = label(c3, "", SUB, FONT_S, wraplength=820)
        self.msa_note.pack(anchor="w", padx=18, pady=(0, 12))

    def update_account_label(self):
        modes = {"offline": "离线模式", "authlib": "外置登录", "msa": "微软正版"}
        mode = modes.get((self.account or {}).get("mode"), "离线模式")
        name = (self.account or {}).get("name") or self.cfg.get("username", "Steve")
        self.account_label.configure(text="%s（%s）" % (name, mode))

    def use_offline_account(self):
        name = (self.acc_offline.get() or "").strip() or "Steve"
        self.account = {"mode": "offline", "name": name}
        self.cfg["username"] = name
        util.save_config(self.cfg)
        self.home_user.set(name)
        self.update_account_label()
        self.log("已切换到离线账号：%s" % name)
        self.set_status("离线账号：%s" % name)

    def logout_account(self):
        self.account = {"mode": "offline", "name": self.cfg.get("username", "Steve")}
        self.update_account_label()
        self.log("已退出登录，回到离线模式")
        self.set_status("已退出登录")

    def login_authlib(self):
        api = (self.acc_api.get() or "").strip()
        user = (self.acc_user.get() or "").strip()
        password = self.acc_pass.get() or ""
        if not (api and user and password):
            messagebox.showinfo("信息不完整", "请填写 API 地址、账号和密码。")
            return
        self.set_status("外置登录中…")

        def work():
            return auth.yggdrasil_login(api, user, password, status=lambda s: self.status_cb(s))

        def done(acc):
            self.account = acc
            self.cfg["authlib_api"] = acc.get("api") or api
            util.save_config(self.cfg)
            self.update_account_label()
            self.home_user.set(acc.get("name"))
            self.log("外置登录成功：%s" % acc.get("name"))
            self.set_status("外置登录成功")
            messagebox.showinfo("登录成功", "已登录为 %s。" % acc.get("name"))

        def err(e):
            self.log("外置登录失败：%s" % e)
            self.set_status("外置登录失败")
            messagebox.showerror("登录失败", str(e))

        self.bg(work, done=done, err=err)

    def login_msa(self):
        client_id = (self.acc_client.get() or "").strip()
        if not client_id:
            messagebox.showinfo("需要 Client ID",
                                "微软登录需要你自己注册一个 Azure 应用（公开客户端 + 设备码流程），\n"
                                "把它的 Client ID 填到上方输入框。")
            return
        self.cfg["msa_client_id"] = client_id
        util.save_config(self.cfg)
        self.set_status("微软登录：等待浏览器授权…")
        self.msa_note.configure(text="正在申请设备码…")

        def work():
            return auth.msa_device_login(
                client_id,
                status=lambda s: self.status_cb(s),
                on_code=lambda code, uri: self.post(lambda: self._show_msa_code(code, uri)),
            )

        def done(acc):
            self.account = acc
            self.update_account_label()
            self.home_user.set(acc.get("name"))
            self.msa_note.configure(text="已登录：%s" % acc.get("name"))
            self.log("微软登录成功：%s" % acc.get("name"))
            self.set_status("微软登录成功")
            messagebox.showinfo("登录成功", "已登录为 %s。" % acc.get("name"))

        def err(e):
            self.msa_note.configure(text="登录失败")
            self.log("微软登录失败：%s" % e)
            self.set_status("微软登录失败")
            messagebox.showerror("微软登录失败", str(e))

        self.bg(work, done=done, err=err)

    def _show_msa_code(self, code, uri):
        try:
            self.clipboard_clear()
            self.clipboard_append(code)
        except Exception:
            pass
        if uri:
            try:
                webbrowser.open(uri)
            except Exception:
                pass
        self.msa_note.configure(text="等待授权：%s" % code)
        messagebox.showinfo("微软登录",
                            "已把设备码复制到剪贴板：\n\n    %s\n\n请在浏览器打开的页面里输入该代码并完成登录。" % code)

    # -- 设置页 -------------------------------------------------------------
    def _build_settings(self):
        f, inner = self._new_page("settings", "设置", "目录 · Java · 启动参数")

        c1 = card(inner)
        c1.pack(fill="x", pady=(0, 12))
        label(c1, "游戏目录", TXT, FONT_B).pack(anchor="w", padx=18, pady=(14, 6))
        self.set_dir = tk.StringVar(value=self.cfg["game_dir"])
        row = tk.Frame(c1, bg=CARD)
        row.pack(fill="x", padx=18, pady=(0, 16))
        row.columnconfigure(0, weight=1)
        entry(row, self.set_dir).grid(row=0, column=0, sticky="ew", ipady=6)
        button(row, "选择", self.choose_game_dir, "ghost").grid(row=0, column=1, padx=8)
        button(row, "打开", lambda: util.open_path(self.cfg["game_dir"]), "ghost").grid(row=0, column=2)

        c2 = card(inner)
        c2.pack(fill="x", pady=(0, 12))
        label(c2, "Java 运行时", TXT, FONT_B).pack(anchor="w", padx=18, pady=(14, 6))
        self.set_java = ttk.Combobox(c2, state="readonly", values=["自动检测（推荐）"], font=FONT)
        self.set_java.pack(fill="x", padx=18)
        self.java_status = label(c2, "", SUB, FONT_S)
        self.java_status.pack(anchor="w", padx=18, pady=(6, 4))
        row2 = tk.Frame(c2, bg=CARD)
        row2.pack(fill="x", padx=18, pady=(0, 16))
        button(row2, "重新检测", self.refresh_java, "ghost").pack(side="left")
        button(row2, "下载 Java 17", lambda: self.download_java(17), "ghost").pack(side="left", padx=8)
        button(row2, "下载 Java 21", lambda: self.download_java(21), "ghost").pack(side="left")
        button(row2, "下载 Java 25", lambda: self.download_java(25), "ghost").pack(side="left", padx=8)

        c3 = card(inner)
        c3.pack(fill="x")
        label(c3, "默认启动参数", TXT, FONT_B).pack(anchor="w", padx=18, pady=(14, 6))
        grid = tk.Frame(c3, bg=CARD)
        grid.pack(fill="x", padx=18, pady=(0, 16))
        label(grid, "玩家名", SUB, FONT_S).grid(row=0, column=0, sticky="w", pady=4)
        self.set_user = tk.StringVar(value=self.cfg.get("username", "Steve"))
        entry(grid, self.set_user, width=20).grid(row=0, column=1, padx=10, pady=4, ipady=5)
        label(grid, "内存 (MB)", SUB, FONT_S).grid(row=0, column=2, sticky="w", padx=(20, 0))
        self.set_mem = tk.StringVar(value=str(self.cfg.get("memory_mb", 4096)))
        entry(grid, self.set_mem, width=8).grid(row=0, column=3, padx=10, pady=4, ipady=5)
        label(grid, "分辨率", SUB, FONT_S).grid(row=0, column=4, sticky="w", padx=(20, 0))
        self.set_w = tk.StringVar(value=str(self.cfg.get("width", 854)))
        self.set_h = tk.StringVar(value=str(self.cfg.get("height", 480)))
        wf = tk.Frame(grid, bg=CARD)
        wf.grid(row=0, column=5, sticky="w", padx=10)
        entry(wf, self.set_w, width=6).pack(side="left")
        label(wf, "×", SUB, FONT_S).pack(side="left", padx=3)
        entry(wf, self.set_h, width=6).pack(side="left")

        button(c3, "保存设置", self.save_settings, "primary").pack(anchor="w", padx=18, pady=(0, 16), ipady=4)

    # ------------------------------------------------------------------ #
    # 队列 / 后台任务
    # ------------------------------------------------------------------ #
    def post(self, fn):
        self.q.put(fn)

    def bg(self, fn, done=None, err=None):
        def run():
            try:
                res = fn()
            except Exception as e:
                if err:
                    self.post(lambda: err(e))
                else:
                    self.post(lambda: self.log("错误：%s" % e))
                return
            if done:
                self.post(lambda: done(res))

        threading.Thread(target=run, daemon=True).start()

    def status_cb(self, text):
        self.post(lambda: self.set_status(text))

    def progress_cb(self, frac):
        self.post(lambda: self.set_progress(frac))

    def _tick(self):
        try:
            while True:
                fn = self.q.get_nowait()
                try:
                    fn()
                except Exception as e:
                    print("UI callback error:", e)
        except queue.Empty:
            pass
        self.after(50, self._tick)

    def set_status(self, text):
        self.status_var.set(text)

    def set_progress(self, frac):
        frac = max(0.0, min(1.0, frac))
        self.progress_canvas.coords(self._progress_rect, 0, 0, 240 * frac, 8)
        self.pct_var.set("%d%%" % int(frac * 100) if frac > 0 else "")

    def log(self, text):
        stamp = time.strftime("%H:%M:%S")
        self.console.configure(state="normal")
        self.console.insert("end", "[%s] %s\n" % (stamp, text))
        if int(self.console.index("end-1c").split(".")[0]) > 2600:
            self.console.delete("1.0", "400.0")
        self.console.see("end")
        self.console.configure(state="disabled")

    def clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # 页面切换
    # ------------------------------------------------------------------ #
    def show_page(self, key):
        for k, f in self.pages.items():
            f.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for k, b in self.nav.items():
            active = k == key
            b.configure(bg=CARD if active else SIDEBAR, fg=TXT if active else SUB,
                        font=FONT_B if active else FONT)
        self.current_page = key
        if key == "home":
            self.refresh_installed()
            self.refresh_java(silent=True)
        elif key == "jversions":
            self.refresh_installed()
        elif key in ("mods", "shaders", "packs"):
            self._fill_gv(self.content[key]["gv"])
            if key == "shaders" and hasattr(self, "shader_ver"):
                ids = self.installed_versions()
                self.shader_ver.configure(values=ids)
                if ids and not self.shader_ver.get():
                    self.shader_ver.set(ids[0])
        elif key == "bversions":
            self.detect_bedrock()
            self.refresh_bds_versions()
            self.refresh_bds_installed()
        elif key == "online":
            self.detect_lan_port_click()
        elif key == "account":
            self.update_account_label()
        elif key == "settings":
            self.refresh_java(silent=True)

    # ------------------------------------------------------------------ #
    # 启动流程：清单、Java、版本
    # ------------------------------------------------------------------ #
    def _boot(self):
        self.log("启动器已启动，游戏目录：%s" % self.cfg["game_dir"])
        os.makedirs(self.cfg["game_dir"], exist_ok=True)
        self.refresh_installed()
        self.set_status("获取版本清单…")
        self.prefetch_content()

        def work():
            return mojang.get_manifest()

        self.bg(work, done=self._on_manifest, err=lambda e: self.log("版本清单获取失败：%s" % e))

    def _on_manifest(self, manifest):
        self.manifest = manifest
        latest = (manifest.get("latest") or {}).get("release")
        self.log("版本清单已加载，共 %d 个版本，最新正式版 %s" % (len(manifest.get("versions", [])), latest))
        self.set_status("就绪")
        self.refresh_version_choices()
        if self.install_pick.get() == "" and latest:
            self.install_pick.set(latest)
        self.refresh_installed()
        self.detect_bedrock()
        self.prefetch_content()

    def refresh_version_choices(self):
        if not self.manifest:
            return
        versions = self.manifest.get("versions", [])
        if self.show_snapshot.get():
            ids = [v["id"] for v in versions]
        else:
            ids = [v["id"] for v in versions if v.get("type") == "release"]
        self.install_pick.configure(values=ids[:300])
        if not self.install_pick.get() and ids:
            self.install_pick.set(ids[0])

    def installed_versions(self):
        vdir = os.path.join(self.cfg["game_dir"], "versions")
        if not os.path.isdir(vdir):
            return []
        items = []
        for name in os.listdir(vdir):
            jp = os.path.join(vdir, name, name + ".json")
            if os.path.isfile(jp):
                try:
                    items.append((os.path.getmtime(jp), name))
                except Exception:
                    items.append((0, name))
        items.sort(reverse=True)
        return [n for _, n in items]

    def refresh_installed(self):
        ids = self.installed_versions()
        self.home_version.configure(values=ids)
        if ids and self.home_version.get() not in ids:
            self.home_version.set(self.cfg.get("last_version") if self.cfg.get("last_version") in ids else ids[0])
        if hasattr(self, "version_tree"):
            for item in self.version_tree.get_children():
                self.version_tree.delete(item)
            for vid in ids:
                kind = "Fabric" if vid.startswith("fabric-loader") else (
                    "快照" if any(c.isalpha() for c in vid.strip("0123456789.-")) else "正式版")
                self.version_tree.insert("", "end", iid=vid, values=(vid, kind))
        if hasattr(self, "home_quick_versions"):
            self.home_quick_versions.configure(text="已安装 %d 个版本" % len(ids))

    def _fill_gv(self, combo):
        if combo.get():
            return
        ids = self.installed_versions()
        if ids:
            base = [v for v in ids if not v.startswith("fabric-loader")]
            combo.configure(values=base or ids)
            combo.set((base or ids)[0])
        elif self.manifest:
            rel = [v["id"] for v in self.manifest.get("versions", []) if v.get("type") == "release"]
            combo.configure(values=rel[:120])
            combo.set(rel[0] if rel else "")

    def refresh_java(self, silent=False):
        def work():
            return javamod.find_javas()

        def done(javas):
            self.java_list = javas
            if javas:
                best = javas[0]
                self.home_java_tip.configure(
                    text="已检测到 %d 个 Java，最高 Java %s（%s）" % (
                        len(javas), best["major"], os.path.basename(os.path.dirname(os.path.dirname(best["path"]))))
                )
                self.java_status.configure(text="检测到：%s" % "；".join(
                    "Java %d" % j["major"] for j in javas[:6]))
                values = ["自动检测（推荐）"] + ["Java %d — %s" % (j["major"], j["path"]) for j in javas]
                self.set_java.configure(values=values)
                if self.set_java.get() not in values:
                    idx = 0
                    cur = self.cfg.get("java_path", "")
                    for i, v in enumerate(values):
                        if cur and cur in v:
                            idx = i
                    self.set_java.current(idx)
            else:
                self.home_java_tip.configure(text="未检测到 Java，启动时会自动下载所需版本")
                self.java_status.configure(text="未检测到 Java")
                self.set_java.configure(values=["自动检测（推荐）"])
            if not silent:
                self.log("Java 检测完成，共 %d 个" % len(javas))

        self.bg(work, done=done, err=lambda e: self.log("Java 检测失败：%s" % e))

    # ------------------------------------------------------------------ #
    # 启动 Java 版
    # ------------------------------------------------------------------ #
    def launch_java(self):
        vid = (self.home_version.get() or "").strip()
        if not vid:
            messagebox.showwarning("没有可启动的版本", "请先到“版本与安装”安装一个游戏版本。")
            return
        username = (self.account or {}).get("name") or (self.home_user.get() or "").strip() or "Steve"
        try:
            mem = int(self.home_mem.get())
        except Exception:
            mem = 4096
        self.cfg.update({"last_version": vid, "memory_mb": mem})
        if (self.account or {}).get("mode", "offline") == "offline":
            self.cfg["username"] = username
        util.save_config(self.cfg)
        self.home_launch_btn.configure(state="disabled", text="准备中…")
        self.log("准备启动 %s（玩家 %s，内存 %d MB）" % (vid, username, mem))
        self.set_progress(0)

        def work():
            vj, root = mojang.resolve_version(self.cfg["game_dir"], vid)
            major = mojang.guess_java_major(vj)
            self.status_cb("检查 Java %d…" % major)
            java_exe = javamod.ensure_java(
                major, preferred=self.cfg.get("java_path", ""),
                status=lambda s: self.status_cb(s), progress=lambda f: self.progress_cb(f),
            )

            auth_info, extra_jvm = None, []
            acc = self.account or {"mode": "offline"}
            if acc.get("mode") == "authlib":
                self.status_cb("准备 authlib-injector…")
                jar = auth.authlib_jar(status=lambda s: self.status_cb(s),
                                       progress=lambda f: self.progress_cb(f))
                extra_jvm = ["-javaagent:%s=%s" % (jar, acc.get("api"))]
                auth_info = {"name": acc.get("name"), "uuid": acc.get("uuid"),
                             "token": acc.get("token"), "user_type": "mojang"}
            elif acc.get("mode") == "msa":
                auth_info = {"name": acc.get("name"), "uuid": acc.get("uuid"),
                             "token": acc.get("token"), "user_type": "msa"}

            cmd, merged, root_id, missing = mojang.build_command(
                self.cfg["game_dir"], vid, java_exe, username, mem,
                int(self.cfg.get("width", 854)), int(self.cfg.get("height", 480)),
                auth=auth_info, extra_jvm=extra_jvm,
            )
            return {"cmd": cmd, "java": java_exe, "major": major, "missing": missing,
                    "root": root_id, "auth": (acc.get("mode") or "offline")}

        self.bg(work, done=self._start_game, err=self._launch_failed)

    def _start_game(self, info):
        self.log("Java 运行时：%s（Java %s，账号模式 %s）" % (info["java"], info["major"], info.get("auth")))
        if info["missing"]:
            self.log("提示：%d 个依赖库缺失，若启动失败请在“版本与安装”重新安装该版本" % info["missing"])
        try:
            self.proc = mojang.launch(info["cmd"], self.cfg["game_dir"],
                                      on_output=lambda line: self.post(lambda l=line: self._game_line(l)))
        except Exception as e:
            self._launch_failed(e)
            return
        self.log("游戏进程已拉起（pid=%s），等待窗口出现…" % self.proc.pid)
        self.set_status("游戏运行中")
        self.set_progress(1)
        self.home_launch_btn.configure(state="normal", text="启动游戏")

        proc = self.proc

        def waiter():
            code = proc.wait()
            self.post(lambda: self._game_exit(code))

        threading.Thread(target=waiter, daemon=True).start()

    def _game_line(self, line):
        if not line.strip():
            return
        self.console.configure(state="normal")
        self.console.insert("end", line + "\n")
        lines = int(self.console.index("end-1c").split(".")[0])
        if lines > 2600:
            self.console.delete("1.0", "400.0")
        self.console.see("end")
        self.console.configure(state="disabled")

    def _game_exit(self, code):
        self.log("游戏进程已退出（退出码 %s）" % code)
        self.set_status("就绪")
        self.home_launch_btn.configure(state="normal", text="启动游戏")
        if code not in (0, None):
            self.log("若游戏未正常打开，请检查上方日志里的报错信息")

    def _launch_failed(self, err):
        self.log("启动失败：%s" % err)
        self.set_status("启动失败")
        self.home_launch_btn.configure(state="normal", text="启动游戏")
        messagebox.showerror("启动失败", str(err))

    # ------------------------------------------------------------------ #
    # 安装
    # ------------------------------------------------------------------ #
    def install_vanilla(self):
        if not self.manifest:
            messagebox.showwarning("清单未就绪", "版本清单还在加载，请稍等。")
            return
        vid = (self.install_pick.get() or "").strip()
        if not vid:
            return
        self.install_btn.configure(state="disabled", text="安装中…")
        self.log("开始安装 %s" % vid)
        mm = mojang.manifest_map(self.manifest)

        def work():
            install = mojang.Installer(self.cfg["game_dir"], mm,
                                       status=lambda s: self.status_cb(s),
                                       progress=lambda f: self.progress_cb(f))
            return install.install(vid)[0]

        self.bg(work, done=self._install_done, err=self._install_failed)

    def _install_done(self, vid):
        self.install_btn.configure(state="normal", text="安装")
        self.set_status("安装完成：%s" % vid)
        self.log("%s 安装完成，可以直接启动" % vid)
        self.refresh_installed()
        self.home_version.set(vid)
        self.cfg["last_version"] = vid
        util.save_config(self.cfg)

    def _install_failed(self, err):
        self.install_btn.configure(state="normal", text="安装")
        self.set_status("安装失败")
        self.log("安装失败：%s" % err)
        messagebox.showerror("安装失败", str(err))

    def install_fabric_version(self):
        vid = (self.install_pick.get() or "").strip()
        if not vid:
            messagebox.showwarning("请选择版本", "先在上方选择要搭配 Fabric 的游戏版本。")
            return
        if not self.manifest:
            messagebox.showwarning("清单未就绪", "版本清单还在加载，请稍等。")
            return
        self.fabric_btn.configure(state="disabled", text="安装中…")
        self.log("开始安装 Fabric（基础版本 %s）" % vid)
        mm = mojang.manifest_map(self.manifest)
        gd = self.cfg["game_dir"]

        def work():
            return mojang.install_fabric(gd, vid, status=lambda s: self.status_cb(s),
                                         progress=lambda f: self.progress_cb(f), manifest=mm)

        def done(fvid):
            self.fabric_btn.configure(state="normal", text="安装 Fabric")
            self.log("Fabric 安装完成：%s" % fvid)
            self.set_status("Fabric 已就绪")
            self.refresh_installed()
            self.home_version.set(fvid)
            self.cfg["last_version"] = fvid
            util.save_config(self.cfg)
            messagebox.showinfo("Fabric 已安装", "版本 %s 已就绪，可直接在首页启动。\n模组请放入 mods 文件夹。" % fvid)

        def err(e):
            self.fabric_btn.configure(state="normal", text="安装 Fabric")
            self.log("Fabric 安装失败：%s" % e)
            messagebox.showerror("Fabric 安装失败", str(e))

        self.bg(work, done=done, err=err)

    def refresh_loader_versions(self):
        mc = (self.install_pick.get() or "").strip()
        if not mc:
            messagebox.showinfo("先选游戏版本", "在上方选择要安装 Forge / NeoForge 的游戏版本。")
            return
        loader = "forge" if self.loader_pick.get() == "Forge" else "neoforge"
        self.set_status("读取 %s 可用版本…" % loader)
        self.loader_ver.configure(values=[])

        def work():
            return forge.list_forge(mc) if loader == "forge" else forge.list_neoforge(mc)

        def done(versions):
            self.loader_ver.configure(values=versions)
            if versions:
                self.loader_ver.current(0)
                self.log("%s %s 可用版本 %d 个" % (loader, mc, len(versions)))
                self.set_status("就绪")
            else:
                self.log("%s %s 官方版本列表取不到（maven 源不可用）" % (loader, mc))
                self.set_status("请手动填写版本号")
                messagebox.showinfo(
                    "需要手动填版本号",
                    "无法读取 %s %s 的版本列表（maven 源在这台机器上不可达）。\n\n"
                    "可以到 neoforged.net 查到版本号后，直接填进下拉框，例如：21.1.133。"
                    % (loader, mc))

        def err(e):
            self.log("加载器版本获取失败：%s" % e)
            self.set_status("获取失败")
            messagebox.showerror("获取失败", str(e))

        self.bg(work, done=done, err=err)

    def install_forge_loader(self):
        mc = (self.install_pick.get() or "").strip()
        ver = (self.loader_ver.get() or "").strip()
        if not mc or not ver:
            messagebox.showinfo("缺少选择", "先选游戏版本并点“获取版本”。")
            return
        if not self.manifest:
            messagebox.showwarning("清单未就绪", "版本清单还在加载，请稍等。")
            return
        loader = "forge" if self.loader_pick.get() == "Forge" else "neoforge"
        self.forge_btn.configure(state="disabled", text="安装中…")
        self.log("开始安装 %s %s（游戏 %s）" % (loader, ver, mc))
        mm = mojang.manifest_map(self.manifest)
        gd = self.cfg["game_dir"]

        def work():
            mojang.Installer(gd, mm, status=lambda s: self.status_cb(s),
                             progress=lambda f: self.progress_cb(f)).install(mc)
            vj = util.read_json(os.path.join(gd, "versions", mc, mc + ".json"), {}) or {}
            major = mojang.guess_java_major(dict(vj, id=mc))
            self.status_cb("准备 Java %s…" % major)
            java_exe = javamod.ensure_java(major, preferred=self.cfg.get("java_path", ""),
                                           status=lambda s: self.status_cb(s),
                                           progress=lambda f: self.progress_cb(f))
            return forge.install_loader(gd, mc, loader, ver, java_exe,
                                        status=lambda s: self.status_cb(s),
                                        progress=lambda f: self.progress_cb(f))

        def done(vid):
            self.forge_btn.configure(state="normal", text="安装所选加载器")
            self.log("%s 安装完成：%s" % (loader, vid))
            self.set_status("安装完成：%s" % vid)
            self.refresh_installed()
            self.home_version.set(vid)
            self.cfg["last_version"] = vid
            util.save_config(self.cfg)
            messagebox.showinfo("安装完成", "版本 %s 已就绪，可直接启动。" % vid)

        def err(e):
            self.forge_btn.configure(state="normal", text="安装所选加载器")
            self.log("%s 安装失败：%s" % (loader, e))
            self.set_status("安装失败")
            hint = ""
            if loader == "neoforge":
                hint = ("\n\n提示：NeoForge 安装器会自己访问 maven.neoforged.net 下载依赖，"
                        "该域名在部分网络下被污染，安装会卡在“下载依赖”阶段。"
                        "可以换网络 / 挂代理后重试，或改用 Forge / Fabric。")
            messagebox.showerror("安装失败", str(e) + hint)

        self.bg(work, done=done, err=err)

    def use_selected_version(self):
        sel = self.version_tree.focus()
        if not sel:
            return
        self.home_version.set(sel)
        self.install_pick.set(sel)
        self.cfg["last_version"] = sel
        util.save_config(self.cfg)
        self.log("启动版本已设为 %s" % sel)
        self.show_page("home")

    # ------------------------------------------------------------------ #
    # 模组 / 光影 / 资源包
    # ------------------------------------------------------------------ #
    def search_content(self, key):
        st = self.content[key]
        q = (st["query"].get() or "").strip()
        gv = (st["gv"].get() or "").strip()
        loader = ""
        if st["loader"] is not None:
            loader = (st["loader"].get() or "").strip().lower()
        self.set_status("搜索中…")
        tree = st["tree"]
        for item in tree.get_children():
            tree.delete(item)

        def work():
            return modrinth.search(q, st["ptype"], loader or None, gv or None, limit=30)

        def done(res):
            hits, total = res
            st["hits"] = {h["project_id"]: h for h in hits}
            for h in hits:
                desc = (h.get("description") or "").replace("\n", " ")[:90]
                tree.insert("", "end", iid=h["project_id"],
                            values=(h.get("title"), h.get("author"), "{:,}".format(h.get("downloads", 0)), desc))
            self.set_status("找到 %d 个结果（共 %s）" % (len(hits), total))
            self.log("搜索 %s：%s 个结果" % (st["ptype"], total))

        def err(e):
            self.set_status("搜索失败")
            self.log("搜索失败：%s" % e)

        self.bg(work, done=done, err=err)

    def prefetch_content(self):
        """联网后立刻预取热门内容列表，点开页面不用等"""
        if getattr(self, "_pref_running", False) or getattr(self, "_pref_done", False):
            return
        self._pref_running = True
        targets = [("mods", "mod"), ("shaders", "shader"), ("packs", "resourcepack")]

        def work():
            out = {}
            for key, ptype in targets:
                try:
                    out[key] = modrinth.search("", ptype, None, None, limit=30, sort="downloads")
                except Exception:
                    continue
            return out

        def done(res):
            self._pref_running = False
            self._pref_done = True
            for key, (hits, total) in res.items():
                st = self.content.get(key)
                if not st:
                    continue
                st["hits"] = {h["project_id"]: h for h in hits}
                tree = st["tree"]
                if tree.get_children():
                    continue
                for h in hits:
                    desc = (h.get("description") or "").replace("\n", " ")[:90]
                    tree.insert("", "end", iid=h["project_id"],
                                values=(h.get("title"), h.get("author"),
                                        "{:,}".format(h.get("downloads", 0)), desc))
            total = sum(v[1] for v in res.values()) if res else 0
            self.log("已预取热门内容列表（共 %s 条候选）" % total)

        self.bg(work, done=done, err=lambda e: self.log("预取内容列表失败：%s" % e))

    def open_content_detail(self, key):
        """点击条目 → 解析 Modrinth 项目页网址 + 各版本文件直链"""
        st = self.content[key]
        sel = st["tree"].focus()
        if not sel:
            messagebox.showinfo("未选择内容", "先在列表里选中一个项目。")
            return
        hit = (st.get("hits") or {}).get(sel) or {}
        title = st["tree"].item(sel, "values")[0] or hit.get("title") or sel
        ptype = st["ptype"]
        slug = hit.get("slug") or sel
        page = modrinth.project_url(ptype, slug)
        gv = (st["gv"].get() or "").strip()
        loader = ""
        if st["loader"] is not None:
            loader = (st["loader"].get() or "").strip().lower()

        win = tk.Toplevel(self)
        win.title("下载页 · %s" % title)
        win.configure(bg=BG)
        win.geometry("920x600")
        win.transient(self)

        head = card(win)
        head.pack(fill="x", padx=14, pady=(14, 8))
        label(head, title, TXT, FONT_B).pack(anchor="w", padx=16, pady=(12, 2))
        label(head, "项目页：%s" % page, ACC, FONT_S).pack(anchor="w", padx=16)
        row = tk.Frame(head, bg=CARD)
        row.pack(fill="x", padx=16, pady=(8, 12))
        button(row, "打开项目页", lambda: webbrowser.open(page), "primary").pack(side="left")
        button(row, "复制项目页", lambda: self._copy(page), "ghost").pack(side="left", padx=8)

        tree_wrap, vtree = scrollable_tree(win, ("版本", "游戏版本", "加载器", "文件", "直链"),
                                           (120, 120, 90, 200, 360), height=12)
        tree_wrap.pack(fill="both", expand=True, padx=14)

        foot = tk.Frame(win, bg=BG)
        foot.pack(fill="x", padx=14, pady=(8, 14))
        vstat = label(foot, "正在获取版本与直链…", SUB, FONT_S, bg=BG)
        vstat.pack(side="right", padx=8)
        files = {}

        def copy_link():
            fid = vtree.focus()
            if not fid or fid not in files:
                messagebox.showinfo("未选择版本", "先在列表里选中一个版本。")
                return
            self._copy(files[fid])
            vstat.configure(text="已复制直链")

        def download_link():
            fid = vtree.focus()
            if not fid or fid not in files:
                messagebox.showinfo("未选择版本", "先在列表里选中一个版本。")
                return
            folder = os.path.join(self.cfg["game_dir"], st["folder"])
            url = files[fid]
            name = os.path.basename(urllib.parse.urlparse(url).path) or ("%s.jar" % fid)

            def work():
                os.makedirs(folder, exist_ok=True)
                return util.download_file(url, os.path.join(folder, name),
                                          desc=os.path.basename(name))

            def done(path):
                self.log("已下载直链文件：%s" % path)
                vstat.configure(text="已保存：%s" % os.path.basename(path))

            self.bg(work, done=done, err=lambda e: vstat.configure(text="下载失败：%s" % e))

        button(foot, "下载选中直链", download_link, "primary").pack(side="left")
        button(foot, "复制直链", copy_link, "ghost").pack(side="left", padx=8)

        def work():
            return modrinth.get_versions(sel, gv or None, loader or None)

        def done(versions):
            if not versions:
                vstat.configure(text="该项目没有符合当前筛选的版本")
                return
            for v in versions[:40]:
                f = modrinth.primary_file(v) or {}
                url = f.get("url") or ""
                files[v.get("id")] = url
                vtree.insert("", "end", iid=v.get("id"),
                             values=(v.get("version_number"), ", ".join(v.get("game_versions") or [])[:22],
                                     ", ".join(v.get("loaders") or [])[:16],
                                     f.get("filename") or "", url))
            vstat.configure(text="共 %d 个版本，双击条目可复制直链" % len(versions))
            vtree.bind("<Double-1>", lambda e: copy_link())

        self.bg(work, done=done, err=lambda e: vstat.configure(text="获取版本失败：%s" % e))

    def _copy(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.log("已复制：%s" % text)
        except Exception as e:
            self.log("复制失败：%s" % e)

    def _version_loader_base(self, vid):
        """返回 (加载器, 原版基础版本)"""
        vdir = os.path.join(self.cfg["game_dir"], "versions")
        vj = util.read_json(os.path.join(vdir, vid, vid + ".json"), {}) or {}
        loader = forge.detect_loader(dict(vj, id=vid))
        base = vid
        cur = vj
        guard = 0
        while cur.get("inheritsFrom") and guard < 6:
            base = cur["inheritsFrom"]
            cur = util.read_json(os.path.join(vdir, base, base + ".json"), {}) or {}
            guard += 1
        return loader, base

    def install_shader_support(self):
        vid = (self.shader_ver.get() or "").strip()
        if not vid:
            messagebox.showinfo("选择版本", "先选择要安装光影前置的游戏版本。")
            return
        try:
            loader, mc = self._version_loader_base(vid)
        except Exception as e:
            messagebox.showerror("读取版本失败", str(e))
            return
        targets = {
            "fabric": [("iris", "fabric"), ("sodium", "fabric")],
            "quilt": [("iris", "quilt"), ("sodium", "quilt")],
            "forge": [("oculus", "forge"), ("embeddium", "forge")],
            "neoforge": [("iris", "neoforge")],
        }.get(loader)
        if not targets:
            messagebox.showinfo("原版不能直接装光影",
                                "原版请先安装 Fabric（推荐）或 Forge，再回来装光影前置。")
            return
        self.shader_btn.configure(state="disabled", text="安装中…")
        mods_dir = os.path.join(self.cfg["game_dir"], "mods")
        self.log("为 %s（%s，%s）安装光影前置" % (vid, loader, mc))

        def work():
            saved = []
            for pid, ldr in targets:
                try:
                    saved += modrinth.download_project(pid, mods_dir, mc, ldr,
                                                       status=lambda s: self.status_cb(s))
                except Exception as e:
                    self.post(lambda e=e, pid=pid: self.log("安装 %s 失败：%s" % (pid, e)))
            return saved

        def done(saved):
            self.shader_btn.configure(state="normal", text="安装光影前置")
            self.log("光影前置完成，共 %d 个文件" % len(saved))
            self.set_status("光影前置已安装")
            messagebox.showinfo("安装完成",
                                "已安装 %d 个文件到 mods。\n启动游戏后在 选项 → 视频设置 → 光影 中选择光影包。"
                                % len(saved))

        def err(e):
            self.shader_btn.configure(state="normal", text="安装光影前置")
            self.log("光影前置安装失败：%s" % e)
            messagebox.showerror("安装失败", str(e))

        self.bg(work, done=done, err=err)

    def download_content(self, key):
        st = self.content[key]
        sel = st["tree"].focus()
        if not sel:
            messagebox.showinfo("未选择内容", "先在列表里选中一个项目。")
            return
        title = st["tree"].item(sel, "values")[0]
        gv = (st["gv"].get() or "").strip()
        loader = ""
        if st["loader"] is not None:
            loader = (st["loader"].get() or "").strip().lower()
        folder = os.path.join(self.cfg["game_dir"], st["folder"])
        self.log("下载 %s → %s" % (title, folder))
        self.set_status("下载 %s…" % title)

        def work():
            return modrinth.download_project(sel, folder, gv or None, loader or None,
                                             status=lambda s: self.status_cb(s))

        def done(saved):
            for name, path in saved:
                self.log("已下载：%s" % os.path.basename(path))
            self.set_status("下载完成：%s" % title)
            messagebox.showinfo("下载完成", "已保存 %d 个文件到：\n%s" % (len(saved), folder))

        def err(e):
            self.set_status("下载失败")
            self.log("下载失败：%s" % e)
            messagebox.showerror("下载失败", str(e))

        self.bg(work, done=done, err=err)

    # ------------------------------------------------------------------ #
    # 基岩版
    # ------------------------------------------------------------------ #
    def detect_bedrock(self):
        self.home_bedrock_status.configure(text="正在检测…", fg=SUB)
        if hasattr(self, "bedrock_status"):
            self.bedrock_status.configure(text="正在检测…", fg=SUB)

        def done(clients):
            self.clients = clients or []
            if hasattr(self, "bc_pick"):
                self.bc_map = {}
                labels = []
                for c in self.clients:
                    tag = c.get("version") or ""
                    if c.get("preview") or "Preview" in (c.get("name") or ""):
                        tag += " 预览版"
                    lb = "%s  %s" % (c.get("label") or c.get("name") or "Minecraft", tag)
                    labels.append(lb)
                    self.bc_map[lb] = c
                self.bc_pick.configure(values=labels)
                if labels and self.bc_pick.current() < 0:
                    self.bc_pick.current(0)
            if self.clients:
                text = "已安装 %d 个客户端：%s" % (
                    len(self.clients),
                    "、".join("%s %s" % (c["name"], c.get("version", "")) for c in self.clients[:3]),
                )
                self.home_bedrock_status.configure(text=text, fg=TXT)
                if hasattr(self, "bedrock_status"):
                    self.bedrock_status.configure(text="检测完成，可在下拉框里选择要启动的客户端。", fg=TXT)
            else:
                text = "未检测到基岩版客户端"
                self.home_bedrock_status.configure(text=text, fg=SUB)
                if hasattr(self, "bedrock_status"):
                    self.bedrock_status.configure(
                        text="%s。基岩版需要先通过 Microsoft Store 安装（系统自带商店，账号与购买需自行确认）。"
                             % text, fg=SUB)
                self.clients = []

        self.bg(lambda: bedrock.installed_clients(), done=done,
                err=lambda e: self.log("基岩版检测失败：%s" % e))

    def launch_bedrock_home(self):
        self.launch_bedrock_page()

    def launch_bedrock_page(self):
        clients = getattr(self, "clients", [])
        pick = None
        if hasattr(self, "bc_pick") and getattr(self, "bc_map", None):
            pick = self.bc_map.get(self.bc_pick.get())
        if pick is None:
            pick = clients[0] if clients else None
        pfn = pick["pfn"] if pick else None
        try:
            way = bedrock.launch_client(pfn)
            self.log("正在启动基岩版（%s）" % ("AppsFolder" if way == "appsFolder" else "minecraft:// 协议"))
            self.set_status("已请求启动基岩版")
        except Exception as e:
            self.log("启动基岩版失败：%s" % e)
            messagebox.showerror("启动失败",
                                 "无法启动基岩版：%s\n请确认已安装 Minecraft（Windows 版）。" % e)

    def open_store(self):
        try:
            os.startfile("ms-windows-store://pdp/?productid=9NBLGGH2JHXJ")
        except Exception as e:
            self.log("打开商店失败：%s" % e)

    def download_bds_selected(self):
        idx = self.bv_pick.current()
        if idx < 0 or not getattr(self, "bds_versions", None):
            messagebox.showinfo("请选择版本", "先刷新并选择一个服务端版本。")
            return
        info = self.bds_versions[idx]
        self._start_bds_download(info["version"], info["url"], info["filename"])

    def download_bds_manual(self):
        ver = (self.bv_manual.get() or "").strip()
        if not ver:
            messagebox.showinfo("请输入版本号", "例如：1.26.66.1")
            return
        self.bv_status.configure(text="校验版本 %s 是否存在…" % ver, fg=SUB)

        def work():
            url, fname, size = bedrock.probe_version(ver)
            return {"version": ver, "url": url, "filename": fname, "size": size}

        def done(info):
            self.bv_status.configure(
                text="找到版本 %s（%s）" % (info["version"], util.human_size(info["size"])), fg=TXT)
            self._start_bds_download(info["version"], info["url"], info["filename"])

        def err(e):
            self.bv_status.configure(text="校验失败：%s" % e, fg=SUB)
            self.log("版本校验失败：%s" % e)
            messagebox.showerror("没有该版本", str(e))

        self.bg(work, done=done, err=err)

    def _start_bds_download(self, version, url, filename):
        self.set_status("下载基岩版服务端 %s…" % version)
        self.bv_status.configure(text="开始下载 %s" % version, fg=TXT)

        def work():
            return bedrock.download_server_version(
                version, url, filename,
                status=lambda s: self.status_cb(s),
                progress=lambda f: self.progress_cb(f),
            )

        def done(res):
            exe, ver = res
            self.log("基岩版服务端 %s 已就绪：%s" % (ver, os.path.dirname(exe)))
            self.bv_status.configure(text="已就绪：%s" % ver, fg=TXT)
            self.set_status("基岩版服务端就绪")
            self.refresh_bds_installed()

        def err(e):
            self.bv_status.configure(text="下载失败：%s" % e, fg=SUB)
            self.log("基岩版服务端下载失败：%s" % e)
            messagebox.showerror("下载失败", str(e))

        self.bg(work, done=done, err=err)

    def refresh_bds_versions(self):
        self.bv_status.configure(text="正在读取官方版本列表…", fg=SUB)

        def done(items):
            self.bds_versions = items
            values = ["%s（%s）" % (i["version"], i["kind"]) for i in items]
            self.bv_pick.configure(values=values)
            if values:
                self.bv_pick.current(0)
            self.bv_status.configure(
                text="官方列表：%d 个版本（正式版 / 预览版）" % len(items), fg=TXT)

        self.bg(bedrock.available_versions, done=done,
                err=lambda e: self.bv_status.configure(text="版本列表获取失败：%s" % e, fg=SUB))

    def refresh_bds_installed(self):
        items = bedrock.list_installed_servers()
        if not hasattr(self, "bds_tree"):
            return
        for iid in self.bds_tree.get_children():
            self.bds_tree.delete(iid)
        for it in items:
            self.bds_tree.insert("", "end", iid=it["path"], values=(it["version"], it["path"]))
        if items:
            self.bds_tree.selection_set(items[0]["path"])
            self.bds_tree.focus(items[0]["path"])
        self.bds_count.configure(text="已下载 %d 个服务端版本" % len(items))

    def run_bds_selected(self):
        sel = self.bds_tree.focus()
        if not sel:
            messagebox.showinfo("未选择", "先在列表里选中一个服务端版本。")
            return
        exe = os.path.join(sel, "bedrock_server.exe")
        if not os.path.isfile(exe):
            messagebox.showinfo("文件缺失", "该目录里没有 bedrock_server.exe。")
            return
        try:
            bedrock.run_server(exe)
            self.log("基岩版服务端已在新的控制台窗口启动：%s" % sel)
            self.set_status("BDS 运行中")
        except Exception as e:
            self.log("启动服务端失败：%s" % e)
            messagebox.showerror("启动失败", str(e))

    def remove_bds_selected(self):
        sel = self.bds_tree.focus()
        if not sel:
            return
        if not messagebox.askyesno("确认删除", "删除本地服务端目录：\n%s\n\n其中的世界存档也会一起删除。" % sel):
            return
        bedrock.remove_server(sel)
        self.log("已删除服务端：%s" % sel)
        self.refresh_bds_installed()

    # ------------------------------------------------------------------ #
    # 设置
    # ------------------------------------------------------------------ #
    def choose_game_dir(self):
        path = filedialog.askdirectory(initialdir=self.cfg["game_dir"], title="选择游戏目录")
        if path:
            self.set_dir.set(os.path.normpath(path))

    def save_settings(self):
        new_dir = (self.set_dir.get() or "").strip()
        if new_dir:
            self.cfg["game_dir"] = os.path.normpath(new_dir)
            os.makedirs(self.cfg["game_dir"], exist_ok=True)
            self.header_dir.configure(text="游戏目录：%s" % self.cfg["game_dir"])
            self.fabric_note.configure(text="将安装到：%s" % self.cfg["game_dir"])
        try:
            self.cfg["memory_mb"] = max(1024, int(self.set_mem.get()))
        except Exception:
            pass
        self.cfg["username"] = (self.set_user.get() or "Steve").strip() or "Steve"
        try:
            self.cfg["width"] = max(320, int(self.set_w.get()))
            self.cfg["height"] = max(240, int(self.set_h.get()))
        except Exception:
            pass
        idx = self.set_java.current()
        if idx > 0 and idx - 1 < len(self.java_list):
            self.cfg["java_path"] = self.java_list[idx - 1]["path"]
        else:
            self.cfg["java_path"] = ""
        util.save_config(self.cfg)
        self.home_user.set(self.cfg["username"])
        self.home_mem.set(str(self.cfg["memory_mb"]))
        self.log("设置已保存（Java：%s）" % (self.cfg["java_path"] or "自动"))
        self.set_status("设置已保存")
        self.refresh_installed()

    def download_java(self, major):
        self.set_status("下载 Java %s…" % major)

        def work():
            return javamod.download_jdk(major, status=lambda s: self.status_cb(s),
                                        progress=lambda f: self.progress_cb(f))

        def done(path):
            self.log("Java %s 已就绪：%s" % (major, path))
            self.set_status("Java %s 已就绪" % major)
            self.refresh_java()

        self.bg(work, done=done, err=lambda e: (self.log("Java 下载失败：%s" % e),
                                                 messagebox.showerror("Java 下载失败", str(e))))

    # ------------------------------------------------------------------ #
    def open_game_dir(self):
        util.open_path(self.cfg["game_dir"])

    def _on_close(self):
        util.save_config(self.cfg)
        if getattr(self, "tunnel_proc", None):
            try:
                tunnel.stop_bore(self.tunnel_proc)
            except Exception:
                pass
        self.destroy()
