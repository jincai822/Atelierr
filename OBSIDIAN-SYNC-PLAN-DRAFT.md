# 手机端方案草案：Obsidian + Syncthing

> 状态：**✅ 已实施完成并验收通过（2026-08-30）**。电脑侧 Docker 化部署，
> 手机侧华为 PTP-AN10（Syncthing-Fork v2.1.3.0 + Obsidian），局域网配对，
> 验收 5/5 通过（见"验收"节实测记录）。
> 起草日期：2026-08-30
>
> **2026-09-02 修订（最小档出口收敛）**：vault 根从 `memory/` 上移到 `$OV`，
> cognition/、reflections/ 进入 Obsidian 视野；Syncthing 挂载改
> `$OV → /data`（整棵数据树），`.stignore` 排除 `state/`、`sessions/`、
> `exports/`；附件目录固定为 `memory/attachments`，QuickAdd 宏与日记
> 插件加 `memory/` 路径前缀。应用代码零改动。

## 目标

解决 Flatnotes 手机端交互局促的问题：手机端改用 Obsidian App +
Syncthing 同步，电脑端工作流不变。Flatnotes 保留，可双轨运行。

## 架构影响评估（已核验，2026-08-30）

对照 `docs/AGENT-ONBOARDING.md` 五条设计不变量，逐条结论：

| 不变量 | 结论 | 依据 |
|---|---|---|
| 平面存储、无子目录 | ✅ 兼容，带一条使用纪律 | watcher 非递归扫描（`scripts/memory/watcher.py:79,150`）；`memory/` 根层保持平面，`wiki/`、`templates/`、`attachments/` 为有意子目录（沉淀层/模板/附件），memory 机制不扫子目录 |
| 机器绝不移动/改写笔记 | ✅ 兼容 | 条款约束系统代码；Obsidian 写入由用户键盘触发，Syncthing 仅传播用户编辑。唯一机器写入仍是 watcher 一次性补 frontmatter（`watcher.py:111-119`，`os.utime` 还原 mtime）。副作用：补写后的 frontmatter 会回传手机，显示为"属性"块 |
| 动态状态只进 sidecar | ✅ 兼容 | 同步整个 `$OV` 数据树；`state/`、`sessions/`、`exports/` 经 `.stignore` 排除不离开电脑；`.obsidian/`、`.stfolder` 为隐藏项，watcher 跳过（`watcher.py:80`，有测试兜底） |
| confidence 无状态纯函数 | ✅ 不触碰 | Syncthing 默认同步 mtime，decay 的 modified 信号保持真实 |
| 无自动删除 | ✅ 兼容 | 手机删笔记 = Flatnotes 删笔记的同一已测试路径（外部删除 → watcher 注销，`test_external_deletion_deregisters`）；`trash/` 在 `$OV/state/`（`memory_cli.py:266`），在同步范围之外，purge 副本安全 |

**结论：零架构改动、零必需代码改动。**

佐证：框架侧脚本本就把 `.obsidian` 当已知目录跳过
（`scripts/atelier/wikilink_to_md.py:42`），此路径与仓库生态一致。

## 新现象（非破坏）

- 双向同时改同一篇 → 产生 `xxx.sync-conflict-*.md`，会被 watcher 当
  新笔记登记：合并后删除即可（可选优化：watcher 加一行排除规则）
- 手机新建笔记需等 `memory_cli sync` 才进索引（与 Flatnotes 现状相同）

## 实施步骤（待执行）

### 电脑侧（✅ 已实施，2026-08-30，Docker 化）

**实施偏差说明**：原计划 apt 安装，但 apt 需 sudo 密码且源内版本过旧
（1.18），GitHub 直连下载超时。改用 Docker（与 Flatnotes 同一
compose，镜像仓库可用、免 sudo）。镜像 `syncthing/syncthing:latest`
= v2.1.3。功能与原计划等价。

已完成：

1. `docker/docker-compose.yml` 新增 `syncthing` 服务：host 网络
   （局域网发现 + WireGuard 直连）、PUID/PGID=1000、挂载
   `$OV` → `/data`（2026-09-02 起为整棵数据树，原为 `$OV/memory`）、
   配置落 `docker/syncthing-config/`
2. 容器 `atelierr-syncthing` 运行中；经 REST 注册文件夹
   `atelierr-memory`（Send & Receive、fsWatcher 开启、版本控制关闭），
   已扫描现有笔记（4 个文件 ≈16KB），`.stfolder` 标记已生成
   （watcher 忽略隐藏项）
3. 管理台 <http://127.0.0.1:8384>——首次访问请自行设置 GUI
   用户名/密码

待手机侧就绪后：管理台接受设备配对 → 文件夹 Sharing 勾选手机。

### 手机侧（约 15 分钟，仅安卓；iOS 不适用本方案）

1. 安装 **Syncthing-Fork**（F-Droid 或 GitHub APK；国内商店没有）
   - 小米/MIUI 防杀后台：应用信息 → 省电策略 → 无限制；允许自启动；
     最近任务里下拉锁定该应用
2. 安装 **Obsidian**（Play 商店或官网 APK，个人使用免费）
3. 配对（全程扫码，不用手输地址）：
   - 电脑管理台右上角菜单 → Show ID，显示二维码
   - 手机 Syncthing-Fork → 设备页 → + → 扫电脑二维码 → 保存
   - 电脑管理台弹出"新设备请求连接"→ 接受
4. 接收共享文件夹：
   - 电脑侧：文件夹设置 → Sharing → 勾选手机
   - 手机收到共享通知 → 接受，存放路径选 `Documents/atelierr-memory`
     （Obsidian 可访问的位置）
   - 等首次同步完成（现有笔记全部落到手机）
5. Obsidian 设置：
   - 「打开文件夹作为仓库」→ 选 `Documents/atelierr-memory`
     （2026-09-02 起库根 = 同步根；笔记在 `memory/` 子目录，
     沉淀层在 `memory/wiki/`，判断登记处在 `cognition/`）
   - 社区插件（Dataview/QuickAdd）与模板随 `.obsidian/` 自动同步
   - 新笔记位置默认；附件已配置固定为 `memory/attachments`
6. 远程同步：**✅ 2026-08-30 当晚打通**。实测机制为**公网 IPv6 端到端
   直连**（电信宽带与 5G 均分配公网 v6，经全球发现服务器交换地址），
   不依赖 WG 隧道；WG（`tcp://10.66.0.2`）作为备选通道。白天排查走过
   的弯路：Orca 内嵌浏览器是电脑中转（不能当连通性判据）、国产浏览器
   云加速会劫持私有地址、手机 App 被运行条件挂起。注意：电脑 22000
   端口经公网 v6 可达，Syncthing 按公网暴露设计（设备证书双向认证，
   陌生设备拒绝），风险可接受。

### 验收（✅ 5/5 通过，2026-08-30 实测）

1. ✅ 手机 Obsidian 新建笔记（`标题首测.md`）→ 电脑秒级出现（21:44 到达，
   同步流量有进有出）
2. ✅ 电脑跑 `memory_cli sync` → 归一化 1、登记入索引
3. ✅ `memory_cli stats` 总数 2，含新笔记
4. ✅ mtime 零污染：归一化后 mtime 精确还原（21:44:32），decay dry-run
   前后一字不差
5. ✅ 手机删除该笔记 → 电脑侧文件消失（Syncthing 传播删除）→ 再次 sync
   注销 1 条 → stats 回到总数 1

实施排障记录：GitHub 直连不可达（手机走 GitHub 经梯子/镜像下载）；
管理台默认暴露局域网（镜像 `STGUIADDRESS` 默认 `0.0.0.0`，已收回
127.0.0.1）；ufw 默认 deny incoming 拦 22000（`sudo ufw allow 22000`）；
手机运行条件默认仅 Wi-Fi（已开移动数据 + 省电无限制）；远程 WG 直连
不通（手机隧道路由不到 10.66.0.2，排查列入 backlog）。

## 使用纪律

- `memory/` 根层保持平面（笔记只落在根层）；wiki 条目进 `wiki/`，
  附件自动进 `attachments/`，模板放 `templates/`——这些是豁免子目录
- sync-conflict 文件合并内容后删除
- cognition（认知条目）操作只在电脑 CLI 进行（批准闸门，刻意设计）

## 可选增强（不在本草案范围，另行批准）

- watcher 排除 `*.sync-conflict-*.md`（一行规则 + 测试）
- `memory_cli sync` 并入每日 03:00 systemd timer（decay 之前执行）
- 常驻 watcher 服务替代手动 sync
- 电脑侧安装 Obsidian 作为 GUI（纯可选）

## 回退方案

手机端卸载/停止同步即可；电脑端 Flatnotes、CLI、定时器全程未动，
随时回到现状。

## 风险与边界

- iOS 不适用（沙箱限制，Syncthing 类工具无法与 Obsidian 共享文件夹）；
  iPhone 用户应走 SilverBullet 网页方案（另立草案）
- Obsidian 为闭源软件（个人使用免费）；Syncthing 安卓官方版已停更，
  使用社区维护的 Syncthing-Fork
- Syncthing 版本控制功能（`.stversions`）默认关闭；如开启会占用额外
  磁盘，与本系统 `trash/` 机制冗余，建议不开
