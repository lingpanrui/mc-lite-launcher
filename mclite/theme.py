# -*- coding: utf-8 -*-
"""主题系统：深色 / 浅色 / 跟随系统 + 多强调色

颜色键与 ui_v2 里的模块常量同名，App 启动与切换时把返回值写回模块全局，
已存在的控件在 rebuild() 后重绘，实现运行时换肤。
"""

# 每个主题：底色 → 卡片 → 文字，全部按 5 级灰阶排好，避免色块打架
PALETTES = {
    "dark": {
        "BG": "#0f1115",
        "SIDEBAR": "#121419",
        "SIDEBAR_ON": "#181d26",
        "CARD": "#171a20",
        "CARD2": "#1d222b",
        "CARD3": "#252c38",
        "LINE": "#2a303b",
        "TXT": "#e9edf4",
        "SUB": "#8b93a3",
        "DIM": "#5f6878",
        "WARN": "#f0b429",
        "DANGER": "#e06c75",
    },
    # 参考 BlockHelm 的 Fluent 浅色：灰底 + 纯白卡片 + 蓝灰文字
    "light": {
        "BG": "#f2f4f7",
        "SIDEBAR": "#e9ecf2",
        "SIDEBAR_ON": "#dde2ec",
        "CARD": "#ffffff",
        "CARD2": "#eef1f6",
        "CARD3": "#dfe4ee",
        "LINE": "#dde2ec",
        "TXT": "#14171d",
        "SUB": "#5b6472",
        "DIM": "#8b93a1",
        "WARN": "#c8860d",
        "DANGER": "#d0453f",
    },
    # 深蓝夜间版
    "midnight": {
        "BG": "#0f1420",
        "SIDEBAR": "#141a28",
        "SIDEBAR_ON": "#1b2334",
        "CARD": "#171f2e",
        "CARD2": "#1d2534",
        "CARD3": "#252e40",
        "LINE": "#2c3648",
        "TXT": "#e8edf6",
        "SUB": "#93a0b5",
        "DIM": "#66748a",
        "WARN": "#f0b429",
        "DANGER": "#e06c75",
    },
}

# 强调色：(主色, 按下色, 悬停色, 主色上的前景色)
ACCENTS = {
    "green": ("#3ddc84", "#2fb56e", "#57e796", "#08130c"),
    "blue": ("#4c8dff", "#3d76e0", "#6fa4ff", "#ffffff"),
    "purple": ("#a86bff", "#9155e6", "#bd8cff", "#ffffff"),
    "orange": ("#ff9f43", "#e6882f", "#ffb465", "#101318"),
}

# 浅色底上要压暗一档，否则绿字白底看不清
LIGHT_ACCENTS = {
    "green": ("#1a9d5b", "#158a4f", "#22b16a", "#ffffff"),
    "blue": ("#2f6fe0", "#275fc4", "#4a85ea", "#ffffff"),
    "purple": ("#7b45d6", "#6a3ac0", "#8f5ce0", "#ffffff"),
    "orange": ("#d97706", "#bf6905", "#e8890f", "#ffffff"),
}

THEME_NAMES = ["dark", "light", "midnight", "system"]


def system_dark():
    """读 Windows 的应用主题设置：True = 系统是深色"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(val) == 0
    except Exception:
        return True


def resolve(cfg):
    """返回实际主题名（system 会解析成 dark / light）"""
    name = (cfg or {}).get("theme") or "dark"
    if name == "system":
        return "light" if not system_dark() else "dark"
    if name not in PALETTES:
        return "dark"
    return name


def load(cfg):
    """取一套可用配色，键名与 ui_v2 的模块常量保持一致"""
    name = resolve(cfg)
    accent = (cfg or {}).get("accent") or "green"
    if accent not in ACCENTS:
        accent = "green"
    acc, acc2, acc_hover, on_acc = (LIGHT_ACCENTS if name == "light" else ACCENTS)[accent]

    th = dict(PALETTES[name])
    th.update(ACC=acc, ACC2=acc2, ACC_HOVER=acc_hover, ON_ACC=on_acc,
              NAME=name, ACCENT=accent)
    return th
