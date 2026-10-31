# 本地交付与审查

以下 `<Skill目录>` 指包含 `SKILL.md` 的安装目录；使用绝对路径调用其 `scripts/`，不依赖当前工作目录。ID、attempt、SHA 和工作目录均取自程序实际返回。命令输出 JSON，退出码非 0 表示未完成。

## 初始化与恢复

需要 Python 3、Git；当前状态锁使用 `fcntl`，支持 macOS/Linux。先确认用户指定的 Git 项目和当前 HEAD。初始化仅导入**已提交 HEAD**，不会带入未提交修改，也不会自动拉取远端。不要为初始化擅自提交、清理或覆盖原工作区。

状态目录必须位于源仓库之外，且不放进 Skill 安装目录。新任务明确记录状态目录；继续任务先读已有 `status`，不要重复初始化：

```bash
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" init --source "<源仓库根目录>"
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" status
```

状态库是源项目的独立副本，团队版本是其中的 `refs/heads/prototype-team`。以后 `start` 使用这个版本，**不自动跟随源仓库或 GitHub 更新**。Skill 文件可以复制安装；运行状态包含绝对路径和 Git worktree 关联，不能直接移动整个状态目录或把它作为 Skill 的一部分分发。

## 开始工作与固定交付

```bash
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" start --owner "<作者标签>" --tool "<实际工具标签>" --title "<工作意图>"
```

将返回的 `workspace`、`base`、`id`、`attempt` 交给用户选择的编程工具。工作目录是独立、detached 的 Git worktree，用户无需手工创建分支。编程工具如何接手见 [coders.md](coders.md)。

交付前，确认该目录的 AI、编辑器和后台进程都已停止写入。程序锁只协调自身调用；`--handoff` 是调用者声明，不是停写命令。不能证明已交接时，不声称已固定可靠交付。

```bash
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" submit --work "<work ID>" --attempt <当前序号> --handoff --summary "<实际变化摘要>"
```

保存返回的完整 delivery JSON。程序固定新快照，不移动原工作目录的 HEAD 或 Git index；之后继续编辑不会改变已交付快照。再交付会形成新修订，旧修订不能沿用批准。`submit` 会包含工作目录内所有 Git 应纳入的文件，交付前核对变更范围，避免把运行日志、临时文件或凭据混入。

## 审查与修复

```bash
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" review --delivery "<delivery ID>" --reviewer "<拟交给的审核者标签>"
```

`reviewer` 必须不同于作者标签，但标签不认证身份。`review` 只是准备材料，`ready` 只表示有可检查的候选；不能说该人已经看过或批准。展示本次意图、实际差异、`candidate_sha`、`team_sha` 及已执行检查。

若返回 `needs_update`，读取原因。当前程序对两边修改同一文件采取保守处理，即使 Git 可能自动合并，也会要求外部修订；没有实际 Git 冲突证据时，不把“同文件重叠”称为文本冲突。

```bash
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" update --delivery "<最新 delivery ID>"
```

`update` 保留原目录，返回新工作目录、新 `attempt` 和 `context_file`。上下文包含原交付与团队版本的差异；由外部编程工具在新基线上重建意图，程序不生成业务修复。只用新目录和新 attempt 交付，然后重新审查。开始更新后，旧 attempt 暂停收下。

### 两份改动都尚未收下

若 B 需要与未合并 A 组合，不先收下 A 来制造基线：

```bash
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" review --delivery "<B delivery ID>" --reviewer "<审核者标签>" --onto-delivery "<A delivery ID>"
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" update --delivery "<B 最新 delivery ID>" --onto-delivery "<A delivery ID>"
```

第二条只在需要修复时运行。`team_sha` 仍是真实团队版本，`comparison_sha` 才是 A 的候选版本；`team_diff` 和 `comparison_diff` 不能混用。修复目录及新交付继承 `onto_delivery_id`，省略参数不会解除依赖。A 有新修订时，显式选择当前交付并重新修复，不能静默沿用旧 A。`preview_only=true` 的审查永远不能 `accept`。

## 检查具体候选

外部执行者取得 review 指定候选的独立 checkout，核对实际 SHA 后执行项目所需检查。只有实际执行后才能登记：

```bash
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" check --review "<review ID>" --snapshot "<实际候选 SHA>" --name "<检查名称>" --status passed --detail "<实际命令、结果及证据位置>"
```

失败时使用 `--status failed`，不掩盖失败。工作目录或旧交付上的结果不能登记给另一个候选。程序保存外部上报，无法证明检查真实发生；目前门槛为至少一项检查且全部登记检查通过，没有生产级必需检查清单。

## 人确认后在本地收下

仅在用户已确认**这份 review 及其具体候选**、且授权仍有效时执行；已有有效确认不需重复索取。AI 建议、测试成功或笼统的继续工作指令不自动构成收下授权。

```bash
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" accept --review "<review ID>" --reviewer "<该 review 的审核者标签>"
python3 "<Skill目录>/scripts/newgit.py" --state "<状态目录>" status
```

此操作**只移动隔离状态库的团队版本**，不会更新源仓库或 GitHub，也不是合并 main。回读成功后才能报告本地已纳入。新版交付、更新中的 attempt、失败检查、团队版本变化或标签不匹配会阻止收下；重新准备审查和必要修复，不能反复强行写入或沿用旧批准。永远不要主动合并 main。

接受操作会先保存具体候选的意图记录。若进程中断，下一次持锁操作会核对 Git ref 与记录：已应用的版本补齐审查记录，尚未应用的意图清除后仍需显式重试。出现第三个版本或记录不匹配时会停止恢复，不覆盖现状；先查明原因。同一审核者对仍处于当前团队版本的已完成接受可以安全重试。
