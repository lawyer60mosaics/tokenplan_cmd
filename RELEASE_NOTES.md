XCLI 1.2.0

- Windows 用户级安装程序，安装后重新打开 CMD 输入 xcli 即可进入看板。
- 配置中心支持 agy / Gemini CLI 切换与 CLI 路径设置。
- Antigravity 直接读取内置 /usage 的每周、5 小时分组共享额度和重置时间。
- 支持本地 arkcli、独立面板定时刷新与显示数量设置。
- 配置保存在用户目录，覆盖升级和卸载保留配置。

下载 XCLI-1.2.0-Setup-x64.exe 安装。需要先安装并登录对应平台的官方 CLI。

支持 npm 全局安装：

```cmd
npm install -g https://github.com/lawyer60mosaics/tokenplan_cmd/releases/download/v1.2.0/tokenplan-cmd-1.2.0.tgz
xcli
```

包内置 Windows x64 程序，无需 Python 或额外下载。尚未发布 npm 官方仓库。
