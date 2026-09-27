# Mac mini 迁移交接文档（2026-09-27）

> 读者：在 Mac mini（M6 / 24GB）上接手的 k3。
> 目的：把 Atelierr 从 Linux 台式机（cj1024-desktop）完整迁移过来并继续开发。
> 先读 `docs/AGENT-ONBOARDING.md`，再读本文件。两文件冲突时以锁定契约为准。

## 0. 迁移前快照（源机实测）

- 代码库：`https://github.com/jincai822/Atelierr.git`（私有），迁移点 HEAD `30f0853` 之后
  含本目录 `docs/migration/`。
- 数据库（vault）：`https://github.com/jincai822/atelierr-data.git`（私有），
  本地路径 `~/atelierr-data`（356MB），**迁移前已推送干净**。
- 密钥：`~/.config/atelierr/env`（7 行：DEEPSEEK_API_KEY、FEISHU_APP_ID/SECRET/
  CHAT_ID/VAULT_NAME/NOTE_PREFIX、OV）。**不进 Git，手工加密搬运**，目标机放同
  路径并 `chmod 600`。
- 源机 Python 3.12.13，依赖冻结见 `pip-freeze-2026-09-27.txt`（267 包）。
  关键：mineru 4.0.2、openai-whisper 20250625、lark-oapi 1.7.3。
- 源机 systemd 单元原件存于 `systemd-user/`（24 个，仅作语义参考，macOS 不用）。

## 1. Mac 端重建步骤（按顺序）

1. 底座：Homebrew、git、uv（`brew install uv`）、OrbStack 或 Docker Desktop、
   Syncthing、WireGuard（如需）。
2. `git clone` 两个仓库。**vault 必须克隆为 `~/atelierr-data`**——
   `config/memory.yaml` 全部用 `~/` 相对路径，同名即零改动。
3. Python 环境：
   ```bash
   cd <repo>
   uv venv .venv-atelierr-312 --python 3.12
   uv pip install --python .venv-atelierr-312/bin/python -r requirements.txt
   ln -sfn .venv-atelierr-312 .venv-atelierr   # 车间 researcher/forgetter 写死用这个名字
   ```
   注意：venv 内无 pip，一律用 `uv pip`。
4. 放密钥 `~/.config/atelierr/env`。
5. MinerU：`uv pip install --python .venv-atelierr-312/bin/python "mineru[all]"`，
   首跑下载模型；Apple Silicon 走 MPS，无 CUDA。
   `mineru config set parse_server.local.mode managed`（与源机一致）。
6. Whisper：首次转写自动下载模型。代码已 GPU 优先、自动回退 CPU
   （`scripts/processors/video.py`），Mac 上会跑 CPU——**功能不变，速度慢数倍**，
   M6/24G 可跑 large 档位。
7. 语义索引重建（索引不搬运）：`uvx basic-memory reindex`。
8. 定时任务（13 个 launchd plist 已生成在 `launchd/`）：
   ```bash
   REPO=<repo 绝对路径> bash docs/migration/install.sh
   ```
   对应关系：decay 每日 03:00 → bmindex 03:20 → digest 07:53 →
   light/links 每 15 分钟错峰（:03/:07 起）→ pending 21:17 → review-daily 21:30 →
   review(周报) 周日 09:13 → weekly-draft 周日 08:47 → review-monthly 每月 1 日
   09:21 → dochealth 每月 2 日 04:17；feishu（websocket 长连接）与 mineru 为
   KeepAlive 常驻。
9. Syncthing：与手机重新配对，共享 `~/atelierr-data`。

## 2. Mac 差异适配（全部已处理，无需改代码）

- **飞书是 websocket 长连接主动连云**（`scripts/dispatch/feishu.py`），NAT 后直接
  可用，不需要公网 IP/回调域名。
- GPU → MPS/CPU：whisper 与 mineru 均自动降级，仅速度损失。
- systemd → launchd：见上。systemd 的 `Persistent=true`（错过补跑）launchd 原生
  支持（睡眠错过的 StartCalendarInterval 唤醒后补跑一次）。
- 代理：plist 与 bmindex 均写死 `127.0.0.1:7897`，Mac 代理软件端口不同则统一改。
- Flatnotes 网页模块已停用，不迁。

## 3. 切换与回退（顺序不能反）

1. 源机停全部任务，**特别是飞书长连接**（双机同时在线会抢消息）：
   `systemctl --user stop atelierr-feishu.service` 及各 timer，然后
   `systemctl --user disable`。
2. Mac 端 `install.sh` 加载全部 plist。
3. 旧机保持原样一周作回退，Git 即完整状态，随时切回。

## 4. 验收清单（全绿才算迁完）

- [ ] 门禁三件套：`.venv-atelierr-312/bin/python -m pytest -q` 全绿 /
      `python tools/acceptance_test.py` 8/8 /
      `python scripts/atelier/harness_smoke.py` exit 0
- [ ] 端到端：飞书发一条抖音/B站链接 → 收卡片 → 确认 → 归档到 `memory/` 正确领域
- [ ] 次日 07:53 晨报自动推送到飞书
- [ ] 飞书搜一条老笔记命中（验 basic-memory 索引）
- [ ] 手机 Obsidian 经 Syncthing 看到 Mac 的 vault

## 5. 开发规矩（源机沿用，勿违）

- 测试统一 `.venv-atelierr-312/bin/python -m pytest -q`；**绝不用仓根 `.venv`**
  （那是 Atelier 车间的 uv 管理环境，禁改）。
- 每次提交前过门禁三件套；commit 消息 `atelierr: <小写英文摘要>`；推送带
  `git -c http.proxy=http://127.0.0.1:7897 push`；vault 提交后顺手推送。
- 禁区（不得改动）：`scripts/atelier/`、`scripts/*.sh`、`.claude/`、`.codex/`、
  `.agents/`、`harness/`（`paths.local.toml` 注释可写）、`protocols/`、
  `frameworks/`、`sources/`、`tests/` 根层 `test_*.py`、`CLAUDE.md`、`AGENTS.md`、
  `pyproject.toml`、`uv.lock`、`.venv`。
- 笔记不可变红线：创建后机器绝不移动/改写；动态状态只进 `state/index.json`；
  删除只走 pending_delete → review → purge → trash/；confidence 是无状态纯函数
  `0.95 ** (idle_days / ref_factor)`。
- 23:00–07:00 飞书推送类测试失败是设计行为（静默时段），不是回归。

## 6. 已知挂单（迁移时点 backlog）

- 方案 C（机器全文差异化衰减）：观察期一个月，暂不实施。
- Whisper 真实模型转写验证： backlog，MVP 用 mock 通过。
- 手机 dashboard 显示问题：用户拍板暂时关闭。
- `.trash/` 旧重复文件清理：用户自己的回收站决策。
- 认知升级三方向（回路三启用 / 判断定期回顾 / decision 接 cognition）：
  用户尚未选择，等拍板。规格在 `docs/prd/COGNITION-SPEC.md` v1.2。

## 7. 源机其他系统（不属于本迁移）

closed-loop-2、llm-wiki、mem0、uptime-kuma、giffgaff 提醒等是源机上别的系统，
不要迁，也不要在本仓库引用。
