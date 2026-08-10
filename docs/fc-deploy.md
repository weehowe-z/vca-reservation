# 部署到阿里云函数计算（FC）

把每小时监控从 Linux systemd 迁移到阿里云函数计算，免服务器、费用可忽略
（新用户 3 个月免费试用 15 万 CU/月，之后按量付费约 ¥1/月）。

架构：FC 定时触发器每小时调用 `handler` → 读取 VCA 官网 → 对比 OSS 中的上
一次快照 → 有变化时通过 SeaTalk Webhook 通知 → 新快照写回 OSS。

```
┌────────────────┐  每小时   ┌──────────┐   拉取/写回   ┌─────────┐
│ FC 定时触发器   │ ───────► │ handler  │ ◄──────────► │ OSS     │
│ cron 0 0 * * * │          │ (python) │   state.json  │ (状态)  │
└────────────────┘          └────┬─────┘              └─────────┘
                                 │ 有变化时
                                 ▼
                           ┌────────────┐
                           │ SeaTalk    │
                           │ Webhook    │
                           └────────────┘
```

## 一次性准备（控制台操作）

### 1. 创建 OSS Bucket

- 开通 OSS，创建 bucket（任意同地域名称，如 `vca-reservation-state`）
- 读写权限选**私有**
- 记下地域的 endpoint，如 `https://oss-cn-hangzhou.aliyuncs.com`

### 2. 创建 RAM 角色（授权 FC 访问 OSS）

- RAM 控制台 → 角色 → 创建角色 → 阿里云服务 → **函数计算**
- 角色名如 `vca-reservation-fc-role`
- 创建后给角色加自定义策略：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:GetObject", "oss:PutObject"],
      "Resource": "acs:oss:*:*:vca-reservation-state/state.json"
    }
  ]
}
```

### 3. 打包代码

```bash
./scripts/build-fc-package.sh
```

生成 `dist/fc-package.zip`（含代码、入口 handler 和 oss2 依赖，约 26MB）。

## 创建函数

函数计算控制台 → 函数 → 创建函数 → **使用自定义运行时/容器镜像都不需要，
直接选 Python3.12 运行时**：

- 代码包上传：`dist/fc-package.zip`
- **请求处理程序**：`handler.handler`
- **内存规格**：128 MB 足够
- **超时时间**：300 秒（六家店串行请求，默认 60 秒不够）
- **运行角色**：选择上面创建的 `vca-reservation-fc-role`
- 函数创建完成后，在函数配置 → 环境变量里设置：

| 变量 | 值 | 说明 |
|------|-----|------|
| `SEATALK_WEBHOOK_URL` | `https://openapi.seatalk.io/...` | 群机器人 Webhook，建议勾选“加密变量” |
| `VCA_OSS_ENDPOINT` | `https://oss-cn-hangzhou.aliyuncs.com` | OSS endpoint |
| `VCA_OSS_BUCKET` | `vca-reservation-state` | OSS bucket 名 |
| `VCA_OSS_STATE_KEY` | `state.json`（可选） | 状态对象 key，默认 `state.json` |

## 创建定时触发器

函数 → 触发器 → 创建触发器：

- 触发类型：**定时触发器**
- 触发方式：**自定义 Cron**：`0 0 * * * * *`（每小时整点，UTC 时间即北京时间 08:00）

## 验证

1. 在函数概览页点 **测试**，手动触发一次 —— 首次运行会发“初始状态”消息
2. 再次执行测试，应收到“本小时无变化”
3. 观察 OSS bucket 中出现 `state.json`（可下载查看快照）

## 与 Linux 部署的差异

| 项目 | Linux systemd | 函数计算 |
|------|--------------|---------|
| 状态存储 | `/var/lib/vca-reservation/state.json` | OSS 对象 `state.json` |
| 失败告警（连续 3 次） | 支持，状态持久化 | 支持，状态同样持久化 |
| 补跑（关机错过任务） | Persistent=true 开机补跑 | 定时触发天然准时 |
| 并发 | 单进程 | 可并发（每小时一次，无需处理） |
| 费用 | VPS 月费 | ≈¥0-1/月 |

如果之前已在 Linux 部署并积累快照，可把旧 `state.json` 上传到 OSS bucket 的
`state.json`，首次云上触发时会基于旧快照对比，不会误报“初始状态”。

## 卸载 / 迁移回来

- 删除函数和触发器即可停止监控
- 迁移回 Linux：`sudo ./scripts/install.sh` 重新安装，把 OSS 中的 `state.json`
  下载到 `/var/lib/vca-reservation/state.json`（注意权限 `0600`）
- 状态文件格式两端完全兼容（都是 `STATE_VERSION = 1`）