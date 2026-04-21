# 热点雷达监控

这个子项目监控 Binance Web3 Topic Rush / 热点雷达，并推送热点主题消息。
目录内已经包含运行所需代码和配置示例，复制 `topic-rush-monitor/` 即可单独部署。

默认会同时监控：

- `Latest`
- `Rising`
- `Viral`

## 运行

进入目录后使用：

```bash
npm run snapshot
npm run monitor
```

也可以按榜单单独启动：

```bash
npm run latest-monitor
npm run rising-monitor
npm run viral-monitor
```

默认状态文件会写到当前项目自己的 `.state/binance-topic-rush-bsc.json`。
本地 Telegram 配置默认读取当前目录下的 `.env`。
可先复制 `.env.example` 为 `.env`，再填入你自己的配置。

## 常用参数

```bash
python3 binance_topic_rush_monitor.py --once
python3 binance_topic_rush_monitor.py --feeds topic-latest
python3 binance_topic_rush_monitor.py --telegram-test-message "topic rush test"
```

脚本会优先读取当前目录下的 `.env`。

如果你想使用项目专用的 Telegram 环境变量名，也可以使用这些环境变量：

```bash
TOPIC_TELEGRAM_BOT_TOKEN=xxx TOPIC_TELEGRAM_CHAT_ID=yyy npm run monitor
```

## 服务器部署说明

下面这份说明按常见 Linux 云服务器编写，默认使用 `systemd` 常驻运行。

### 1. 环境要求

- `python3` 3.9 或更高版本
- 可选：`npm`

这个项目没有额外的 Python 三方依赖；服务器上只要有 Python，就可以直接运行 `python3 binance_topic_rush_monitor.py`。

### 2. 上传文件

如果你只部署热点雷达，上传整个 `topic-rush-monitor/` 目录即可，例如放到：

```bash
/opt/topic-rush-monitor
```

目录里至少需要这些文件：

- `binance_topic_rush_monitor.py`
- `.env`

如果你想继续用 `npm run monitor` 这种方式启动，再额外带上 `package.json`。

`.state/` 不需要预先创建，脚本首次运行时会自动生成。

### 3. 配置 `.env`

先复制模板：

```bash
cp .env.example .env
```

再填写你自己的 Telegram 配置：

```bash
TOPIC_TELEGRAM_BOT_TOKEN=your_topic_bot_token
TOPIC_TELEGRAM_CHAT_ID=your_topic_chat_id
```

推荐继续使用 `TOPIC_TELEGRAM_*` 这组变量，配置含义会更直观。

### 4. 首次手动验证

先在服务器里进入目录：

```bash
cd /opt/topic-rush-monitor
```

先发一条 Telegram 测试消息：

```bash
python3 binance_topic_rush_monitor.py --telegram-test-message "topic rush test"
```

再跑一次单次抓取，确认接口和状态文件都正常：

```bash
python3 binance_topic_rush_monitor.py --once
```

如果想只验证某一个榜单，可以这样跑：

```bash
python3 binance_topic_rush_monitor.py --feeds topic-latest --once
```

### 5. 直接前台运行

如果你只是临时跑一下，可以直接执行：

```bash
python3 binance_topic_rush_monitor.py
```

默认会同时监控：

- `topic-latest`
- `topic-rising`
- `topic-viral`

### 6. 用 systemd 常驻

新建服务文件：

```bash
sudo nano /etc/systemd/system/topic-rush-monitor.service
```

写入下面内容：

```ini
[Unit]
Description=Binance Web3 Topic Rush Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/topic-rush-monitor
ExecStart=/usr/bin/python3 /opt/topic-rush-monitor/binance_topic_rush_monitor.py
Restart=always
RestartSec=5
User=deploy

[Install]
WantedBy=multi-user.target
```

把 `User=deploy` 改成你的实际运行用户，并确保该用户对部署目录有读写权限。

然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now topic-rush-monitor
sudo systemctl status topic-rush-monitor
```

### 7. 查看日志

如果你是手动前台运行，日志会直接输出到终端。

如果你是用 `systemd` 跑，查看日志用：

```bash
sudo journalctl -u topic-rush-monitor -f
```

查看最近 100 行：

```bash
sudo journalctl -u topic-rush-monitor -n 100 --no-pager
```

### 8. 更新部署

后续更新时，替换目录里的代码后执行：

```bash
sudo systemctl restart topic-rush-monitor
```

如果你改了 service 文件本身，先执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart topic-rush-monitor
```

### 9. 常见问题

`Telegram 没收到消息`

先执行测试命令确认 bot token 和 chat id 是否正确：

```bash
python3 binance_topic_rush_monitor.py --telegram-test-message "topic rush test"
```

`脚本能跑，但没有新增推送`

首次运行会先建立基线，只记录当前榜单内容；后续只有真正新增的主题才会推送。

`想单独跑一个榜单`

可以把 `ExecStart` 改成：

```bash
/usr/bin/python3 /opt/topic-rush-monitor/binance_topic_rush_monitor.py --feeds topic-latest
```
