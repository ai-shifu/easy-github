# 参与开发

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

先通过 issue 描述问题或提出改进。修改时使用独立分支，完成相关验证后提交非草稿 PR；不要直接推送或主动合并到 `main`。

## 语言约定

提问、讨论改动或与 AI 工具协作时，可以使用你习惯的语言。PR 标题、PR 描述和文档默认使用英文，方便不同语言背景的贡献者审查。

英文文档是维护基线。简体中文译本位于 `README.zh-CN.md`、`CONTRIBUTING.zh-CN.md`、`docs/zh-CN/` 和 `skills/easy-github/references/zh-CN/`。请保持语言切换和相对链接有效。修改行为或操作说明时，同时更新两种语言，保留一致的能力边界、验证要求和事实区分。

欢迎贡献更多语言的译本。沿用现有的 locale 命名和目录布局，为每份译本链接对应的英文来源，并把 Skill 参考文档译本加入 `scripts/package_skill.py` 的明确文件清单。只保留一个顶层 `SKILL.md` 入口，避免安装另一语言时产生重复 Skill。命令、ID、JSON 字段和状态值保留原拼写，用读者的语言解释含义。

## 修改源码与验证

运行源码位于 `prototype/`。Skill 内的 `scripts/` 是生成副本，修改源码或 Skill 内容后重新构建，不分别维护两份实现：

```bash
python3 scripts/package_skill.py
python3 -m unittest discover -s tests -v
```

测试使用临时 Git 仓库与模拟传输，不需要 GitHub 凭据或模型服务。对真实工具或 GitHub 的联调需明确选择测试仓库，并保留精确版本与实际执行证据；不要把模拟测试描述为真人审核或真实外部 AI 执行。

请保持 `LICENSE` 与 Skill 内的许可证一致，不提交凭据、个人运行日志或工作状态目录。新增能力应有针对实际行为的检查，特别是版本绑定、旧候选拒绝和原工作目录保留。
