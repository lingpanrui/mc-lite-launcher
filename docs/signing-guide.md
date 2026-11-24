# 签名与分发完整步骤

本文档对应仓库当前的签名方案，分两块：**Windows exe（自签名证书）** 与 **Android APK（固定 release keystore）**。

## 0. 现状速查

| 项目 | 值 |
| --- | --- |
| exe 签名证书主体 | `CN=MCLite Self-Signed, O=MCLite, C=CN` |
| exe 证书指纹（SHA-1） | `A382880EE6D964E45D8410303303C373415060B3` |
| exe 证书有效期 | 5 年（至 2031-11-24） |
| 证书文件 | `dist/MCLite-selfsigned.cer`（只含公钥，可公开分发） |
| 私钥文件 | `.signing/codesign-selfsigned.pfx`（**禁止外传**，口令在 `.signing/credentials.txt`） |
| APK 签名证书主体 | `CN=MCLite, O=MCLite, C=CN` |
| APK 证书指纹（SHA-256） | `c03b83acde011eb8fe85bf77bf6936a4d074b0aaf2d0c9a3c50b918fea55c6eb` |
| APK 私钥 | `.signing/mclite-release.jks`（**禁止外传**），CI 侧存在 GitHub Actions Secrets 里 |

---

## 1. 本机启用（导入受信任）

两个存储都必须导：**根**决定证书链能否被信任，**受信任的发布者**决定 UAC 是否承认发布者。

```powershell
cd <项目目录>\dist

certutil -user -addstore -f Root .\MCLite-selfsigned.cer
certutil -user -addstore -f TrustedPublisher .\MCLite-selfsigned.cer
```

图形界面做法（不想用命令行时）：

1. 双击 `MCLite-selfsigned.cer` → 点「安装证书」
2. 存储位置选「当前用户」→「下一步」
3. 选「将所有的证书都放入下列存储」→ 浏览 → **受信任的根证书颁发机构** → 确定 → 完成
4. 重复一次第 1~3 步，这次存储选 **受信任的发布者**
5. 出现「安全警告」时点「是」

## 2. 验证签名

```powershell
cd <项目目录>
Get-AuthenticodeSignature .\dist\MCLite.exe |
  Select-Object Status, StatusMessage, @{n='Signer';e={$_.SignerCertificate.Subject}}
```

期望输出：

```
Status        : Valid
StatusMessage : Signature verified.
Signer        : CN=MCLite Self-Signed, O=MCLite, C=CN
```

导入前是 `UnknownError`（"证书链在不受信任的根终止"），导入后变 `Valid`，这就是唯一判据。

图形界面确认：右键 `MCLite.exe` → 属性 → 「数字签名」标签 → 签名者列表里能看到 `MCLite Self-Signed`，选中后点「详细信息」→「查看证书」。

## 3. 分发给别人

对方电脑第一次双击仍会提示「未知发布者」，因为他的系统没有你的根证书。让他做一次第 1 步即可（把 `MCLite-selfsigned.cer` 和 exe 一起发过去）。

对方只需要命令版：

```powershell
certutil -user -addstore -f Root .\MCLite-selfsigned.cer
certutil -user -addstore -f TrustedPublisher .\MCLite-selfsigned.cer
```

> 这一步是对方在自己的机器上主动信任你的证书，等于"你告诉他的系统：这个发布者是我"。
> 如果他不想改系统信任，那就只能每次点「仍要运行」，这没法绕开。

## 4. 重新构建 exe 之后

签名是**按文件内容**算的，重新打包后 hash 变了，必须重新签：

```powershell
cd <项目目录>

# 1) 打包（会覆盖 dist/MCLite.exe，签名随之丢失）
python -m PyInstaller --noconfirm --clean --onefile --windowed --name MCLite main.py

# 2) 用同一张证书重新签名
$cert = Get-Item 'Cert:\CurrentUser\My\A382880EE6D964E45D8410303303C373415060B3'
Set-AuthenticodeSignature -FilePath .\dist\MCLite.exe -Certificate $cert `
  -TimestampServer "http://timestamp.digicert.com" -HashAlgorithm SHA256

# 3) 重新计算校验值
$h = (Get-FileHash .\dist\MCLite.exe -Algorithm SHA256).Hash.ToLower()
"MCLite.exe  $h" | Set-Content .\dist\SHA256SUMS.txt -Encoding ascii
```

如果换电脑打包（新机器上没有这张证书），先把 `.signing/codesign-selfsigned.pfx` 导入：

```powershell
Import-PfxCertificate -FilePath .\signing\codesign-selfsigned.pfx `
  -CertStoreLocation Cert:\CurrentUser\My -Password (ConvertTo-SecureString "<口令>" -AsPlainText -Force)
```

## 5. 凭据保管

- `.signing/` 已在 `.gitignore` 里，不会被提交；**不要**用聊天工具、网盘公开链接传私钥。
- 建议把 `.signing/` 整个目录加密备份一份（U 盘 / 本地加密盘都行）。丢失后果：
  - exe：旧签名失效，只能重新签发新证书并让所有人重新导入（可接受）；
  - APK：**无法再覆盖升级**，只能卸载重装（影响较大）。
- APK 的 keystore 已存 GitHub Actions Secrets，只要仓库还在，CI 就能持续签出一致的包。

## 6. 撤销信任

```powershell
certutil -user -delstore Root A382880EE6D964E45D8410303303C373415060B3
certutil -user -delstore TrustedPublisher A382880EE6D964E45D8410303303C373415060B3
```

撤销后 exe 仍带签名，但本机又会显示「未知发布者」。

## 7. 想做到"别人下载不弹窗"还差什么

自签名证书的根永远不会被别人的系统天然信任，所以只有两条路：

1. **商业 OV/EV 代码签名证书**（付费，需企业资质 + 硬件令牌；EV 可立刻获得 SmartScreen 信誉）。
2. **[SignPath Foundation](https://signpath.org/) 开源项目赞助签名**（免费，需提交项目审核；本项目满足"公开仓库 + MIT + 公开 CI 构建"的基础条件）。注意 `app.signpath.io` 控制台走的是"自带证书"流程，那条路仍要你自己有证书，赞助申请是独立入口。

审核通过后，把 Organization ID、Project slug、Signing policy slug、API token 放进 GitHub Secrets，在 `.github/workflows/build.yml` 里加一步 `signpath/github-action-submit-signing-request` 即可自动签名，无需人工干预。
