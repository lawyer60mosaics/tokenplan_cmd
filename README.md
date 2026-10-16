# XCLI / TokenPlan CMD 1.1.0

Windows CMD 多 AI 额度看板。可在一个终端显示 1–50 个面板，为每个面板配置独立刷新间隔、显示开关和数据源。

## Windows 安装

运行 `XCLI-1.1.0-Setup-x64.exe`，安装到当前用户目录，无需管理员权限。安装完成后重新打开 CMD，输入：

```cmd
xcli
xcli --configure
xcli --version
```

安装器添加用户 PATH，支持系统“已安装的应用”卸载与覆盖升级。配置保存在 `%APPDATA%\XCLI\config.json`，升级和卸载保留配置。旧版配置可通过 `xcli --config "旧目录\config.json"` 继续使用；外部快照路径相对于所选配置文件。

## Antigravity / Gemini 优先接入

先安装并登录官方 [Antigravity agy CLI](https://antigravity.google/docs/cli/install/)。配置中心选择 Antigravity / Gemini，J 选择 `agy`，E 可指定 `agy.exe`，T 检查连接。

程序调用 `agy --print /usage --output-format json --print-timeout 30s`，读取内置额度命令，不发送模型问题。需要支持该结构化命令的新版 agy（本机验证 1.3.6）。显示每周和 5 小时剩余百分比及 UTC 重置时间；组内模型共享额度，不等于每个模型独立余额。模型/账户标识填 `account` 显示全部分组，填 `Gemini` 或 `Claude` 筛选分组。Antigravity 中 Claude/GPT 分组不代表独立 Claude 订阅账户。

J 选择 `gemini` 可使用旧版 Gemini CLI / Code Assist 适配器，其 A/G/O 配置只在旧数据源显示。

## 操作

C 打开配置中心，V 选择显示面板，Enter 查看完整详情，PgUp/PgDn 翻页，R 手动刷新，Q 退出。配置中心可添加、删除面板、设置刷新间隔、暂停刷新、指定 CLI 路径并检查连接。

```cmd
xcli --demo
xcli --once --json
xcli --panel gemini --once
```

Codex 读取本地官方 CLI 账号额度；Claude 读取 Claude Code 订阅 OAuth；DeepSeek 在配置页 K 保存 API Key 到 Windows 凭据管理器；火山方舟使用本地 `arkcli`，配置 Profile、查询范围和最近天数。默认 mine 范围，Root 账号需自行明确选择 account 或使用子用户。方舟 API 用量与资源包额度不等于现金余额，统计可能延迟。未登录、无权限、服务不提供额度时明确显示未知，绝不伪造余额。

安装器只安装 XCLI；各平台 CLI 需自行安装登录。账号密钥不会写入仓库或面板配置文件。

## 从源码运行与打包

```cmd
py -3 app.py
py -3 -m unittest discover -s tests -v
py -3 -m pip install pyinstaller==6.20.0
py -3 -m PyInstaller --noconfirm --onefile --console --name xcli --add-data "zellij.kdl;." app.py
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\xcli.iss
```

Windows/Linux Python 3.10+。依赖仅标准库；打包使用 PyInstaller，安装器使用 Inno Setup 6。GitHub Actions 在版本标签推送时生成安装器与免安装包。

## Zellij 集成

保留上游 Zellij 子模块及许可证，使用 `git submodule update --init` 获取源代码。CMD 看板可原生运行；可选安装或编译 Zellij 后执行 `xcli --zellij`，或 `xcli --layout quota-layout.kdl` 导出分屏布局。XCLI 自有代码与上游代码的关系见 NOTICE.md。
