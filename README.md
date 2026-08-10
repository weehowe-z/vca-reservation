# vca-reservation

每小时检查 Van Cleef & Arpels 日本官网中大阪、神户、广岛六家店的“作品を検討 →
ジュエリー”预约号源，并通过 SeaTalk 群组 Webhook 通知。

- 每次成功检查都会发消息；没有变化也会发送“本小时无变化”。
- 相比上一次成功快照有新增或减少时，消息会 `@all`。
- 首次运行只建立基线，不 `@all`。
- 连续三次查询失败时告警一次；恢复且号源有变化时仍会 `@all`。
- 只读取公开号源，不预约、不填写个人信息，也不查询售后服务时段。

## 监控门店

- 大阪：阪急梅田本店、大阪髙島屋店、心斎橋店
- 神户：大丸神户店、神户阪急店
- 广岛：福屋八丁堀本店

## 部署方式

- **Linux systemd**：见下方「Linux 安装」，适合已有服务器
- **阿里云函数计算（免服务器，≈¥0-1/月）**：见 [docs/fc-deploy.md](docs/fc-deploy.md)

## Linux 安装

需要 Python 3.11+、`systemd` 和 root 权限。先取得本仓库并进入目录，然后创建只由
root 可读的配置文件：

```bash
sudo install -m 0600 deploy/vca-reservation.env.example /etc/vca-reservation.env
sudoedit /etc/vca-reservation.env
```

把 `SEATALK_WEBHOOK_URL` 的占位值替换成 SeaTalk 群组机器人提供的完整 Webhook URL，
再执行：

```bash
sudo ./scripts/install.sh
```

Webhook URL 相当于密码，不要提交到 Git、截图或贴到日志中。SeaTalk 页面上的“签名密钥”
用于互动卡片事件回调，本项目只向 Incoming Webhook 发文本，因此不需要也不应配置该密钥。

安装脚本会创建专用用户 `vca-reservation`，把程序安装到
`/opt/vca-reservation/.venv`，并启用每小时执行且支持开机补跑的 systemd timer。状态文件默认位于
`/var/lib/vca-reservation/state.json`。

## 验证与日常操作

只读取官网并在终端显示六家店的当前结果，不发 SeaTalk：

```bash
/opt/vca-reservation/.venv/bin/vca-reservation smoke
```

单独验证 Webhook（不 `@all`）：

```bash
sudo systemd-run --wait --pipe \
  --property=EnvironmentFile=/etc/vca-reservation.env \
  /opt/vca-reservation/.venv/bin/vca-reservation test-webhook
```

立即执行一次正式检查。首次会发送“初始状态”，之后无变化会发送“本小时无变化”：

```bash
sudo systemctl start vca-reservation.service
```

查看定时器和最近日志：

```bash
systemctl list-timers vca-reservation.timer --no-pager
systemctl status vca-reservation.timer --no-pager
sudo journalctl -u vca-reservation.service -n 100 --no-pager
```

`vca-reservation.service` 是一次性任务，不是常驻进程；每小时由 timer 拉起一次。机器关机期间
错过的任务会在下次启动后补跑一次。

## 更新

在仓库中拉取新代码并重新运行安装脚本；配置和历史快照不会被覆盖：

```bash
git pull --ff-only
sudo ./scripts/install.sh
```

## 卸载

默认保留 Webhook 配置和历史快照，便于以后重装：

```bash
sudo ./scripts/uninstall.sh
```

明确希望同时永久删除 `/etc/vca-reservation.env`、`/var/lib/vca-reservation` 和专用用户时：

```bash
sudo ./scripts/uninstall.sh --purge
```

## 本地开发

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

测试不会访问官网或 SeaTalk。真实读取和真实消息必须分别显式执行 `smoke` 与
`test-webhook`。
