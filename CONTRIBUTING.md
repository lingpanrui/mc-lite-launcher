# 参与开发

## 环境

- Windows 10/11
- Python 3.10+（只用标准库，不需要 pip 装依赖）
- 打包 exe 时额外需要 `pyinstaller`

```powershell
python 启动.bat
python selftest.py          # 接口连通性自检
python selftest.py --install 1.20.1   # 真实安装一个版本
```

## 代码风格

- 只用 Python 标准库（`tkinter`、`urllib`、`zipfile`…），不要引入第三方依赖，
  这是“单文件免依赖 exe”的前提。
- 网络请求统一走 `mclite/util.py` 的 `http_json` / `download_file`，
  这样断点、超时、User-Agent、镜像兜底只维护一处。
- 长耗时任务放到后台线程，UI 更新一律通过 `App.post / bg` 回主线程，不要直接跨线程改控件。
- 新页面用 `self._new_page(key, 标题, 副标题)`，返回的 `inner` 已经带滚动容器，
  内容再高也不会被截断。

## 提交

1. Fork 本仓库，新建分支：`feat/xxx`、`fix/xxx`
2. 改动尽量聚焦一个主题，提交信息用中文或英文都行，写清“做了什么/为什么”
3. 提 PR 前跑一遍 `python -m compileall mclite main.py` 和 `selftest.py`

## 特别欢迎的方向

- 基岩版客户端启动的兼容性（不同商店版本、预览版）
- 外置登录站点的兼容（不同 authlib-injector 实现）
- 下载失败重试 / 镜像策略
- 界面细节与高 DPI 适配
