# outlook-k12-imap 第一阶段设计文档

## Context（背景）

用户需要开发一个全新的独立 Web 后台应用 `outlook-k12-imap`，用于管理微软邮箱/账户数据导入、通过 IMAP OAuth2 接收 OpenAI 注册验证码、执行注册流程（含用户资料填写和 K12 工作空间邀请）、日志可视化展示和系统设置。

现有工作区 `openai-cpa` 是一个 FastAPI + Vue.js + Tailwind CSS 的 OpenAI 账户注册自动化平台，已在以下方面提供了成熟参考：
- **微软账户导入**：`email----password----client_id----refresh_token` 四段式格式，`local_mailboxes` 表存储
- **IMAP OAuth2 收信**：通过 refresh_token 换 access_token，XOAUTH2 认证 `outlook.office365.com:993`
- **主题切换**：`body.theme-dark` CSS 类 + localStorage `ui_theme_mode`
- **日志缓存**：deque + `RecentParsedLogCache`，正则解析 `[time] [level] message`
- **侧边栏导航**：Vue `tabs` + `currentTab`，移动端抽屉式

新项目完全独立，自带 SQLite 数据库，不复用 openai-cpa 的代码和数据库。

测试邮箱文件格式确认：`邮箱----密码----client_id----refresh_token`（`----` 分隔，4 字段）。

K12 邀请流程确认：注册成功后获取 Access Token，POST 到 `/backend-api/accounts/{workspaceId}/invites/request` 发送加入申请，默认 workspace ID 为 `631e1603-06cf-4f0b-b79b-d09fbfcfe98d`。

---

## 1. 项目理解与风险边界说明

### 1.1 项目本质
这是一个 **OpenAI 账户批量注册管理后台**，核心链路：
1. 导入微软邮箱账户（含 OAuth2 凭据）
2. 使用微软邮箱通过 IMAP OAuth2 接收 OpenAI 注册验证码
3. 执行注册流程：提交注册 → 接收验证码 → 填写用户资料（用户名+年龄）→ 注册成功
4. 注册成功后执行 K12 工作空间邀请（用 AT 向 workspace 发送 join request）
5. 全程日志可视化

### 1.2 技术栈
- **后端**：Python + FastAPI（与现有项目一致，降低学习成本）
- **前端**：HTML + CSS + JavaScript，使用 Vue 3（CDN）+ Tailwind CSS（CDN），与现有项目风格一致
- **数据库**：SQLite（独立文件 `data/k12.db`）
- **IMAP**：Python 标准库 `imaplib` + OAuth2 XOAUTH2
- **HTTP 客户端**：`httpx`（比 curl_cffi 轻量，无二进制依赖问题）

### 1.3 风险边界
| 风险项 | 说明 | 应对策略 |
|--------|------|----------|
| 敏感信息存储 | refresh_token、password 等凭据明文存储风险 | 预留 AES-256 加密接口，一期使用 base64 混淆 + 密钥配置，二期升级 |
| OpenAI 注册接口合规性 | 真实注册接口可能不合规或资料不足 | 先实现 Mock 注册适配器，保留 Provider 接口，后续可插拔 |
| IMAP 连接稳定性 | outlook.office365.com 可能限流或封禁 | 实现重试机制、连接池、错误分类（abuse_mode / 网络超时 / 认证失败） |
| K12 邀请依赖 chatgpt.com | 需要 chatgpt.com 的 session AT | 后端模拟 `/api/auth/session` 获取 AT，非浏览器脚本方式 |
| 验证码解析规则多样性 | 不同邮件模板可能变化 | 解析规则在 config.yaml 中配置，支持发件人/标题/正文多维度匹配 |
| 并发安全 | 多线程注册时数据库写入冲突 | SQLite WAL 模式 + 写锁 + 连接池 |

---

## 2. 当前工作区代码分析计划

### 2.1 已完成分析的关键模块

| 模块 | 文件路径 | 分析结论 |
|------|----------|----------|
| 主入口 | `wfxl_openai_regst.py` | FastAPI 应用，lifespan 管理，端口扫描，WebSocket 集群通信 |
| 全局状态 | `global_state.py` | `log_history` deque，`VALID_TOKENS` 集合，Bearer token 认证 |
| 配置系统 | `utils/config.py` (975行) | YAML 配置热加载，`reload_all_configs()`，支持 SQLite/MySQL 双引擎 |
| 数据库管理 | `utils/db_manager.py` (1157行) | `local_mailboxes` 表结构：email, password, client_id, refresh_token, status, fission_count, retry_master |
| 微软邮箱服务 | `utils/email_providers/local_microsoft_service.py` (386行) | OAuth2 令牌交换，Graph API 扫信，IMAP XOAUTH2 回退，service abuse mode 检测 |
| 日志缓存 | `utils/log_stream_cache.py` (60行) | 正则 `^\[(.*?)\]\s*\[(.*?)\]\s+(.*)$`，重叠检测优化 |
| 主题切换 | `static/css/style.css` + `static/js/app.js` | `body.theme-dark` CSS 类 + localStorage `ui_theme_mode`，Vue `isDarkMode` |
| 侧边栏 | `index.html` | `tabs` 数组 + `currentTab` 切换，移动端 `mobileNavOpen` 抽屉 |
| 账户导入路由 | `routers/account_routes.py` | `email----password----client_id----refresh_token` 解析，`INSERT OR IGNORE` 去重 |
| 测试模式 | `tests/test_*.py` | unittest + mock/patch，FakeResponse 类模式 |

### 2.2 复用模式清单（参考但不复制代码）
1. **主题切换方案**：CSS 变量 + `body.theme-dark` 类覆盖 + localStorage 持久化
2. **日志解析正则**：`[time] [level] message` 格式 + RecentParsedLogCache 增量解析
3. **IMAP XOAUTH2 认证**：`user={email}\x01auth=Bearer {token}\x01\x01` auth string
4. **OAuth2 令牌交换**：POST refresh_token 到 `login.microsoftonline.com/common/oauth2/v2.0/token`
5. **账户导入格式**：`----` 分隔符解析
6. **Bearer Token 认证**：`verify_token` 依赖注入模式
7. **测试模式**：unittest + FakeResponse + patch

---

## 3. 产品需求拆解

### 3.1 功能模块优先级

| 优先级 | 模块 | 功能点 | 验收标准 |
|--------|------|--------|----------|
| P0 | 微软账户导入 | 批量导入、格式校验、去重、结果统计 | 导入 txt 文件，正确解析 4 字段格式，重复邮箱自动跳过，返回成功/失败计数 |
| P0 | IMAP 验证码接收 | OAuth2 令牌交换、IMAP 连接、邮件搜索、验证码解析 | 使用 refresh_token 获取 access_token，连接 outlook.office365.com:993，搜索 OpenAI 邮件，正则提取验证码 |
| P0 | 注册流程状态机 | 状态流转、Mock 适配器 | 7 个状态正确流转，Mock 适配器可模拟全流程 |
| P0 | 日志可视化 | 实时展示、筛选、分页、详情 | 日志按级别着色，支持按账户/状态/时间/级别筛选，分页查询 |
| P1 | K12 邀请 | workspace ID 配置、join request | 注册成功后自动/手动触发 K12 邀请，默认 workspace ID 可配置 |
| P1 | 用户资料填写 | 用户名+年龄输入 | 验证码验证通过后进入资料填写步骤 |
| P1 | 主题切换 | 深色/浅色 | 与现有项目一致的 `body.theme-dark` 方案 |
| P2 | 系统设置 | K12 配置、注册适配器配置 | 可在界面修改 K12 workspace ID 等配置并热加载 |
| P2 | 敏感信息加密 | 预留加密方案 | 一期 base64 混淆，预留 AES 接口 |

### 3.2 注册流程状态机

```
待注册(pending)
    ↓ [自动] 触发注册
提交中(submitting)
    ↓ [自动] 提交注册请求
等待验证码(waiting_code)
    ↓ [自动] IMAP 轮询收信 + 自动解析验证码
验证码已接收(code_received)
    ↓ [自动] 自动填入验证码 + 自动生成用户资料(用户名/年龄)
资料提交中(submitting_profile)
    ↓ [自动] 资料提交成功
K12邀请中(k12_inviting)
    ↓ [自动] K12 join request 发送
注册成功(success)
    
任意状态 → 注册失败(failed)
```
注：全程全自动，创建任务后无需人工干预。用户资料(用户名/年龄)在创建任务时预设或自动随机生成。
各步骤也保留手动 API 端点供异常重试使用。

### 3.3 用户流程
1. 管理员登录后台 → 输入密码 → 获取 Bearer Token
2. 进入「微软邮箱批量导入」→ 上传/粘贴账户数据 → 校验格式 → 导入成功
3. 进入「控制台日志」→ 选择账户 → 启动注册 → 观察日志实时更新
4. 注册流程全自动执行（无需人工干预）：提交 → 等待验证码 → IMAP 自动收信 → 自动解析验证码 → 自动填入资料 → 自动 K12 邀请
5. 进入「设置」→ 配置 K12 workspace ID、注册适配器等参数

---

## 4. 页面原型文字版

### 4.1 全局布局
```
┌─────────────────────────────────────────────────┐
│ [☰汉堡]  outlook-k12-imap   [☀/🌙主题] [👤退出]  │  ← 顶部 Header
├──────────┬──────────────────────────────────────┤
│          │                                      │
│ 控制台   │                                      │
│ 日志     │         主内容区                      │
│          │         (根据左侧选中项切换)             │
│ 微软邮箱 │                                      │
│ 批量导入 │                                      │
│          │                                      │
│ 设置     │                                      │
│          │                                      │
└──────────┴──────────────────────────────────────┘
```

### 4.2 登录页
- 居中卡片式布局
- 标题：outlook-k12-imap 管理后台
- 密码输入框 + 登录按钮
- 底部版本号

### 4.3 控制台日志页
```
┌─────────────────────────────────────────────────┐
│ 筛选栏: [账户▼] [状态▼] [级别▼] [日期] [搜索]  │
├─────────────────────────────────────────────────┤
│ 任务进度: ████████░░ 80%  成功8/失败2/总计10    │
├─────────────────────────────────────────────────┤
│ [10:30:01] [INFO]  账号 xxx@outlook.com 开始注册 │
│ [10:30:05] [INFO]  提交注册请求...               │
│ [10:30:10] [WARN]  等待验证码中...(第3次轮询)    │
│ [10:30:15] [SUCCESS] 收到验证码: 123456          │
│ [10:30:20] [INFO]  提交用户资料: 用户名/年龄      │
│ [10:30:25] [ERROR] K12 邀请失败: HTTP 403        │
│ ...                                              │
├─────────────────────────────────────────────────┤
│ 分页: < 1 2 3 ... > 每页50条                     │
└─────────────────────────────────────────────────┘
```
- 日志按级别着色：INFO 蓝色、SUCCESS 绿色、WARN 橙色、ERROR 红色
- 支持点击日志查看详情（完整堆栈/上下文）
- 准实时刷新（轮询/SSE）

### 4.4 微软邮箱批量导入页
```
┌─────────────────────────────────────────────────┐
│ 导入区域                                          │
│ ┌─────────────────────────────────────────────┐ │
│ │  [文件上传区域] 或 [文本框粘贴]               │ │
│ │  格式: 邮箱----密码----client_id----refresh   │ │
│ │  每行一条，# 开头为注释                       │ │
│ └─────────────────────────────────────────────┘ │
│ [选择文件] [粘贴文本] [开始导入]                  │
├─────────────────────────────────────────────────┤
│ 导入结果: ✅成功 8 条  ⚠️重复 1 条  ❌失败 0 条  │
├─────────────────────────────────────────────────┤
│ 已导入账户列表                                    │
│ ┌──────┬───────────┬──────┬────────┬──────┬───┐│
│ │ ID   │ 邮箱       │ 状态 │ 创建时间│ 操作 │   ││
│ ├──────┼───────────┼──────┼────────┼──────┼───┤│
│ │ 1    │ xxx@...    │ 待用 │ 07-02   │[删除]│   ││
│ │ 2    │ yyy@...    │ 占用 │ 07-02   │[删除]│   ││
│ └──────┴───────────┴──────┴────────┴──────┴───┘│
│ 分页: < 1 2 3 >  [搜索] [批量删除]               │
└─────────────────────────────────────────────────┘
```
- 状态：待用(0) / 占用中(1) / 已用(2) / 异常(3)
- 密码/refresh_token 默认掩码显示，点击可切换

### 4.5 设置页
```
┌─────────────────────────────────────────────────┐
│ K12 配置                                          │
│   Workspace ID: [631e1603-06cf-4f0b-b79b-...]    │
│   邀请方式:     [request / accept]               │
│   自动邀请:     [☑ 注册成功后自动邀请]            │
│                                                   │
│ 注册配置                                          │
│   注册适配器:   [Mock(默认) / OpenAI]             │
│   并发数:       [1]                              │
│                                                   │
│ [保存配置] [保存并热重载]                         │
└─────────────────────────────────────────────────┘
```
注：IMAP 连接参数（outlook.office365.com:993）和验证码解析规则（发件人/标题/正则）
直接硬编码在服务层代码和 config.yaml 中，不在 UI 设置页暴露。

---

## 5. 数据库表设计草案

### 5.1 `ms_accounts`（微软邮箱账户表）
```sql
CREATE TABLE IF NOT EXISTS ms_accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,        -- 微软邮箱地址
    password      TEXT,                         -- 邮箱密码（加密预留）
    client_id     TEXT,                         -- OAuth2 应用 ID
    refresh_token TEXT,                         -- OAuth2 刷新令牌（加密预留）
    status        INTEGER DEFAULT 0,            -- 0=待用 1=占用中 2=已用 3=异常
    remark        TEXT DEFAULT '',              -- 备注
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 `reg_tasks`（注册任务表）
```sql
CREATE TABLE IF NOT EXISTS reg_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL,           -- 关联 ms_accounts.id
    email           TEXT NOT NULL,              -- 冗余邮箱便于查询
    status          TEXT DEFAULT 'pending',     -- pending/submitting/waiting_code/
                                                 -- code_received/submitting_profile/
                                                 -- k12_inviting/success/failed
    verify_code     TEXT,                        -- 接收到的验证码
    username        TEXT,                        -- 用户资料-用户名
    age             INTEGER,                     -- 用户资料-年龄
    access_token    TEXT,                        -- 注册成功后的 AT
    k12_status      TEXT DEFAULT 'pending',     -- pending/requested/accepted/failed
    k12_workspace_id TEXT,                       -- K12 workspace ID
    error_message   TEXT,                        -- 失败原因
    retry_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES ms_accounts(id)
);
```

### 5.3 `reg_logs`（注册日志表）
```sql
CREATE TABLE IF NOT EXISTS reg_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER,                         -- 关联 reg_tasks.id（可为空=系统日志）
    account_id  INTEGER,                         -- 关联 ms_accounts.id（可为空）
    email       TEXT,                            -- 冗余邮箱便于筛选
    level       TEXT NOT NULL,                   -- INFO/SUCCESS/WARN/ERROR/DEBUG
    message     TEXT NOT NULL,                   -- 日志正文
    detail      TEXT,                            -- 详情（堆栈/上下文 JSON）
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_logs_task ON reg_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_logs_level ON reg_logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_created ON reg_logs(created_at);
```

### 5.4 `system_settings`（系统设置表）
```sql
CREATE TABLE IF NOT EXISTS system_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,                            -- JSON 序列化值
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.5 索引策略
- `ms_accounts.email` — UNIQUE 索引（去重 + 查询）
- `reg_tasks.status` — 普通索引（状态筛选）
- `reg_tasks.account_id` — 普通索引（关联查询）
- `reg_logs.task_id` / `reg_logs.level` / `reg_logs.created_at` — 复合查询索引

---

## 6. RESTful API 设计草案

### 6.1 认证模块
| 方法 | 路径 | 说明 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/auth/login` | 登录获取 Token | `{"password": "xxx"}` | `{"status":"success","token":"xxx"}` |
| POST | `/api/auth/logout` | 退出登录 | - | `{"status":"success"}` |

### 6.2 微软账户模块
| 方法 | 路径 | 说明 | 请求/参数 | 响应 |
|------|------|------|-----------|------|
| GET | `/api/accounts` | 分页查询账户 | `?page=1&page_size=50&search=xxx&status=0` | `{"data":[...],"total":100,"page":1}` |
| POST | `/api/accounts/import` | 批量导入 | `{"raw_text":"email----pwd----cid----rt"}` | `{"status":"success","count":8,"duplicated":1,"failed":0}` |
| DELETE | `/api/accounts` | 批量删除 | `{"ids":[1,2,3]}` | `{"status":"success"}` |
| GET | `/api/accounts/{id}` | 账户详情 | - | `{"id":1,"email":"...","status":0,...}` |
| PATCH | `/api/accounts/{id}` | 更新账户 | `{"status":0,"remark":"xxx"}` | `{"status":"success"}` |

### 6.3 注册任务模块
| 方法 | 路径 | 说明 | 请求/参数 | 响应 |
|------|------|------|-----------|------|
| GET | `/api/tasks` | 任务列表 | `?page=1&page_size=50&status=pending&email=xxx` | `{"data":[...],"total":10}` |
| POST | `/api/tasks` | 创建注册任务 | `{"account_ids":[1,2],"username":"xxx","age":25}` | `{"status":"success","task_ids":[1,2]}` |
| GET | `/api/tasks/{id}` | 任务详情 | - | `{"id":1,"status":"waiting_code",...}` |
| POST | `/api/tasks/{id}/start` | 启动任务 | - | `{"status":"success"}` |
| POST | `/api/tasks/{id}/stop` | 停止任务 | - | `{"status":"success"}` |
| POST | `/api/tasks/{id}/retry` | 重试任务 | - | `{"status":"success"}` |
| POST | `/api/tasks/{id}/verify_code` | 手动补交验证码（异常重试用） | `{"code":"123456"}` | `{"status":"success"}` |
| POST | `/api/tasks/{id}/profile` | 手动补交用户资料（异常重试用） | `{"username":"xxx","age":25}` | `{"status":"success"}` |
| POST | `/api/tasks/{id}/k12_invite` | 手动触发 K12 邀请（异常重试用） | `{"workspace_id":"xxx"}` | `{"status":"success"}` |

### 6.4 日志模块
| 方法 | 路径 | 说明 | 请求/参数 | 响应 |
|------|------|------|-----------|------|
| GET | `/api/logs` | 分页查询日志 | `?page=1&page_size=50&level=ERROR&task_id=1&email=xxx&start=2026-07-01&end=2026-07-02` | `{"data":[...],"total":100}` |
| GET | `/api/logs/{id}` | 日志详情 | - | `{"id":1,"level":"ERROR","message":"...","detail":"..."}` |
| GET | `/api/logs/stream` | SSE 实时日志流 | `?task_id=1` (EventSource) | SSE 事件流 |
| GET | `/api/logs/stats` | 日志统计 | `?task_id=1` | `{"total":100,"INFO":80,"ERROR":5,...}` |

### 6.5 设置模块
| 方法 | 路径 | 说明 | 请求/参数 | 响应 |
|------|------|------|-----------|------|
| GET | `/api/settings` | 获取全部设置 | - | `{"k12":{...},"registration":{...}}` |
| PUT | `/api/settings` | 更新设置 | `{"k12":{...},"registration":{...}}` | `{"status":"success"}` |
| POST | `/api/settings/reload` | 热重载配置 | - | `{"status":"success"}` |

### 6.6 响应格式规范
```json
{
    "status": "success" | "error" | "warning",
    "message": "描述信息",
    "data": { ... }
}
```
所有接口需要 Bearer Token 认证（除 `/api/auth/login`），Header: `Authorization: Bearer xxx`

---

## 7. TDD 测试计划

### 7.1 测试文件规划
```
tests/
├── test_account_import.py      # 账户导入解析
├── test_imap_service.py         # IMAP OAuth2 收信
├── test_code_parser.py          # 验证码正则解析
├── test_registration_flow.py    # 注册状态机流转
├── test_k12_invite.py           # K12 邀请流程
├── test_log_service.py          # 日志写入查询
├── test_api_accounts.py         # 账户 API 路由
├── test_api_tasks.py            # 任务 API 路由
├── test_api_logs.py             # 日志 API 路由
├── test_api_settings.py         # 设置 API 路由
└── test_auth.py                 # 认证模块
```

### 7.2 核心测试用例

#### test_account_import.py
- ✅ 正确解析 `email----password----client_id----refresh_token` 四段格式
- ✅ 跳过空行和 `#` 注释行
- ✅ 字段不足时跳过并记录错误
- ✅ 重复邮箱自动去重（INSERT OR IGNORE）
- ✅ 返回正确的成功/重复/失败计数
- ✅ 特殊字符邮箱处理（+ 别名）

#### test_imap_service.py
- ✅ refresh_token 换取 access_token 成功
- ✅ token 交换失败时抛出正确异常
- ✅ IMAP XOAUTH2 认证字符串构造正确
- ✅ 搜索 INBOX 和 Junk 文件夹
- ✅ service abuse mode 检测和状态标记
- ✅ 网络超时重试机制

#### test_code_parser.py
- ✅ 6 位数字验证码正则匹配
- ✅ 发件人关键词过滤（openai.com）
- ✅ 标题关键词过滤
- ✅ 多种邮件正文格式解析（HTML/纯文本）
- ✅ 无匹配时返回空结果

#### test_registration_flow.py
- ✅ 全自动状态机：pending → submitting → waiting_code 正确流转
- ✅ 全自动状态机：waiting_code → code_received → submitting_profile 正确流转
- ✅ 全自动状态机：submitting_profile → k12_inviting → success 正确流转
- ✅ 任意状态 → failed 的异常流转
- ✅ 非法状态跳转被拒绝
- ✅ Mock 适配器返回模拟验证码
- ✅ 用户资料自动生成（随机用户名 + 18-35 随机年龄）
- ✅ 全流程 pending → success 无人工干预

#### test_k12_invite.py
- ✅ 正确构造 join request 请求
- ✅ workspace ID 格式校验
- ✅ AT 失效时自动刷新
- ✅ HTTP 403/401 错误处理
- ✅ 默认 workspace ID 使用

#### test_log_service.py
- ✅ 日志写入数据库
- ✅ 按级别筛选查询
- ✅ 按任务 ID 筛选查询
- ✅ 按时间范围筛选查询
- ✅ 分页查询正确
- ✅ 日志统计接口

### 7.3 测试执行命令
```bash
cd f:\game\outlook-k12-imap
python -m pytest tests/ -v
# 或
python -m unittest discover tests/ -v
```

---

## 8. 开发任务拆分与执行 Loop

### 8.1 项目目录结构
```
f:\game\outlook-k12-imap\
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理
│   ├── database.py                # SQLite 初始化 + 连接管理
│   ├── auth.py                    # Bearer Token 认证
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth_routes.py         # 登录/退出
│   │   ├── account_routes.py      # 微软账户导入管理
│   │   ├── task_routes.py         # 注册任务管理
│   │   ├── log_routes.py          # 日志查询/SSE
│   │   └── settings_routes.py     # 系统设置
│   └── services/
│       ├── __init__.py
│       ├── account_service.py     # 账户导入解析逻辑
│       ├── imap_service.py        # IMAP OAuth2 收信
│       ├── code_parser.py         # 验证码解析
│       ├── registration_provider.py  # 注册 Provider 接口 + Mock 实现
│       ├── k12_service.py         # K12 邀请
│       ├── state_machine.py       # 注册状态机
│       └── log_service.py         # 日志写入查询
├── static/
│   ├── css/
│   │   ├── style.css             # 主样式 + theme-dark
│   │   └── index.css             # 页面专属样式
│   └── js/
│       ├── app.js                # Vue 应用主逻辑
│       ├── tailwind.min.js       # Tailwind CSS CDN
│       └── vue.global.js         # Vue 3 CDN
├── tests/                         # 测试文件（见 7.1）
├── data/                          # 数据目录
│   └── k12.db                    # SQLite 数据库（自动生成）
├── index.html                    # 前端入口
├── config.yaml                   # 配置文件
├── requirements.txt              # Python 依赖
├── README.md
├── 缺陷记录.md                    # Bug 记录
└── 注册流程问题记录.md            # 注册流程 Bug 记录
```

### 8.2 任务拆分与依赖

#### Task 1: 项目骨架搭建（无依赖）
- 创建目录结构
- `requirements.txt`：fastapi, uvicorn, httpx, pydantic, pyyaml
- `app/main.py`：FastAPI 应用入口，静态文件挂载，路由注册
- `app/config.py`：YAML 配置加载
- `app/database.py`：SQLite 初始化，WAL 模式，4 张表建表
- `config.yaml`：默认配置
- **验收**：`python -m app.main` 能启动，访问 `http://127.0.0.1:8000` 返回页面

#### Task 2: 认证模块（依赖 Task 1）
- `app/auth.py`：Bearer Token 生成/验证，密码登录
- `routers/auth_routes.py`：POST `/api/auth/login`，POST `/api/auth/logout`
- **TDD**：先写 `test_auth.py`，再实现
- **验收**：登录返回 token，后续请求带 token 通过认证

#### Task 3: 微软账户导入服务（依赖 Task 1）
- `services/account_service.py`：解析 `----` 格式，校验，去重，统计
- `routers/account_routes.py`：GET/POST/DELETE/PATCH 账户接口
- **TDD**：先写 `test_account_import.py` 和 `test_api_accounts.py`
- **验收**：导入测试邮箱文件全部 9 条成功，重复导入返回 duplicated 计数

#### Task 4: IMAP OAuth2 收信服务（依赖 Task 1）
- `services/imap_service.py`：refresh_token 换 access_token，XOAUTH2 认证，邮件搜索
- `services/code_parser.py`：正则解析验证码
- **TDD**：先写 `test_imap_service.py` 和 `test_code_parser.py`
- **验收**：Mock HTTP 返回 token，Mock IMAP 返回邮件，验证码正确解析

#### Task 5: 注册状态机 + Mock 适配器（依赖 Task 3, 4）
- `services/state_machine.py`：7 状态全自动流转，非法跳转拒绝
- `services/registration_provider.py`：Provider 抽象接口 + Mock 实现，含自动生成用户资料(随机用户名+18-35随机年龄)
- **TDD**：先写 `test_registration_flow.py`
- **验收**：Mock 适配器模拟全自动全流程状态流转，pending → success 无需人工干预

#### Task 6: K12 邀请服务（依赖 Task 5）
- `services/k12_service.py`：构造 join request，AT 获取，错误处理
- **TDD**：先写 `test_k12_invite.py`
- **验收**：Mock HTTP 返回 200，K12 邀请状态正确更新

#### Task 7: 注册任务路由（依赖 Task 5, 6）
- `routers/task_routes.py`：任务 CRUD，启动(全自动执行)/停止/重试，手动补交验证码/资料(仅异常重试用)
- **TDD**：先写 `test_api_tasks.py`
- **验收**：创建任务 → 启动 → 全自动状态流转至 success；手动端点可覆盖异常步骤

#### Task 8: 日志服务 + 路由（依赖 Task 1）
- `services/log_service.py`：日志写入，分页查询，统计
- `routers/log_routes.py`：GET 分页查询，GET 详情，SSE 实时流，统计
- **TDD**：先写 `test_log_service.py` 和 `test_api_logs.py`
- **验收**：写入日志 → 分页查询 → 按级别/任务/时间筛选正确

#### Task 9: 设置模块（依赖 Task 1）
- `routers/settings_routes.py`：GET/PUT 设置，热重载
- **TDD**：先写 `test_api_settings.py`
- **验收**：修改 K12 workspace ID → 保存 → 热重载生效

#### Task 10: 前端页面实现（依赖 Task 2-9 全部 API）
- `index.html`：Vue 应用骨架，侧边栏 + 主内容区
- `static/css/style.css`：主样式 + theme-dark 深色模式
- `static/css/index.css`：页面专属样式
- `static/js/app.js`：Vue 应用逻辑，路由切换，API 调用
- **验收**：三个页面完整可用，主题切换正常，loading/empty/error/success 状态完整

#### Task 11: 集成测试 + Bug 修复（依赖 Task 10）
- 端到端测试：导入账户 → 创建任务 → 启动注册 → 查看日志 → K12 邀请
- 记录 Bug 到 `缺陷记录.md`
- 回归修复
- **验收**：全流程跑通，无阻塞性 Bug

### 8.3 每个 Task 的 Loop 执行流程
```
1. 明确任务目标和验收标准
2. 编写测试用例（tests/test_xxx.py）
3. 运行测试 → 预期全部失败（红灯）
4. 实现最小可用功能
5. 运行测试 → 预期全部通过（绿灯）
6. 如果失败 → 记录 Bug 到 Markdown → 修复 → 回归测试
7. 更新任务状态
8. Git commit: `feat: xxx` / `test: xxx` / `fix: xxx`
9. 进入下一个 Task
```

### 8.4 Git Commit 规范
- `feat: 实现微软账户批量导入服务`
- `test: 添加账户导入解析测试用例`
- `fix: 修复 IMAP 连接超时未重试问题`
- `docs: 更新 README 使用说明`
- `refactor: 重构注册状态机状态枚举`

---

## 9. 需要我审核或确认的问题清单

### 9.1 已确认事项
- ✅ 全新独立项目，不复用 openai-cpa 代码和数据库
- ✅ 注册目标为 OpenAI 账户注册
- ✅ IMAP 仅使用 OAuth2（refresh_token + client_id → access_token → XOAUTH2）
- ✅ 独立 SQLite 数据库
- ✅ 验证码后需要输入用户资料（用户名 + 年龄）
- ✅ K12 邀请流程，默认 workspace ID: `631e1603-06cf-4f0b-b79b-d09fbfcfe98d`
- ✅ 测试邮箱格式：`email----password----client_id----refresh_token`
- ✅ 注册流程为全自动模式：创建任务后自动走完全流程，无需人工干预
- ✅ 用户资料自动生成：用户名=随机字符串，年龄=18-35随机（创建任务时也可批量指定）
- ✅ 各步骤保留手动 API 端点供异常重试使用
- ✅ 项目创建路径：`f:\game\outlook-k12-imap\`（与 openai-cpa 平级）
- ✅ 登录密码：初始密码 `admin`，可在设置中修改
- ✅ K12 邀请方式：默认 `request`（主动申请加入），设置中可切换为 `accept`
- ✅ K12 AT 获取方式：使用注册成功后获取的 access_token 直接作为 Bearer Token 调用 K12 API
- ✅ 敏感信息加密方案：一期明文存储 + 预留加密接口字段，二期实现 AES-256
- ✅ 日志实时推送方式：SSE 为主 + 轮询降级

### 9.2 待确认问题

无 — 所有问题已全部确认。

---

## 验证方案

### 端到端测试流程
1. 启动服务：`python -m app.main` → 访问 `http://127.0.0.1:8000`
2. 登录：输入密码 `admin` → 获取 Token
3. 导入账户：粘贴测试邮箱文件内容 → 确认 9 条全部导入成功
4. 创建注册任务：选择账户 → 启动（用户资料自动生成，也可预设）
5. 观察日志：控制台日志页实时显示注册流程状态流转
6. 验证 Mock 流程：pending → submitting → waiting_code → code_received → submitting_profile → k12_inviting → success
7. 切换主题：深色/浅色切换正常，刷新后保持
8. 运行全部测试：`python -m pytest tests/ -v` 全绿

### 关键文件清单
- 后端入口：`app/main.py`
- 数据库初始化：`app/database.py`
- IMAP 服务：`app/services/imap_service.py`
- 注册状态机：`app/services/state_machine.py`
- K12 服务：`app/services/k12_service.py`
- 前端入口：`index.html`
- 前端逻辑：`static/js/app.js`
- 主题样式：`static/css/style.css`
- 配置文件：`config.yaml`
- 测试目录：`tests/`
- Bug 记录：`缺陷记录.md`、`注册流程问题记录.md`