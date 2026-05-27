# 更新 `master` 分支代码

## 参数

- **目标仓库路径**：根据业务路由确定，路径见 `SKILL.md` 映射表`仓库路径`列

## 步骤

1. `cd` 到目标仓库路径
2. 记录当前分支：`CURRENT_BRANCH=$(git branch --show-current)`
3. 检查是否有未提交变动：`git status --porcelain`
   - 有输出 → 执行 `git stash push -m "auto-stash before master update"`，记录已 stash
   - 无输出 → 跳过
4. 更新 master 分支：
   - 若 `$CURRENT_BRANCH` 是 `master`，直接 `git pull`
   - 否则依次执行：
     - `git checkout master`
     - `git pull`
     - `git checkout $CURRENT_BRANCH`
5. 若第 3 步执行了 stash，执行 `git stash pop`
