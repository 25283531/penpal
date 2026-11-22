# 笔友 (Penpal) — 后端 API

FastAPI + SQLite，单容器部署。给 Android App 用：选人物 → 写长信 →
按节奏等回信 → 读回信 → 换人/结束关系。

第一阶段免费，不接支付；所有用户均为免费档。默认端口 **7000**。

## 目录

| 路径 | 说明 |
|---|---|
| `app/` | 源码（见仓库根 README 的目录表） |
| `data/` | 数据卷：SQLite（`penpal.db`）、加密密钥（`.encryption.key`，0600）、活动/消息种子（`activities.json`、`messages.json`） |
| `tests/` | pytest 测试（22 个，全部离线） |
| `scripts/smoke.sh` | curl 冒烟脚本 |
| `scripts/decrypt_export.py` | 解密导出工具（检查专用） |

## 后台管理（Web Admin）

地址：`http://<服务器IP>:7000/admin`

- 首次打开：设置管理员密码（至少 6 位，scrypt 存库），设置后即登录。
- 之后：密码登录，会话 Cookie 7 天有效；右上角可退出。
- 栏目：仪表盘（汇总数字）、人物与合规（各人物信件数 + 违规类型统计）、LLM 配置、会员配置、消息推送、活动管理、记忆演变。
- **所有 Key 都在这里配**：LLM 四家供应商（千问/混元/硅基流动/智谱，不用豆包）、会员价格。密钥存在数据库设置表里，不走环境变量，不进 App。

## 隐私红线（硬性）

- 后台**绝对不查看任何单个用户的内容**：不看信件原文、记忆内容，不按设备/用户列出，不导出。
- 后台只看汇总数字：设备/信件/回信总数、今日活跃、各人物信件数、违规类型数量。
- 用户内容与 AI 答复在 SQLite 里是**加密存储**的（Fernet，见 `app/crypto.py`）。
- **密钥文件要单独备份，丢了数据就永久无法恢复。**

## 写信与回信规则（服务端强制）

- 单封最长 2000 字；每位人物同时只能有 1 封在途信（轮次制）。
- 每日发信上限按用户每天计：免费/会员 1 封，高级会员 5 封；发满当天换人也不行。
- 回信节奏：每位人物的第一封当天回；之后免费每 3 天、会员/高级每天。
- 回信由 LLM 生成（最多 2000 字），过内容过滤，不合格重写一次，
  仍不合格返回 502；没有配任何 LLM Key 时信件保持排队状态，
  `POST /api/v1/letters/process-due` 返回 `llm_unavailable: true`，
  绝不伪造回信。
- 回信是自动的，不靠手动触发：`app/scheduler.py` 在后端进程内起
  一个守护线程（FastAPI lifespan 启动），启动时先跑一次（清掉已
  到期的积压信），之后每小时跑一次，对所有 device 的到期信件执行
  process-due（`app/replies.py: process_all_due_replies`）。没配 LLM
  时信件继续排队、下次重试；LLM 失败的信件留在在途状态、下次重
  试，不丢信。每次运行记日志并写入 `scheduler_runs` 表（只有汇总
  计数），见 `/api/v1/admin/scheduler-runs` 与 dashboard 的
  `scheduler` 一项；间隔可用环境变量 `PENPAL_REPLY_INTERVAL_SECONDS`
  覆盖（默认 3600）。手动 `POST /api/v1/letters/process-due` 仍保留，
  只处理调用者自己的到期信件。
- 关系是知己：内容过滤禁止任何恋人/伴侣/配偶表述；回信标注
  `ai_generated: true`，App 展示时须写“AI 生成”。
- 结束关系：30 天内可重连，超 30 天用户侧不可见；服务端加密数据
  一直保留（软删除），只能用 `scripts/decrypt_export.py` 检查。

## 记忆系统

自研，无开源记忆项目/向量库：记忆按“用户 × 人物”分开（`app/evolution.py`），
回忆强化（进入上下文 recall_count+1、重要度+0.05）、遗忘淡化
（30 天不回忆每天 -0.02，很淡很旧的标记 faded，数据不删）、
每天最多整合一次（提炼持久记忆、最多一条感悟、重写人格介绍）。
关系阶段按信件数：初识（1–2）→ 熟悉（3–6）→ 默契（7–14）→ 知己（15+）。
回信上下文 = 人物设定 + 定稿人生经历 + 人格 + 记忆（前 20 条，排除 faded）
+ 最近信件摘要（不是全文）。

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 7000
# 健康检查：curl http://localhost:7000/api/v1/health
```

## 测试

```bash
python -m pytest tests/ -q
```
