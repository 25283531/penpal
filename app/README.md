# 笔友 (Penpal) — Android App

慢信 + 虚拟笔友：选一位虚拟知己（P01–P05），慢慢写信（最多 2000 字），
慢慢等回信。第一封当天回，之后免费每 3 天回一封。Kotlin + Jetpack Compose，
从“未来我” App fork 而来，但**不共用服务端、不共用包名**。

- 包名：`com.junze.penpal`；应用名：笔友
- 服务端地址写死在代码里（`ApiClient.DEFAULT_BASE_URL`）：
  `https://penpal.250886.xyz:32123` —— App 里没有任何地方可以输入或
  修改服务器地址。
- 首次启动先用设备号匿名注册（`POST /api/v1/auth/device`），不注册邮箱
  也可以正常写信、读信；邮箱注册/验证后才能改密、找回密码。

## 状态（2026-11-20）

- 服务端地址**尚未接通**（端口 32123 未响应）。App 能编译、能装，
  联网失败时显示「服务器未连接，请稍后再试」，不谎称已连通。
- 邮箱注册/验证码/找回密码接口（`auth/register`、`auth/send-code`、
  `auth/verify`、`auth/login-email`、`auth/change-password`、
  `auth/forgot-password`、`auth/reset-password`、`auth/captcha`、
  `privacy`）已按后端实际代码（`backend/app/main.py` + `email_auth.py`，
  2026-11-20 已读）对齐，不是按约定猜的：
  - 注册/邮箱登录返回扁平对象 `{token, device_id, email, email_verified}`，
    没有嵌套 `user`，注册也不发邮件；
  - 验证是 `send-code {email, purpose:"verify"}` → `verify {email, code}`；
  - 验证码是 PNG 图片，`captcha_token` 在响应头 `X-Captcha-Token`；
  - 改密 `{current_password?, code?, new_password}`，已验证用户走密码；
  - 注意：M0 的 `POST /api/v1/auth/login` 是每日登录积分接口（无 body），
    不是邮箱登录；邮箱登录用的是 `POST /api/v1/auth/login-email`。
  - 注册会在服务端生成一个新的设备号（`email-…`），与匿名设备号不同，
    匿名期的信件/积分不会自动带到邮箱账号下——这是后端行为。

## 构建

```bash
cd app
gradle assembleDebug   # 需要 JDK 17 + Android SDK（API 34）
```

GitHub Actions（`.github/workflows/android.yml`）每次改 `app/` 就构建，
产物为 `penpal-debug-apk`。本地没有 JDK/SDK 时不要硬编，靠 CI。

## 目录

| 路径 | 说明 |
|---|---|
| `app/src/main/java/com/junze/penpal/data/api/` | `ApiClient`（写死的服务端地址）、`ApiService`（全部接口 + DTO） |
| `app/src/main/java/com/junze/penpal/data/repository/` | `PenpalRepository`（设备认证、401 重试一次、Room 缓存） |
| `app/src/main/java/com/junze/penpal/data/local/` | Room 缓存（人物、信件） |
| `app/src/main/java/com/junze/penpal/data/prefs/` | DataStore（设备号、token、邮箱、验证状态） |
| `app/src/main/java/com/junze/penpal/ui/home/` | 首页（验证横幅、人物入口、最近的信、积分） |
| `app/src/main/java/com/junze/penpal/ui/letters/` | 笔友列表、人物详情、写信（2000 字计数）、信件详情（AI 生成标签、标记已读） |
| `app/src/main/java/com/junze/penpal/ui/account/` | 注册（邮箱+密码+年龄+图形验证码+隐私勾选）、登录、验证邮箱、忘记密码 |
| `app/src/main/java/com/junze/penpal/ui/me/` | 会员、积分、解锁进度、改密（仅已验证邮箱可见表单） |
| `app/src/main/java/com/junze/penpal/ui/privacy/` | 隐私协议（服务端拉取，离线用内置文本） |
| `app/src/main/java/com/junze/penpal/worker/` | 本地每日提醒（8:00 / 20:00，无服务端推送） |
