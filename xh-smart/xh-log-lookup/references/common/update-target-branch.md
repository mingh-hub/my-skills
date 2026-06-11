# 更新本地代码分支（按环境选分支）

代码锚点校验前，必须确保本地仓库代码与日志所属环境实际运行的分支一致。**生产看 master，测试看需求开发分支**——两者分路，不能混用。

## 为什么分环境

- **生产环境**跑的是 `master`（或对应 release），默认更新并读 `master` 是对的。
- **测试环境**大多在跑某个需求开发分支，新增逻辑在 `master` 上**不存在**。若仍读 `master`，会出现两类错误：
  - 锚点对不上 → 误判"日志已下线/模板过期"。
  - 更隐蔽：读到 `master` 旧逻辑分析得头头是道，但测试环境实际跑的是开发分支新代码，**结论看似有据实则错误**。
- 当前业务代码未打印 git commit/branch/version，无法从日志自动反推测试分支，所以测试环境**必须先确认分支**。

## 参数

- **目标仓库路径**：按业务路由确定，路径见 `SKILL.md` 映射表`仓库路径`列。
- **目标分支 `TARGET_BRANCH`**：
  - 生产环境 → `master`（无需询问）。
  - 测试环境 → 读代码前 `TARGET_BRANCH` **必须已确认**，按以下顺序取值，禁止默认 `master`：
    1. 用户在提问中**已给出分支名**（如"在 `feature/xxx` 测的"）→ 直接用，不再重复提问。
    2. 未给出 → **先问用户**该问题测的是哪个需求开发分支，拿到再继续。
    3. 用户答不上来 → 用「测试分支推断」列候选，经用户确认后再读代码。

## 测试分支推断（用户答不上分支名时的辅助手段）

测试环境的需求开发分支**一般以 `release-` 开头**（如 `release-1.0.0`）。在目标仓库执行，优先按此命名约定 + 最近活跃度给候选，供用户确认：

1. `git fetch --all --prune`
2. 列最近活跃分支，优先 `release-` 开头：
   - 优先：`git for-each-ref --sort=-committerdate refs/remotes/origin --format='%(committerdate:short) %(refname:short)' | grep -E 'origin/release-' | head -10`
   - 补充（`release-` 无命中时）：去掉 `grep` 看全部最近分支 `git for-each-ref --sort=-committerdate refs/remotes/origin --format='%(committerdate:short) %(refname:short)' | head -10`
3. 把候选列给用户，结合日志时间窗口（日志产生时间附近的分支更可能是测试分支），请用户确认；确认前不得用任一分支的代码下结论。

## 更新步骤

1. `cd` 到目标仓库路径。
2. 记录当前分支：`CURRENT_BRANCH=$(git branch --show-current)`。
3. 检查未提交变动：`git status --porcelain`
   - 有输出 → `git stash push -m "auto-stash before branch update"`，记录已 stash。
   - 无输出 → 跳过。
4. 更新到 `TARGET_BRANCH`：
   - 先 `git fetch origin`。
   - 若 `$CURRENT_BRANCH` == `$TARGET_BRANCH`，直接 `git pull`。
   - 否则依次：`git checkout $TARGET_BRANCH` → `git pull` → 读完代码后按需切回 `git checkout $CURRENT_BRANCH`。
5. 若第 3 步执行了 stash，执行 `git stash pop`。

## 结论标注（强制）

测试环境读代码后，结论必须写明**实际依据的分支名**，例如"基于 `feature/xxx` 分支代码分析"。若分支未经用户确认或存在不确定，必须标注"分支未确认，结论可能不准"，不能把测试问题当作生产链路下最终根因。
