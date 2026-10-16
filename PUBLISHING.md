# 发布到 npm

GitHub 保存源代码，npm 保存供用户安装的版本包。本仓库的 `build.yml` 已提供构建、安装验证、GitHub Release 和 npm 自动发布。

## 首次设置（仅一次）

1. 在 https://www.npmjs.com/signup 注册自己的账号，验证邮箱并启用双因素认证。GitHub 账号授权不等于 npm 发布授权。
2. 在 Windows CMD 登录，下载已经测试过的安装包，完成首次发布：

   ```cmd
   npm login --registry=https://registry.npmjs.org/
   curl.exe -fL https://github.com/lawyer60mosaics/tokenplan_cmd/releases/download/v1.2.0/tokenplan-cmd-1.2.0.tgz -o tokenplan-cmd-1.2.0.tgz
   npm publish .\tokenplan-cmd-1.2.0.tgz --access public --ignore-scripts --registry=https://registry.npmjs.org/
   ```

   按浏览器和终端提示完成登录、2FA。包名需可用且你具有发布权限；如果被占用，需要先统一修改 package.json、工作流和文档中的名称，或使用自己的 `@用户名/tokenplan-cmd`。不要将密码、验证码或 npm Token 提交到 GitHub。
3. 在 npm 的 `tokenplan-cmd` 包页面打开 **Settings → Trusted publishing → GitHub Actions**，填写：

   | 字段 | 内容 |
   | --- | --- |
   | Organization or user | `lawyer60mosaics` |
   | Repository | `tokenplan_cmd` |
   | Workflow filename | `build.yml` |
   | Environment name | 留空 |
   | Allowed actions | 允许直接 `npm publish` |

   无需在 GitHub Secrets 保存 npm Token。新建授权需在 2 天内成功发布一次，否则应删除过期配置并重新建立。
4. 在 GitHub 仓库 **Settings → Secrets and variables → Actions → Variables → New repository variable** 添加 `NPM_PUBLISH_ENABLED`，值为 `true`。未开启时构建和 GitHub Release 照常运行，npm 发布步骤跳过。

## 后续更新

普通代码 push 自动测试。准备公开新版时，更新以下版本号为同一个尚未发布的版本（例如 `1.2.1`）：

- `package.json` 中的 version。
- `app.py` 中的 VERSION。
- `pyproject.toml` 中的 version。
- `installer/xcli.iss` 中的 AppVersion。
- README.md 和 RELEASE_NOTES.md 中的版本、下载链接和更新说明。

提交代码后推送相同版本标签，在仓库目录执行：

```cmd
git add package.json app.py pyproject.toml installer/xcli.iss README.md RELEASE_NOTES.md
git commit -m "release: 1.2.1"
git push origin feat/tokenplan-cmd
git tag -a v1.2.1 -m "XCLI 1.2.1"
git push origin v1.2.1
```

其他功能改动应先提交。标签必须指向包含改动和版本号的提交。Actions 将构建 Windows 程序、打 npm 包、测试安装、生成 Release，再通过 npm OIDC 授权发布该版本；没有每次手动打包或输入 npm Token 的步骤。发布工作流会核对标签与包版本。

npm 不允许覆盖已发布的同一版本。发布失败时查看 Actions 的 Publish to npm 日志；如果该版本尚未在 npm 发布，可重新运行失败的 job。已经发布则必须增加新版本，不要移动旧标签。

## 其他人安装与升级

首次成功发布到 npm 后，Windows x64 用户可以执行：

```cmd
npm install -g tokenplan-cmd
xcli
xcli --configure
```

升级：

```cmd
npm install -g tokenplan-cmd@latest
```

你推送新版不会自动替换用户本机程序，用户执行升级命令后生效。账号登录与配置保留在各用户本机，不随 npm 包分发。

参考：[npm 首次发布](https://docs.npmjs.com/creating-and-publishing-unscoped-public-packages/)、[npm Trusted publishing](https://docs.npmjs.com/trusted-publishers/)。
