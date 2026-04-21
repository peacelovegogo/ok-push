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

## CentOS 服务器部署说明

下面这份说明按 CentOS 7 / CentOS Stream / 其他带 `systemd` 的 CentOS 系统编写，目标是把 `topic-rush-monitor` 做成开机自动启动服务。

### 1. 环境准备

- `python3` 3.9 或更高版本
- `systemd`
- 可选：`npm`

这个项目没有额外的 Python 三方依赖；服务器上只要有 Python，就可以直接运行 `python3 binance_topic_rush_monitor.py`。

如果服务器还没有安装 Python，可以先执行：

```bash
# CentOS Stream / 较新的 CentOS 环境
sudo dnf install -y python3

# CentOS 7 常见写法
sudo yum install -y python3
```

安装后建议确认 Python 路径，后面写 `systemd` 服务文件时会用到：

```bash
python3 --version
which python3
```

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

### 3. 创建运行用户并设置目录权限

推荐给这个服务单独创建一个系统用户，例如 `topicrush`：

```bash
sudo useradd --system --home-dir /opt/topic-rush-monitor --shell /sbin/nologin topicrush
sudo chown -R topicrush:topicrush /opt/topic-rush-monitor
```

如果你已经有专门的部署用户，也可以直接复用；关键是这个用户必须对 `/opt/topic-rush-monitor` 目录有读写权限，因为脚本会在里面创建 `.state/`。

### 4. 配置 `.env`

先复制模板：

```bash
cd /opt/topic-rush-monitor
cp .env.example .env
```

再填写你自己的 Telegram 配置：

```bash
TOPIC_TELEGRAM_BOT_TOKEN=your_topic_bot_token
TOPIC_TELEGRAM_CHAT_ID=your_topic_chat_id
```

推荐继续使用 `TOPIC_TELEGRAM_*` 这组变量，配置含义会更直观。

### 5. 首次手动验证

建议先用实际运行用户手动验证一次：

```bash
cd /opt/topic-rush-monitor
sudo -u topicrush python3 binance_topic_rush_monitor.py --telegram-test-message "topic rush test"
sudo -u topicrush python3 binance_topic_rush_monitor.py --once
```

如果想只验证某一个榜单，可以这样跑：

```bash
sudo -u topicrush python3 binance_topic_rush_monitor.py --feeds topic-latest --once
```

如果这一步能正常运行，后面做成开机自启通常就不会有太大问题。

### 6. 配置 systemd 开机自启服务

新建服务文件：

```bash
sudo vi /etc/systemd/system/topic-rush-monitor.service
```

写入下面内容：

```ini
[Unit]
Description=Binance Web3 Topic Rush Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=topicrush
Group=topicrush
WorkingDirectory=/opt/topic-rush-monitor
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 /opt/topic-rush-monitor/binance_topic_rush_monitor.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

注意两点：

- 如果你的 Python 不在 `/usr/bin/python3`，把 `ExecStart` 改成 `which python3` 查到的真实路径
- 如果你没有创建 `topicrush` 用户，就把 `User` 和 `Group` 改成你的实际运行用户

加载服务并设置开机自动启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable topic-rush-monitor
sudo systemctl start topic-rush-monitor
sudo systemctl status topic-rush-monitor --no-pager
```

确认是否已经设置为开机自启：

```bash
sudo systemctl is-enabled topic-rush-monitor
```

返回 `enabled` 就表示服务器重启后会自动启动。

### 7. 常用服务管理命令

启动服务：

```bash
sudo systemctl start topic-rush-monitor
```

停止服务：

```bash
sudo systemctl stop topic-rush-monitor
```

重启服务：

```bash
sudo systemctl restart topic-rush-monitor
```

查看状态：

```bash
sudo systemctl status topic-rush-monitor --no-pager
```

关闭开机自启：

```bash
sudo systemctl disable topic-rush-monitor
```

### 8. 查看日志

如果你是手动前台运行，日志会直接输出到终端。

如果你是用 `systemd` 跑，查看实时日志用：

```bash
sudo journalctl -u topic-rush-monitor -f
```

查看最近 100 行：

```bash
sudo journalctl -u topic-rush-monitor -n 100 --no-pager
```

### 9. 更新部署

后续更新时，替换目录里的代码后执行：

```bash
sudo chown -R topicrush:topicrush /opt/topic-rush-monitor
sudo systemctl restart topic-rush-monitor
```

如果你改了 service 文件本身，先执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart topic-rush-monitor
```

### 10. 常见问题

`服务启动失败`

先看状态和日志：

```bash
sudo systemctl status topic-rush-monitor --no-pager
sudo journalctl -u topic-rush-monitor -n 100 --no-pager
```

很多时候是 `ExecStart` 的 Python 路径写错，或者运行用户对部署目录没有写权限。

`Telegram 没收到消息`

先执行测试命令确认 bot token 和 chat id 是否正确：

```bash
sudo -u topicrush python3 /opt/topic-rush-monitor/binance_topic_rush_monitor.py --telegram-test-message "topic rush test"
```

`脚本能跑，但没有新增推送`

首次运行会先建立基线，只记录当前榜单内容；后续只有真正新增的主题才会推送。

`想单独跑一个榜单`

可以把 `ExecStart` 改成：

```bash
/usr/bin/python3 /opt/topic-rush-monitor/binance_topic_rush_monitor.py --feeds topic-latest
```
