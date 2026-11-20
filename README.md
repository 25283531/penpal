# 笔友 (Penpal) — M0 后端

慢信 + 虚拟笔友：用户选一位虚拟人物写长信（最长 2000 字），对方按
节奏回一封同样可长达 2000 字的信。关系是**知己**，不是恋人/伴侣。
第一阶段**不收费**，所有用户均为免费档。

宣传词：从前车马很慢，书信很远，一生只能交心一个人。

设计文档：`workspace/penpal-app/PLAN.md`、`workspace/penpal-app/characters.md`
（本仓库是独立后端 + 独立 App；从“未来我”后端 fork，不共用服务）。

## M0 范围（后端 only）

- 独立服务：端口 **7000**（未来我是 6999），镜像
  `ghcr.io/25283531/penpal-backend:latest`，独立 SQLite 库
  （`penpal.db`）和独立 Fernet 密钥，独立 `/admin`。
- 人物：只上 P01–P05（林澈、沈知遥、陈默、顾晚晴、周叙白），
  人生经历为定稿原文，进回信上下文，绝不现场编造。
  每人 1 张 AI 真人生活照：**M0 只有提示词，photo_url 为空、
  photo_status 为 pending——照片尚未生成，不要对外声称已生成。**
- 写信规则（服务端强制）：每位人物同时只能有 1 封在途信；
  每日发信上限按用户每天计（免费/会员 1 封、高级 5 封），
  发满当天换人也不行；首封当天回，之后免费每 3 天、会员/高级每天。
- 记忆/人格按“用户 × 人物”分开：回忆强化、遗忘淡化、每日整合、
  最多一条感悟；关系阶段按信件数：初识（1–2）→ 熟悉（3–6）→
  默契（7–14）→ 知己（15+）。
- 会员档 free/member/premium（9.9/19.9 元）在代码里，M0 不接支付。
- 积分：写信 +1、读完回信 +1、每日登录 +1（每天只计 1 次）；
  解锁：100 分 1 位、300 分再 1 位；拉新累计 1/10/30/40/50 人
  对应解锁 1/2/3/4/5 位、封顶 5 位（计数器已实现，拉新 UI 不在 M0）。
- 结束关系：30 天内可重连，超 30 天用户侧不可见；服务端加密数据
  一直保留（软删除，绝不硬删信件/记忆），后台看不到任何用户内容。

## 未做（后续步骤）

Android App、真实 AI 照片、支付、拉新 UI、P06–P20 全量人物、
完整未成年人模式（M0 只有注册年龄门：未满 14 岁拒绝注册，
14–17 岁标记 minor_mode）。

## 本地运行

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 7000
# 健康检查：curl http://localhost:7000/api/v1/health
# 后台：打开 http://localhost:7000/admin，首次设置管理员密码，然后配 LLM Key。
```

没有配任何 LLM Key 时，回信不会伪造：`POST /api/v1/letters/process-due`
会返回 `llm_unavailable: true`，信件保持 in_transit（排队状态）。

## 部署到家里路由器（iStoreOS Docker）

```bash
# 在路由器上新建目录 /root/penpal-backend/，把仓库根目录的
# docker-compose.yml 放进去（或把整个仓库传上去，在根目录运行）。
# 镜像由 GitHub Actions 构建并推到 GHCR（amd64 + arm64）：
docker compose pull
docker compose up -d
docker compose logs -f

# 验证：
curl http://10.0.1.1:7000/api/v1/health
# 后台：http://10.0.1.1:7000/admin，首次设置管理员密码，然后配 Key。
# 数据持久化在 ./backend/data（SQLite + 加密密钥），升级时不要删这个目录。
# 密钥文件 backend/data/.encryption.key 要单独备份，丢了数据无法恢复。
# 更新：
docker compose pull
docker compose up -d
```

> 注意：路由器 DNS 之前出过问题（nameserver 是 Tailscale 的
> 100.100.100.100，解析超时）。如果 `docker compose pull` 拉不到
> 镜像，先确认路由器 DNS 能解析 ghcr.io（可用 223.5.5.5 / 8.8.8.8）。

## 测试

```bash
cd backend
python -m pytest tests/ -q   # 22 个测试，全部离线，不调用任何付费 API
```

## API（全部在 `/api/v1` 下，`/admin` 除外）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 + 已配置的供应商 + 端口 7000 |
| POST | `/api/v1/auth/device` | `{device_id, age, emergency_contact?}` → `{token}`；age 必填，未满 14 岁拒绝 |
| POST | `/api/v1/auth/login` | 每日登录 +1 分（每天只计 1 次） |
| GET | `/api/v1/characters`、`/api/v1/characters/{id}` | P01–P05（公开字段；photo_url 为空，photo_status pending） |
| POST | `/api/v1/letters` | `{character_id, text}` 寄信（最长 2000 字；轮次制 + 每日上限 + 名额校验） |
| GET | `/api/v1/letters`、`?character_id=P01` | 我的信件 / 某人物的信件往来 |
| GET | `/api/v1/letters/{id}` | 单封信 |
| POST | `/api/v1/letters/{id}/read` | 读完回信 +1 分（只计 1 次） |
| POST | `/api/v1/letters/process-due` | `{date?}` 生成到期的回信；无 LLM Key 时排队，不伪造 |
| GET/POST | `/api/v1/relationships`、`/end`、`/reconnect` | 结束 / 30 天内重连 |
| GET | `/api/v1/points`、`/api/v1/unlocks` | 积分流水 / 解锁进度 |
| POST | `/api/v1/referrals` | 记录拉新（成功 = 被邀请人写出第一封信） |
| GET | `/api/v1/llm/providers` | 供应商表（千问/混元/硅基流动/智谱；不用豆包） |
| GET | `/api/v1/membership/status` | `{plan: free, phase1_free: true, ...}` |
| GET | `/api/v1/activities`、`/api/v1/messages` | 活动 / 消息（打开 App 时拉取） |

## 隐私红线（硬性）

- 后台**绝对不查看任何单个用户的内容**：不看信件原文、记忆内容，
  不按设备/用户列出，不导出。
- 后台只看汇总数字：设备/信件/回信总数、今日活跃、各人物信件数、
  违规类型数量。
- 用户内容与 AI 答复在 SQLite 里是**加密存储**的（Fernet）。
  解密检查只能用命令行工具（同时需要密钥文件 + 数据库文件），
  每次运行记审计日志，不记内容：

```bash
python3 scripts/decrypt_export.py \
  --db data/penpal.db --key data/.encryption.key \
  --out /tmp/penpal-export.json --operator "检查人姓名"
```

## 目录

| 路径 | 说明 |
|---|---|
| `backend/app/` | 源码（`main.py` 路由，`characters.py` 人物定稿，`database.py` SQLite，`evolution.py` 记忆演变，`context.py` 回信上下文，`llm.py` 多供应商 LLM，`replies.py` 回信调度，`membership.py` 会员档与回信节奏，`content_filter.py` 内容过滤，`crypto.py` 字段级加密，`admin.py` + `admin.html` 后台） |
| `backend/data/` | 数据卷：SQLite（`penpal.db`）、加密密钥（`.encryption.key`，0600）、活动/消息种子 |
| `backend/tests/` | pytest 测试（22 个） |
| `backend/scripts/` | `decrypt_export.py` 解密导出工具（检查专用）、`smoke.sh` curl 冒烟 |
| `.github/workflows/` | `docker.yml`（GHCR 镜像，amd64+arm64）、`backend.yml`（pytest） |
