# 定时衰减（生产部署）

每天 03:00 自动执行两步：先 **sync**（归一化登记手机/网页新来的裸笔记），
再**记忆衰减**。衰减任务**只写 sidecar 索引与报告，
绝不改动笔记文件**；报告写入 `<state_dir>/reports/decay-YYYY-MM-DD.md`。

- 推荐方案：**systemd timer**（用户级，Persistent 补跑）
- 备选方案：**crontab**

无论哪种方案，都需要先准备配置文件（gitignored，不入库）：

```bash
cd /srv/workspaces/Atelierr
cp config/memory.yaml.example config/memory.yaml
# 确认 memory.root / memory.state_dir 指向你的目录（默认 ~/atelierr-data）
```

手动触发一次（不依赖定时器）：

```bash
cd /srv/workspaces/Atelierr
python -m scripts.cli.memory_cli decay
# 输出示例:
# 总数: 1 | short-term: 1 | mid-term: 0 | long-term: 0
# 已迁移: 0 条
# 报告: /home/cj1024/atelierr-data/state/reports/decay-2026-08-29.md
```

---

## 方案 A: systemd timer（推荐）

Unit 文件随仓库分发在 `docker/systemd/`：

- `atelierr-decay.service`（Type=oneshot，WorkingDirectory 与
  `ATELIERR_CONFIG` 已内建；stdout/stderr 追加到
  `~/atelierr-data/state/logs/decay.log`，`ExecStartPre` 保证 logs 目录存在）
- `atelierr-decay.timer`（`OnCalendar=*-*-* 03:00:00`，`Persistent=true`）

### 安装（用户级）

```bash
# 1. 复制 unit 文件到用户级目录
mkdir -p ~/.config/systemd/user
cp docker/systemd/atelierr-decay.service docker/systemd/atelierr-decay.timer \
  ~/.config/systemd/user/

# 2. 重新加载并启用定时器（--now 立即生效）
systemctl --user daemon-reload
systemctl --user enable --now atelierr-decay.timer
```

> 说明：这是用户级（user）unit，不需要 root；`%h` 展开为你的 home。
> `ATELIERR_CONFIG` 指向仓库内的 `config/memory.yaml`，请按上文先准备。

### 查看状态与日志

```bash
# 定时器状态与下次触发时间
systemctl --user list-timers atelierr-decay.timer

# 手动触发一次（等价于 timer 到点）
systemctl --user start atelierr-decay.service

# 查看本次运行结果
systemctl --user status atelierr-decay.service

# 查看运行日志（也写入 ~/atelierr-data/state/logs/decay.log）
journalctl --user -u atelierr-decay.service
tail -f ~/atelierr-data/state/logs/decay.log
```

### 卸载

```bash
systemctl --user disable --now atelierr-decay.timer
rm ~/.config/systemd/user/atelierr-decay.service ~/.config/systemd/user/atelierr-decay.timer
systemctl --user daemon-reload
```

---

## 方案 B: crontab（备选）

与 systemd timer 等价的 crontab 行（`crontab -e`）：

```cron
# 先确保日志目录存在（首次执行一次）:
#   mkdir -p ~/atelierr-data/state/logs
#
# 每日 03:00 执行衰减；cd 到仓库根（python -m 依赖 CWD），
# stdout/stderr 追加到日志
0 3 * * * cd /srv/workspaces/Atelierr && /srv/workspaces/Atelierr/.venv-atelierr/bin/python -m scripts.cli.memory_cli decay >> /home/cj1024/atelierr-data/state/logs/decay.log 2>&1
```

要点：

- `cd /srv/workspaces/Atelierr` 不可省：`python -m scripts.cli.memory_cli`
  从当前目录导入 `scripts` 包；
- 使用绝对路径的 venv python（`/srv/workspaces/Atelierr/.venv-atelierr/bin/python`）；
- 日志路径中的 `/home/cj1024` 换成你的 home；
- 配置通过 `config/memory.yaml`（CWD 相对）解析；也可显式加
  `ATELIERR_CONFIG=/srv/workspaces/Atelierr/config/memory.yaml` 环境变量。

---

## 输出落点汇总

| 内容 | 路径 |
|---|---|
| 衰减报告（每次运行生成） | `<state_dir>/reports/decay-YYYY-MM-DD.md`（默认 `~/atelierr-data/state/reports/`） |
| 运行日志（systemd/cron 重定向） | `~/atelierr-data/state/logs/decay.log` |
| sidecar 索引（decay 更新） | `<state_dir>/index.json` |

查看最近报告：

```bash
cat ~/atelierr-data/state/reports/decay-$(date +%F).md
```
