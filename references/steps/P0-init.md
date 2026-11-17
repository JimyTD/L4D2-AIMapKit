# P0 开项目

**目的**：建好项目骨架，装齐依赖，定下 agent 配置。缺工具时流程走不完，所以先体检。

## 做

1. `kit init <目录> --name <项目名>`：复制项目骨架。骨架包括资料库、待决定列表、`PROJECT.md`、`HUMAN.md`、项目 `AGENTS.md`。
2. `kit doctor --write`：体检依赖，把找到的游戏目录和 python 写进 `kit.local.json`（这个文件不提交）。
3. **请示并安装**：把 `kit doctor` 报缺的项整理成一张清单，一次请用户批准，批准后由你安装。清单就是批准范围；以后再要新依赖，改清单重新请示。游戏本体和 Authoring Tools 需要用户登录 Steam 自己装：写进 `HUMAN.md`，附上步骤。
4. 再跑一次 `kit doctor`，直到全部通过。
5. **agent 配置**：先查清当前环境能不能派子 agent、能不能给子 agent 指定模型、能不能新开会话、每个会话同时能派几个子 agent。再问用户四件事，一次问完：主模型档用什么；轻量档用什么；同时推进几关的设计（每条都要用户拍板，开得越多用户要审的越多；设计线结束后改设计数据用的修订会话不算在内）；允不允许会话按流程在固定接力点自动开下一段、开修订会话（见 [sessions.md](../sessions.md)；不允许的话，每到接力点会话把开场白写好，用户自己开）。写进 `kit.local.json` 的 `agents`：

   ```json
   "agents": {"subagents": true, "pick_model": true, "new_session": true, "max_subagents": 3,
              "main": "<模型名>", "light": "<模型名>", "max_parallel_lines": 2, "auto_handoff": true}
   ```

   `new_session` 记环境能力，`auto_handoff` 记用户的授权，两者分开。环境不支持子 agent 时写 `"subagents": false`：之后所有子 agent 任务都由你自己做，流程照走，只是慢。
6. 仓库：`git init` 和 `git lfs install`。骨架里的 `.gitattributes` 把图片等二进制交给 LFS，编译产物不提交。资料库里有网络照片的项目仓库不能公开。
7. 更新 `PROJECT.md` 的当前阶段。

## 拍板

文字即可，不需要网页：依赖清单是安装许可请求，一次列全请用户批准；agent 配置四问一次问完。依赖清单要包括生成线用的软件（如 Blender 和它的 Source 导出插件、标识用字体），批准过的写进项目的依赖清单，之后缺了直接装，不再请示。

## 完成

- 用户批准了依赖清单，`kit doctor` 全部通过。
- `kit status` 显示 P0 完成，下一步 P1。

## 常见坑

- 设计做到一半，或交给生成时才发现缺工具，整条线停下。
- 脚本里写死本机路径，换台机器就跑不了。路径只写进 `kit.local.json`。
