# 参与 Contrib Scout

欢迎提交可复现的 bug、测试案例和用户体验改进。范围较大的功能先开 issue 说明具体使用场景，避免重复实现。

1. 检查现有 issue / PR，说明当前版本、复现步骤、预期和实际结果。
2. 新建独立分支；一个 PR 解决一个清楚的问题。
3. 修改 TypeScript 后运行 `npm run build`，同时提交生成的 `contrib_scout/web/app.js`。
4. 运行 `python3 -m unittest discover -s tests -v`、`npm run check` 和 `git diff --check`。
5. 在 PR 中说明改动、原因、验证和边界。提交信息使用 Conventional Commits，例如 `fix: 修复关联 PR 检测遗漏`。

不要提交密钥、私有仓库内容或包含个人信息的调研报告。测试材料使用虚构数据或充分匿名化的案例，标明来源与授权。

允许使用 AI 辅助开发。提交者需要理解改动、检查生成内容、亲自验证，并在 PR 中说明 AI 辅助的范围。不要自动向其他仓库发送 issue、评论或 PR。
