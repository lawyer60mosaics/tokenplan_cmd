# Sources and integration boundaries

TokenPlan CMD uses Zellij's command-pane layout protocol. The direct CMD renderer
is implemented in this repository. It is not a renamed copy of the Zellij core.

The optional `vendor/zellij` Git submodule pins upstream commit
`519a23715c6b0f65a3ffada64e738ed6ec9380fc` from
https://github.com/zellij-org/zellij. Zellij is MIT licensed, copyright 2020 Zellij
contributors; its original license remains in the submodule. No upstream code
has been modified by this project.

Protocol references, consulted 2026-10-16:

- Codex account limits: https://github.com/openai/codex/tree/main/codex-rs/app-server
- Claude Code OAuth usage (internal endpoint, not a public API stability promise):
  https://github.com/anthropics/claude-code/issues/31021
- Antigravity built-in usage command:
  https://antigravity.google/docs/cli/commands/usage
  https://github.com/google-antigravity/antigravity-cli/issues/1045
  Reads structured groups/buckets from the local agy CLI; credentials remain managed by agy.
- Gemini Code Assist quota contract (optional legacy backend):
  https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/code_assist/types.ts
  and `server.ts` in the same directory. The implementation is independent; no
  Google source or embedded OAuth client secret is copied into this repository.
  OAuth app metadata is read locally from the user's installed official CLI.
- DeepSeek balance: https://api-docs.deepseek.com/api/get-user-balance/
- Volcengine usage CLI: https://github.com/volcengine/ark-cli

Provider names and trademarks belong to their respective owners. This project
is not an official product from any provider.
