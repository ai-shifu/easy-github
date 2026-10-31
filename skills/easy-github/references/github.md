# GitHub 测试仓库适配器

`scripts/github_live.py` 当前是受限实验适配器：仅支持 `github.com` 上**私有、名称以 `newgit-integration-` 开头**的明确指定仓库。允许的 base 为 `prototype-team` 或 `newgit/<work_id>`，交付 head 为 `newgit/<work_id>`。不能把它描述为支持任意生产仓库；不为绕开限制而擅自改名、复制仓库或取消检查。

需要已登录的 `gh` 和本地固定交付所在的 bare Git 目录。写入范围必须来自用户当前任务或仍有效的已有授权；Skill 的存在和历史实验不授予任何仓库写入权限。适配器没有创建仓库、初始化远端基线、APPROVE 或 merge 操作。

## 发布前

- 从管理程序保留完整 delivery JSON，使用状态库返回的 `repo` 作为 `--git-dir`；不要手工伪造 SHA 或 work ID。
- 远端目标 base 必须已存在，且 SHA 精确等于 `delivery.base`。基线建立是单独准备工作，不能靠合并 main 或绕过校验来完成。
- 回读仓库、base/head、已有 PR、reviews 和 CI，避免重复创建或发送同一审查。GitHub 操作者取真实登录账户，不能把本地作者/审核者标签称为另一位真人。

## 创建或更新 PR

将 PR 正文写入文件后调用：

```bash
python3 "<Skill目录>/scripts/github_live.py" --repository "<owner/newgit-integration-name>" --git-dir "<状态库的 repo.git>" --evidence-dir "<运行记录目录>/github" publish --delivery-file "<完整 delivery JSON 文件>" --title "<改动标题>" --body-file "<正文文件>" --base "prototype-team"
```

正文说明具体问题、行为变化、真实实现工具、实际验证和依赖；把未执行的检查明确区分开。适配器创建非 draft PR，并核对 head/base 都属于指定仓库。

新建交付分支必须尚不存在。更新已有 PR 时，在同一 `publish` 命令中同时提供：

```text
--previous-head <刚读回的完整旧 head SHA> --pull-number <真实 PR 号>
```

程序使用精确 lease 推送固定 SHA，核验远端分支与 PR 读回。若 head/base 已变化，先查明变化、重新准备交付或审查，不能盲目重试覆盖别人的更新。

如果 B 在未合并 A 上修复，B 的 `delivery.base` 应为 A 的固定 SHA，并使用 `--base "newgit/<A 的 work_id>"`。这样可保留两个均未合并的 stacked PR；A 分支若已移动，停止沿用旧 B。候选组合的具体操作见 [workflow.md](workflow.md)。

## 发表 AI 审查

审查完成后，以实际看过的 head、base ref 和 base SHA 调用：

```bash
python3 "<Skill目录>/scripts/github_live.py" --repository "<owner/newgit-integration-name>" --git-dir "<状态库的 repo.git>" --evidence-dir "<运行记录目录>/github" review --number <PR号> --commit "<已审查 head SHA>" --base "<已审查 base 分支>" --base-sha "<已审查 base SHA>" --body-file "<审查正文文件>"
```

正文写明实际审查工具、范围、可操作发现、测试是亲自执行还是外部提供，以及未验证事项。适配器只发表 `COMMENT`，不能把它称为人工批准或 APPROVE。

程序在发表前后核对精确 head/base，并回读审查 ID、作者、状态、正文和 commit。写入失败不自动重试；响应不确定时先读远端，查明是否已发生，避免重复发送。

## 完成回读

分别报告：PR 是否创建及其当前 head/base、是否仍打开且未合并、CI 对应的具体 SHA 和结果、AI COMMENT 是否存在、是否有人的实际批准。适配器的 PR 发布成功不代表 CI 成功，也不证明已经有人审核。证据 JSON 保存在指定 `--evidence-dir`，不放进 Skill 包或业务提交。

无论测试、审查或人工建议如何，永远不要主动合并 main；本适配器不执行任何合并。
