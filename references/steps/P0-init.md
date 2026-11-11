# P0 开项目

**目的**：建好项目骨架，装齐依赖，定下 agent 配置。缺工具时流程走不完，所以先体检。

## 做

1. `kit init <目录> --name <项目名>`：复制项目骨架。骨架包括资料库、待决定列表、`PROJECT.md`、`HUMAN.md`、项目 `AGENTS.md`。
2. `kit doctor --write`：体检依赖，把找到的游戏目录和 python 写进 `kit.local.json`（这个文件不提交）。
3. **请示并安装**：把 `kit doctor` 报缺的项整理成一张清单，一次请用户批准，批准后由你安装。清单就是批准范围；以后再要新依赖，改清单重新请示。游戏本体和 Authoring Tools 需要用户登录 Steam 自己装：写进 `HUMAN.md`，附上步骤。
4. 再跑一次 `kit doctor`，直到全部通过。
5. **agent 配置**：先查清当前环境能不能派子 agent、能不能给子 agent 指定模型、能不能新开会话。再问用户三件事：主模型档用什么、轻量档用什么、并行主线最多开几条。写进 `kit.local.json` 的 `agents`：

   ```json
   "agents": {"subagents": true, "pick_model": true, "new_session": true,
              "main": "<模型名>", "light": "<模型名>", "max_parallel_lines": 2}
   ```

   环境不支持子 agent 时写 `"subagents": false`：之后所有子 agent 任务都由你自己做，流程照走，只是慢。
6. 仓库：`git init` 和 `git lfs install`。骨架里的 `.gitattributes` 把图片等二进制交给 LFS，编译产物不提交。资料库里有网络照片的项目仓库不能公开。
7. 更新 `PROJECT.md` 的当前阶段。

## 完成

- 用户批准了依赖清单，`kit doctor` 全部通过。
- `kit status` 显示 P0 完成，下一步 P1。

## 常见坑

- 设计做到一半，或交给生成时才发现缺工具，整条线停下。
- 脚本里写死本机路径，换台机器就跑不了。路径只写进 `kit.local.json`。

