# TokenPlan CMD

在一个 CMD 窗口内查看 Codex、Claude、Gemini、DeepSeek 和火山方舟的用量与可获取的剩余额度。支持自选面板数量、多个账号／模型、定时刷新和终端配置界面。

## 启动

源码版需要 Windows 10/11 和 Python 3.10 以上，Python 运行时不需要第三方库。双击 `start.cmd`，或在本目录的 CMD 执行：

```bat
start.cmd
```

打包版直接运行 `tokenplan.exe`，不需要安装 Python。终端 80×24 可紧凑显示默认五个面板；放大到 120×40 可查看更多指标。过小窗口自动分页。

```bat
start-config.cmd
start.cmd --demo
start.cmd --once --json
```

`--demo` 不访问账户，所有示例数字明确标记 DEMO；演示模式中的修改不保存。正常模式不使用示例值填充未知额度。

## 配置界面

主界面按 **C**，或运行 `start-config.cmd`。所有常规操作均可在 CMD 中完成，无需编辑 JSON。

1. 输入已有面板编号编辑，或输入 **N** 添加同一平台的另一个账号／模型。
2. 设置名称、模型／账户标识、刷新间隔、是否显示和是否自动刷新。
3. 按 **H** 查看该平台接入说明，**L** 启动官方 CLI 登录，**T** 执行只读连接检查。
4. 根据平台填写账号路径、Profile、项目 ID 或密钥。只有适用字段才会显示。
5. **S** 保存当前面板并返回，**0** 取消当前编辑；配置中心输入 **0** 返回仪表盘，配置立即生效。

登录操作由用户输入 LOGIN 后启动官方 CLI，登录状态立即生效，不随取消面板编辑撤销。程序不会主动登录、扫描浏览器 Cookie、创建 API Key、切换 CLI 默认 Profile 或发起模型推理。

DeepSeek 的 Key 用 **K** 隐藏输入，保存到 Windows 凭据管理器，JSON 仅保存引用。可选的环境变量方式仍支持。取消编辑会删除本次暂存凭据，已保存的 Key 不回显。非 Windows 系统使用环境变量。

## 五个平台的接入和指标

| 平台 | 数据来源 | 可展示内容 | 配置要求与边界 |
| --- | --- | --- | --- |
| Codex | 官方 CLI `account/rateLimits/read` | 服务端返回的额度窗口、剩余百分比、重置时间、Credits | 先登录 Codex 订阅账号；模型共享账户额度时不拆成独立额度 |
| Claude | Claude Code OAuth usage | 5小时、7天和可用的模型周期百分比、重置时间 | Claude Code 订阅登录；读取 CLI 凭据文件。内部接口可能变更，API Key 不适用 |
| Gemini | 官方 CLI 使用的 Code Assist quota 协议 | 每个模型的剩余比例、可选剩余请求数和重置时间 | Gemini CLI Google 登录；这是 CLI/Code Assist 额度，不能代表 Gemini 网页聊天额度 |
| DeepSeek | 官方 `GET /user/balance` | 按币种显示账户金额余额 | API Key；此接口不返回模型 Token 用量 |
| 火山方舟 | 官方 `arkcli usage stats` / `usage balance --type free-quota` | 指定日期的 Token／请求数、模型免费额度与资源包剩余 | SSO 控制台权限；聚合用量延迟 5–30 分钟，资源额度不是人民币余额 |

### Codex

安装并登录官方 Codex CLI 后通常无需额外配置。不同账号可以指定独立的 Codex 状态目录和原生 CLI 程序路径。程序只查询当前账号额度，不切换默认登录。

### Claude 订阅

安装官方 Claude Code，在配置页选择 **L** 执行 `claude auth login`。默认凭据文件为 `~/.claude/.credentials.json`，可配置其他账号的文件。登录过期后在配置页重新登录并检查连接；不读取 Claude 桌面端或浏览器的加密存储。

模型标识填写 `account` 显示所有可用窗口；填写 `sonnet`、`opus` 等只筛选对应模型周期，仍会标明账户共享额度。接口只返回百分比时，不虚构 Token 上限。

### Gemini 订阅

安装官方 CLI：

```bat
npm install -g @google/gemini-cli
```

配置页 **L** 启动 CLI，在其中选择 Google 登录。登录完成后退出 CLI 返回配置页，按 **T** 检查。默认读取 `~/.gemini/oauth_creds.json`。模型标识填写 `account` 显示全部，或填写接口返回的精确模型 ID。

项目 ID 可自动通过 `loadCodeAssist` 发现；企业账号或权限不足时需要填写有权访问的 Google Cloud Project。程序不创建项目、不自动开通服务。

访问令牌过期时，利用本机官方 CLI 的 OAuth 应用元数据刷新并仅在内存缓存，不覆盖 CLI 凭据文件。元数据默认从 npm 安装目录查找，也可在配置页指定 `oauth2.js` 路径。仓库不包含 Google OAuth client secret。若 CLI 升级改变文件结构，界面会提示重新配置，不会悄悄使用其他账号。

### DeepSeek API

配置页选择 **K** 输入 Key，再按 **T** 验证。也可在同一个 CMD 中设置 `DEEPSEEK_API_KEY` 后启动；多账号使用不同环境变量名。已有凭据引用时优先从凭据管理器读取。环境变量修改需重启，配置页更新 Key 则保存后生效。

### 火山方舟 API

```bat
npm install -g @volcengine/ark-cli
```

配置页 **L** 启动官方 SSO 登录。API 推理 Key 不具备管理用量查询权限，因此不能仅凭一把推理 Key 获取整个平台余额。

- **Profile**：可以指定已存在的 CLI Profile；留空使用当前 Profile，程序不切换默认值。
- **查询范围**：默认 `mine`，按当前登录子用户的 Active Key 归集；`account` 是当前 Profile 的账号范围，可能包含团队其他人的用量，需在界面明确选择。
- **查询类型**：`usage` 是 API Token／请求数，`free_quota` 是免费额度／资源包，`both` 分开显示两者。
- **日期**：最近 1～31 天，使用 UTC+8 的自然日，默认今天。
- **模型**：`account` 查询所选范围的模型汇总；填写基础模型 ID 会传递模型过滤条件。语音模型的用量查询不在 arkcli 的支持范围。

Root 身份可能不支持 `mine`；失败时程序保留该范围并报告原因，不自动扩大到账号全量。统计、资源额度、Coding Plan 套餐和人民币账单是不同口径；本项目的方舟适配器只查询配置中选择的 API 统计／模型资源，不把它们当作 Coding Plan 额度或现金余额。分页或部分失败会显式标记，不输出伪完整的总量。

## 键盘

| 按键 | 操作 |
| --- | --- |
| C | 配置中心 |
| Enter / Esc | 打开／关闭当前面板的详情页；详情页用方向键、J/K 或 PgUp/PgDn 滚动 |
| V / 空格 | 打开面板显示列表／切换显示状态 |
| 方向键、Tab、J/K | 选择面板，必要时自动翻页 |
| R / A | 刷新当前／全部启用且未暂停的面板 |
| P | 暂停／恢复自动刷新 |
| + / - | 刷新间隔增减10秒 |
| Q / Ctrl+C | 退出 CMD 仪表盘 |

每个来源独立刷新，网络调用不会阻塞键盘和界面；同进程内相同来源请求合并，不重叠采集。Claude／方舟最小有效间隔60秒，默认300秒；其他来源默认60秒、最小10秒。平台限流时遵守 Retry-After 并退避，手动刷新也遵守请求间隔。失败保留上次数据并标记过期，凭据失效停止自动请求；重新登录或修改配置后可恢复。

刷新频率不代表上游数据实时性。界面区分数据时间和读取时间，不同单位与共享账户额度不会相加成一个“总剩余”。暂停、显示和间隔保存后重启恢复。退出时恢复终端屏幕，进行中的查询可能需要等待其超时结束；方舟单轮最多90秒。

## Zellij 分屏

CMD 直接模式使用本项目的终端渲染器；Zellij 模式使用上游命令面板机制。运行 `start-zellij.cmd` 或：

```bat
start.cmd --zellij
```

优先查找 PATH 中的 Zellij，然后查找应用旁的 `zellij.exe`、`vendor/zellij/target/debug/zellij.exe`。`Alt+H/J/K/L` 切换窗格，`Ctrl+X` 或 `Ctrl+Q` 退出整个会话。单面板内的 Q 只结束该窗格里的程序。配置在主界面或 `start-config.cmd` 修改后，重启分屏生效；分屏内刷新间隔的快捷调整为临时设置。

```bat
start.cmd --layout quota-layout.kdl
```

可单独导出布局。生成的布局含本机路径，迁移到其他机器或 WSL 后应在目标环境重新生成。Zellij 各窗格是独立进程，不跨进程合并账号请求。上游代码通过固定提交的 Git 子模块保留，详见 [NOTICE.md](NOTICE.md)。

构建可选的上游终端版：

```bat
git -c core.longpaths=true submodule update --init --depth 1
cd vendor\zellij
cargo +1.95 build -p zellij --locked --no-default-features
```

## 外部快照与迁移

所有平台都可在配置页按 **B** 切换为外部 JSON 快照。格式示例见 `snapshots/claude.example.json`。`provider` 和 `model` 必须与面板一致；`observed_at` 必须包含时区，指标支持可选的 `used`、`limit`、`remaining` 和 `resets_at`。仅在已知上限与已用量时计算剩余，缺失值显示未知。外部采集器应原子替换快照文件。

v1 配置会升级到 v2：尚未接入且没有实际文件的默认快照切换为内置采集器，自定义快照路径保留。配置与密钥不上传 Git。

## 开发与打包

```bat
py -3 -m unittest discover -s tests -v
py -3 -m compileall -q app.py quota tests
py -3 app.py --demo --once --json
```

测试包含五个平台的协议模拟、令牌过期、Google 令牌刷新缓存、0%/100%边界、模型过滤、方舟分页与范围、刷新调度、配置事务和 Windows 凭据管理器。带真实账号的连接检查需要用户在本机登录，模拟测试通过不代表所有账号均已实网验证。

```bat
py -3 -m pip install pyinstaller==6.20.0
py -3 -m PyInstaller --noconfirm --clean --onefile --console --name tokenplan --add-data "zellij.kdl;." app.py
```

产物是 `dist/tokenplan.exe`。GitHub Actions 在 Windows/Linux 和多个 Python 版本运行测试；手动触发 Windows executable 工作流或推送版本标签，可获得单文件 EXE 构建产物。Zellij 和各平台 CLI 仍是外部可选依赖，不嵌入 EXE。

Claude/Gemini 的订阅接口属于其 CLI 使用的内部协议，可能随平台更新改变；遇到不兼容时明确报错并保留旧值。使用前应遵守对应平台条款。许可证为 MIT。
