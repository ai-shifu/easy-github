# 交接给外部编程工具

Skill 负责管理交接，业务代码与冲突修复仍由用户选择的编程工具完成。用户已经在某个编程工具中工作时，直接把程序返回的工作目录和任务交给它即可；**不必为了使用 Skill 额外启动一款 CLI**。

交接材料应包含：工作意图、允许修改的范围、绝对工作目录、基线、work ID、attempt、项目验证方式，以及完成后停止写入并交回管理程序的要求。修复任务还需程序返回的 `context_file`。若工具只能读取分配目录，可把必要上下文内嵌到提示，不扩大它的文件访问范围。

告诉编程工具保留别人的已存在改动，只在本次目录内编程和检查；提交、推送、PR 与版本管理交由管理流程处理。工具结束进程不等于没有其他编辑器或后台写入者，冻结前仍需确认交接。

## 可选原生 CLI runner

机器已安装并完成相应原生登录时，可用包内 runner：

```bash
python3 "<Skill目录>/scripts/coders.py" --tool codex --workspace "<分配工作目录>" --prompt-file "<指令文件>" --output "<新的运行记录目录>" --mode edit --timeout 600
```

`--tool` 支持 `codex`、`claude`、`copilot`；`--mode` 支持 `edit`、`review`。提示通过 stdin 交给原生 CLI。把指令和运行记录放在业务工作目录、Skill 安装目录之外；`--output` 必须是新目录，不能覆写旧证据。不把已有授权扩大为安装或更改另一工具的全局配置。

runner 使用本机原生配置和认证，不复制凭据到提示或提交。保留 `manifest.json`、脱敏输出、`stderr.txt` 和 `final.txt`：

| 工具 | 原生输出与判定 | 权限边界 |
|---|---|---|
| Codex | JSON 事件 `events.jsonl`，识别 turn 完成或失败；记录会话 ID | edit 为 `workspace-write`，review 为 `read-only` |
| Claude Code | JSON 事件 `events.jsonl`，核对 result 成功状态 | 禁 hooks/额外 MCP；review 仅 Read/Glob/Grep |
| GitHub Copilot CLI | 纯文本 `stdout.txt`；exit 0、非空响应且无明确认证失败才记调用完成 | 禁内建和配置中的 MCP；review 禁 shell/write；edit 有写入与特定命令白名单 |

Copilot 不提供这里使用的结构化事件，`final.txt` 保留完整原生响应及工具过程，不是抽取后的单条结论。Claude/Copilot 的工具白名单不是操作系统沙箱；尤其 edit 的 Python 权限可以执行 Python 代码，不能据此声称任意进程或文件访问均被强隔离。

CLI 版本可能改变参数或输出。若本机命令不兼容，检查原生 `--help` 并保留失败证据；不要用不存在的事件或仅凭输出文件存在认定成功。无需为封装任务强制升级用户工具。

## 独立审查

先取得需审查的精确候选，放入干净、独立的 Git checkout；提供明确 base/head、需求范围和已知外部检查证据。然后：

```bash
python3 "<Skill目录>/scripts/coders.py" --tool codex --workspace "<候选的干净 checkout>" --prompt-file "<审查指令文件>" --output "<新的审查记录目录>" --mode review --timeout 600
```

runner 要求起始目录干净，并核对结束后的 HEAD 与工作区是否变化；变化则判为失败。Claude/Copilot 的 review 不执行 shell，业务测试由独立步骤完成，报告应区分“静态检查”与“自己实际运行测试”。Codex review 可在只读权限下执行检查。

原生 CLI 完成仅证明调用已结束。继续核对改动范围、实际业务结果及固定候选上的检查，再用管理程序交付或记录审查。AI 审查意见不是人工批准。

## 失败与更换工具

runner 达到超时会终止进程组。Claude 连续两次明确认证失败后停止；Copilot 检测到明确认证错误后停止。不要清零失败记录反复重试，或擅自更改全局认证配置掩盖问题。

用户已授权更换工具时，使用可用的真实工具继续，保留旧尝试与失败原因，并如实记录新工具。当前程序没有修改既有 work 工具标签的命令；可创建清楚标记新工具的新 work，若需要接续已交付内容，则显式提供该内容及当前基线，不能假装它自动迁移。未经停写确认，不让新工具同时占用旧工具仍在修改的目录。不能用模拟实现冒充另一工具的真实运行。
