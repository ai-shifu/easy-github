# 安装 Easy GitHub

Easy GitHub v0.1.2 是包含操作说明和 Python 运行脚本的自包含 Skill。安装 Skill 不会自动安装、登录或升级编程工具，也不会自动连接 GitHub 仓库。

## 环境要求

| 使用方式 | 需要什么 |
|---|---|
| 本地代码管理 | macOS/Linux、Python 3、Git，以及已有提交的本地 Git 项目 |
| 在 AI 工具中使用 Skill | 支持本地 Skill 的工具，例如 Codex 或 Claude Code |
| 可选的外部 CLI runner | 你要调用的 Codex、Claude Code 或 Copilot CLI 已安装且能正常使用 |
| GitHub 测试仓库集成 | 已登录的 `gh`，以及符合限制的目标测试仓库 |

当前程序使用 `fcntl` 进行状态锁定，不支持原生 Windows。无需额外安装 Python 运行依赖。

## 从仓库安装

首次发布通过 `feat/initial-release` 分支提交 PR，尚未自动合并到 `main`。使用下面的分支名取得完整 Skill：

```bash
git clone --branch feat/initial-release https://github.com/ai-shifu/easy-github.git
cd easy-github
```

### Codex

```bash
python3 scripts/install_skill.py --target codex
```

默认安装到 `~/.codex/skills/easy-github/`；若配置了 `CODEX_HOME`，使用其 `skills/easy-github/` 目录。安装器会输出实际路径。

在 Codex 中使用 `$easy-github`：

```text
用 $easy-github 查看这个项目的代码协作状态，先不要修改业务代码。
```

### Claude Code

```bash
python3 scripts/install_skill.py --target claude
```

安装位置为 `~/.claude/skills/easy-github/`。在 Claude Code 中使用：

```text
/easy-github 帮我为这项改动准备独立工作目录。
```

Claude Code 的 Skill 位置和调用方式见[官方说明](https://code.claude.com/docs/en/skills)。Skill 可在 Claude Code 内直接管理工作；可选 runner 的认证和可用性仍取决于你的本机环境。

### 自定义目录

`--dest` 指定最终的 Skill 文件夹，不是其父目录：

```bash
python3 scripts/install_skill.py --dest /absolute/path/to/skills/easy-github
```

使用支持 Skill 的其他工具时，先确认该工具的安装目录和调用方式。支持通过 runner 启动某款编程 CLI，不代表已经为该工具安装了原生 Skill。

安装器会校验包内文件。若目标已是完全相同的安装，则不改动；若已有内容不同，则停止，避免覆盖你的修改。升级前可先备份或移走旧安装，再安装新版本。业务状态和工作目录应放在安装目录之外，不能一起覆盖或迁移。

## 从安装包手动安装

仓库提供 [dist/easy-github.skill](../dist/easy-github.skill)。它是 ZIP 文件，内部只有一个 `easy-github/` 顶层文件夹。

1. 下载并解压安装包；如解压软件不识别扩展名，可先将副本改名为 `.zip`。
2. 将整个 `easy-github/` 文件夹复制到目标工具的 Skills 目录。
3. 确认目录内存在 `SKILL.md`、`scripts/`、`references/`、`manifest.json` 和 `LICENSE`。

不要只复制 `SKILL.md`，也不要把已有项目的状态库、日志或凭据放进 Skill 目录。

## 核验安装

在安装器报告的 Skill 目录中，运行以下命令确认脚本可启动：

```bash
python3 scripts/newgit.py --help
python3 scripts/coders.py --help
python3 scripts/github_live.py --help
```

这些命令只显示帮助，不初始化项目或操作 GitHub。若工具尚未列出新 Skill，可重新打开会话，或先按该工具支持的方式直接加载安装目录中的 `SKILL.md`。

开始实际工作时，告诉 AI 源项目在哪里，以及已有状态目录的位置。初始化只读取源项目已提交的 HEAD；继续工作应复用原状态目录。详细约定见[本地工作流](../skills/easy-github/references/workflow.md)。

## 卸载

确认不再需要该安装后，删除安装器报告的 `easy-github/` 文件夹即可。不要删除业务状态目录或其中的工作空间；卸载 Skill 不代表这些改动已经被接受或备份。
