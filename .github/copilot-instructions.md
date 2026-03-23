# Copilot Instructions

## Markdown Documentation Language Rule

When generating Markdown files intended for AI reading, if the primary content is in English, you must also provide paired Chinese translation or Chinese annotations for readability.

中文说明：当生成给 AI 读取的 Markdown 文件时，若正文主要为英文，必须同时提供配套中文翻译或中文注释，方便阅读与校对。

## Enforcement Notes

- This rule applies to newly created Markdown docs and major rewrites.
- Chinese-only Markdown docs do not require extra translation.
- Prefer section-by-section bilingual structure for clarity.

中文说明：
- 本规则适用于新建 Markdown 文档及大幅改写场景。
- 若文档本身主要为中文，则无需额外翻译。
- 优先采用“分段英文 + 对应中文”的结构，便于阅读。
## Autopilot Worktree & Output Rule

- In autopilot-style sessions, make code changes only in branch `feature/ai-develop` under `.worktrees/ai-develop`; do not modify the main branch working directory directly.
- Use milestone commits. Commit messages must be Chinese and include the reason for the change.
- At delivery time, output only merge strategy and commands; do not auto-run merge commands.

中文说明：
- 在 autopilot 模式下，仅允许在 `.worktrees/ai-develop` 的 `feature/ai-develop` 分支修改代码，禁止直接改 main 工作目录。
- 按里程碑提交，提交信息必须为中文且包含“变更原因”。
- 交付时仅输出合并方案与命令，不自动执行合并。