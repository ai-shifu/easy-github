# Easy GitHub

[English](README.md) | [简体中文](README.zh-CN.md)

**用自然语言管理代码协作，让人专注方向和审核。**

A friendlier GitHub workflow for humans and AI coding tools.

Easy GitHub 是一个面向多人、多 AI 协作的 Skill。代码由你选择的编程工具完成；它负责准备独立工作目录、固定交付版本、整理审查材料，并在改动无法直接组合时，把上下文交回编程工具修复。

**当前版本：0.1.3，原型阶段。** 本地工作流可用于本地 Git 项目；GitHub 写入目前只支持私有的 `newgit-integration-*` 测试仓库。它不会主动合并 `main`，也不会把 AI 审查当成人工批准。

## 快速安装

需要 macOS 或 Linux、Python 3.11 或更新版本和 Git。请使用 UTF-8 终端和区域设置（locale），确保非 ASCII 路径和参数正确传递。克隆仓库默认的 `main` 分支：

```bash
git clone https://github.com/ai-shifu/easy-github.git
cd easy-github
python3 scripts/install_skill.py --target codex
```

然后在 Codex 中调用：

```text
用 $easy-github 给这项工作准备一个独立空间，我用 Codex 来写。
```

Claude Code 用户可使用 `--target claude` 安装，并用 `/easy-github` 调用。安装器不覆盖内容不同的已有 Skill；完全相同的安装重复执行不会重写文件。

[完整安装方法](docs/zh-CN/installation.md)包括自定义目录、安装包方式及安装核验。

## 怎么用

用你习惯的语言直接描述想做的事：

```text
用 $easy-github 交付这份改动，整理给同事审查。

用 $easy-github 检查这两份改动能否一起使用。
两份都还没收下；需要修改时，准备新目录，保留旧版本。

用 $easy-github 把这版送到指定测试仓库审查，先不合并。
```

Skill 会保留 Git / GitHub 的版本、差异和 PR 链接，帮助你理解当前状态。你不需要先手动安排分支或记住提交命令。

完整过程见[使用示例](docs/zh-CN/examples.md)。

## 现在能做什么

| 能力 | 当前行为 |
|---|---|
| 独立工作 | 为每项工作准备隔离目录，供不同编程工具接手 |
| 固定交付 | 外部工具停写后，保存不可变的交付版本 |
| 组合与冲突材料 | 检查两份改动，保留旧目录，给外部 AI 准备新修复目录和上下文 |
| 审查与检查记录 | 将差异、检查结果和审查绑定到具体版本 |
| 可选工具调用 | 调用已安装、已登录的 Codex、Claude Code 或 GitHub Copilot CLI |
| 测试仓库 PR | 发布固定交付、创建或更新 PR、发表绑定版本的 AI `COMMENT` |

Skill 的职责、命令和接入细节见 [Skill 中文说明](skills/easy-github/references/zh-CN/skill.md)。

## 当前边界

- **状态库是独立副本。** 初始化只导入源项目已提交的 HEAD，后续不自动同步源项目或远端。未提交改动不会自动进入新工作。
- **本地“收下”只更新状态库。** 它不会更新原项目或 GitHub；组合预览不能直接收下。
- **GitHub 适配器仍限实验。** 目标必须是 `github.com` 上私有的 `newgit-integration-*` 仓库，目标基线需预先存在。它不创建仓库，不提供 merge 或 `APPROVE`。本项目本身公开开源。
- **人仍做决定。** `ready` 表示可审查；CI 通过、AI 建议和人工批准是不同状态。本地参与者名称只是标签，不是身份认证。
- **没有完整产品界面。** 当前没有 GUI、后台自动保存、自动远端同步或正式多人权限系统。状态目录包含本机路径，不能随 Skill 搬迁。

现有工具白名单也不等于操作系统沙箱。外部工具权限和实际检查范围见[编程工具接入](skills/easy-github/references/zh-CN/coders.md)。

## 开发与验证

Python 运行代码使用标准库。运行本地测试：

```bash
python3 -m unittest discover -s tests -v
```

本地演练使用模拟角色和临时 Git 仓库，不调用真实模型或 GitHub：

```bash
python3 scripts/run_demo.py
```

修改 `prototype/` 中的运行源码后，重新生成 Skill 内的脚本副本和安装包：

```bash
python3 scripts/package_skill.py
```

不要分别修改 `prototype/` 与 Skill 中的运行脚本。生成的 `manifest.json` 记录包内文件哈希；打包不包含运行状态、凭据或本机日志。

审查流程和语言约定见[贡献说明](CONTRIBUTING.zh-CN.md)。

## 许可证

[MIT](LICENSE)。Skill 安装包包含许可证，可按许可证条款使用、修改和分发。
