# 参与开发

先通过 issue 描述问题或提出改进。修改时使用独立分支，完成相关验证后提交非草稿 PR；不要直接推送或主动合并到 `main`。

运行源码位于 `prototype/`。Skill 内的 `scripts/` 是生成副本，修改源码或 Skill 内容后重新构建，不分别维护两份实现：

```bash
python3 scripts/package_skill.py
python3 -m unittest discover -s tests -v
```

测试使用临时 Git 仓库与模拟传输，不需要 GitHub 凭据或模型服务。对真实工具或 GitHub 的联调需明确选择测试仓库，并保留精确版本与实际执行证据；不要把模拟测试描述为真人审核或真实外部 AI 执行。

请保持 `LICENSE` 与 Skill 内的许可证一致，不提交凭据、个人运行日志或工作状态目录。新增能力应有针对实际行为的检查，特别是版本绑定、旧候选拒绝和原工作目录保留。
