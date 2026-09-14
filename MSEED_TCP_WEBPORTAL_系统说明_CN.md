# miniSEED TCP 接收与 Web Portal 系统说明

## 1. 目的与边界

本系统用于同时接收大量地震仪通过 TCP 持续发送的 miniSEED 2.x 数据，将每台仪器的数据保存为独立的 HDF5 (`.h5`) 文件，并让 Web Portal 在不复制波形数据的前提下提供实时查看、历史查询、权限控制和 miniSEED 导出。

当前设计目标是至少 100 台长期在线仪器。实际可承载的采样率取决于 CPU、磁盘 IOPS、网络带宽和每条记录的样本数；系统采用有界队列和 TCP 背压来保证过载时优先不丢数据。

系统不实现通用的仪器端补传协议。它会检测缺包与时间断档，但能否补传取决于仪器固件是否提供专用重发命令。

## 2. 部署组成

| 组件 | 运行路径 | 职责 |
| --- | --- | --- |
| TCP 接收器 | `/opt/mseed-tcp-server` | 监听 miniSEED TCP 流、解析、校验、排队和写入 HDF5 |
| 接收器服务 | `mseed-tcp-server.service` | 以 `mseed` 用户运行，入口为 `python -m mseed_tcp_server` |
| 波形文件 | `/var/lib/mseed-tcp-server/devices/*.h5` | 每台仪器一个 HDF5 文件 |
| 异常隔离区 | `/var/lib/mseed-tcp-server/quarantine/` | 保存无法恢复的残包、坏包和写失败数据 |
| Web Portal | `/opt/mseed-web-portal` | FastAPI 应用、认证、设备权限、波形 API 和导出 |
| Portal 元数据 | `/var/lib/mseed-web-portal/app.db` | SQLite，仅保存用户、权限、客户与设备登记，不保存波形 |
| Portal 服务 | `mseed-web-portal.service` | 当前运行端口为 `1888`；可由 nginx 反向代理到 80/443 |

```text
仪器 1..N
    | TCP :18000, miniSEED 字节流
    v
mseed-tcp-server
    | 连接线程: 分包、校验、解析出 NumPy 波形
    | 有界分片写队列: 同设备顺序，不同设备并行
    v
/var/lib/mseed-tcp-server/devices/<device>.h5
    | SWMR flush / 旧文件兼容读取
    v
mseed-web-portal :1888
    | FastAPI + Portal SQLite 权限数据库
    v
浏览器实时波形、历史波形、质量页、导出
```

## 3. 接收器处理逻辑

### 3.1 TCP 连接和容量控制

`mseed_tcp_server/server.py` 基于 `socketserver.ThreadingTCPServer`：每个 TCP 连接由一个守护线程负责。连接建立时通过 `BoundedSemaphore` 限制并发客户端数；新版本默认值为 `max_clients = 512`，可覆盖 100+ 台设备和短时重连峰值。

连接设置包括：

- `SO_KEEPALIVE` 与平台支持时的 `TCP_KEEPIDLE`、`TCP_KEEPINTVL`、`TCP_KEEPCNT`；
- `socket_timeout_sec`，超时后不关闭连接，只继续等待；
- 监听 backlog；生产环境建议设为 `512`，减少多设备同时重连时的拒绝连接风险。

仪器 TCP 发送没有“一个 `recv()` 等于一个 miniSEED 包”的保证。因此每个连接持有一个字节缓冲区，连续 `recv()` 并从中取出完整记录。

### 3.2 miniSEED 识别、解析与坏数据处理

处理顺序如下：

1. `is_plausible_record_start()` 检查固定头、质量码和块偏移是否合理。
2. `get_record_length()` 优先从 Blockette 1000 解析记录长度；若设备没有 Blockette 1000，可在配置中使用 `fixed_record_length`。
3. 缓冲区不足一个完整记录时保留到下一次 `recv()`。
4. `parse_full_packet()` 使用 ObsPy 完整解码记录，生成 `MSeedHeader` 和 NumPy 波形数组。
5. 前缀错误、长度错误或解析失败时，使用 `find_next_record_start()` 扫描下一个可能的记录起点；无法恢复的字节写入 quarantine，而不是混入 HDF5。

`max_buffer_bytes` 防止异常发送方无限占用内存。超过限制时，接收器尽力重新同步；找不到合法头时只保留末尾 47 字节，其他内容隔离。

### 3.3 有界分片写入队列

完整记录不会在连接线程中直接写磁盘。它先进入 `MSeedWritePipeline`：

1. 根据 `crc32(device_id) % writer_threads` 选择一个写入分片。
2. 同一 `device_id` 始终进入同一 FIFO 队列，因此序列号、间隙检测和 HDF5 写入顺序不会被多线程打乱。
3. 不同设备可由不同写线程并行写入，避免慢设备阻塞全部仪器。
4. 队列满时 `put()` 等待，而不丢弃记录；连接线程停止继续 `recv()`，TCP 窗口会反向限制发送方。这是有意的背压机制。

推荐容量配置：

```ini
[server]
backlog = 512
max_clients = 512
writer_threads = 8
write_queue_max_packets = 32768
```

`writer_threads` 应从 8 开始结合 CPU 和磁盘压测调整。队列容量是内存换取短时写入抖动的缓冲，不应把持续磁盘性能不足当作“靠加大队列解决”。

### 3.4 设备归类、去重和数据质量

设备身份由客户端 IP、服务端端口、miniSEED 网络码和台站码组成：

```text
device_id = <client_ip>_<server_port>_<network>_<station>
device_key = <network>_<station>
stream_key = <network>.<station>.<location>.<channel>
```

例如 `SS.02003.00.BHZ` 对应 `device_key = SS_02003`，三分量 `BHZ/BHN/BHE` 保存到同一个设备文件的三个 stream group。

写入时执行以下保护：

- 内存 SHA-256 缓存快速过滤当前进程内的重复包；
- HDF5 数据集名称包含纳秒时间、序列号和 SHA 前缀，服务重启后的重复包也不会再次写入；
- 检查 miniSEED 序列号连续性；
- 使用 `start_unix`、`end_unix`、采样率检测时间缺口或重叠；
- 事件写入 HDF5 根数据集 `gaps` 和 `events`，同时写入服务日志。

## 4. HDF5 存储和实时可见性

### 4.1 文件结构

每台设备一个文件：

```text
/var/lib/mseed-tcp-server/devices/192.0.2.10_18000_SS_02003.h5
  attrs: device_id, device_key, instrument_type, instrument_serial, created_at
  gaps: 可扩展复合数据集
  events: 可扩展复合数据集
  SS.02003.00.BHZ/                 # stream group
    attrs: last_seq, last_start, last_end, updated_unix, ...
    rec_<start_ns>_<seq>_<sha>/    # 每条 miniSEED 记录一个波形 dataset
      data: 解码后的 NumPy 样本
      attrs: 时间、采样率、通道、序列号、SHA、接收时间、raw_mseed 等
```

`raw_mseed` 属性保存原始 miniSEED 字节，用于无损导出；dataset 数据保存解码波形，用于 Portal 绘图与历史查询。

### 4.2 SWMR 和旧文件兼容

新建 HDF5 文件以 `libver="latest"` 打开并启用 HDF5 SWMR（single writer, multiple reader）。接收器对每个包完成属性写入后执行 `flush()`，Portal 便可读取已提交的新记录，而写端持续保持文件句柄，避免每条记录反复打开和关闭 HDF5 文件。

历史文件如果是旧 HDF5 superblock，无法原地启用 SWMR。接收器会自动回退为“打开、写入、flush、关闭”；Portal 会先尝试 SWMR，失败时短暂重试三次（每次 50 ms），再用普通只读模式打开。旧数据可继续使用，不需要迁移才能恢复服务。

注意事项：

- 同一个设备文件只能由一个接收器实例写入，禁止两个 mseed TCP 服务指向同一 `devices` 目录。
- Portal 只能只读访问接收器 HDF5 目录，不能由 Portal 修改波形文件。
- HDF5 文件不是适合用普通 `cp` 在写入中复制的数据库。在线备份应使用文件系统快照、停服务后备份，或先验证专用备份工具的快照策略。
- `gzip` 压缩更节省空间但消耗 CPU；高吞吐场景可配置 `lzf` 获得更低写入延迟。`lzf` 不应配置 `hdf5_compression_opts`。

## 5. Web Portal 逻辑

### 5.1 设备登记与权限

Portal 启动时初始化 `/var/lib/mseed-web-portal/app.db` 的 SQLite 表。该库保存：用户、角色、设备登记、用户设备授权、客户信息和告警配置。

接收器新建 `.h5` 后，管理员必须执行一次“同步设备”操作，Portal 才会把该文件登记为可分配设备：

```bash
sudo /opt/mseed-web-portal/.venv/bin/python \
  /opt/mseed-web-portal/tools/sync_devices.py
```

也可从管理页面触发。已登记设备后续持续写入不需要重复同步；同步只在新增设备、移动 HDF5 文件或修改设备元数据后执行。

普通用户只能看到 `user_devices` 或客户设备规则授予的设备；管理员可以管理用户、授权、客户规则和设备元数据。

### 5.2 波形读取与实时刷新

`app/data_reader.py` 是 HDF5 访问层。它使用 `open_h5_read()` 打开文件，优先 SWMR 只读并带短暂重试。读取过程按 stream、组件与时间范围筛选记录，使用 ObsPy 合并连续 Trace，然后使用 min/max 下采样限制浏览器点数。

实时页面不是服务端推送：浏览器按 `refresh_seconds` 调用波形 API。默认 2 秒刷新、显示最近 120 秒。端到端延迟通常由以下部分组成：仪器发送周期 + TCP 网络延迟 + 解码/排队 + HDF5 flush + 浏览器轮询周期。

主要 API（均需登录，`/api/health` 除外）：

| 接口 | 用途 |
| --- | --- |
| `GET /api/health` | Portal 健康检查 |
| `GET /api/devices` | 当前账户有权限的设备 |
| `GET /api/components?device_id=N` | 设备分量和最新时间 |
| `GET /api/waveform?device_id=N&component=BHZ&seconds=120` | 最近窗口波形 |
| `GET /api/waveform?...&start=<ISO/Unix>&end=<ISO/Unix>` | 历史时间段波形 |
| `GET /api/quality?device_id=N` | 间隙、重复和异常事件 |
| `GET /export/download` | 导出授权范围内的 miniSEED |

历史查询受 `max_query_records` 和 `max_plot_points` 限制，目的是防止单个浏览器请求把 Portal 进程和内存耗尽。大范围数据应使用导出接口，不应在实时页面中查询。

## 6. 配置和依赖

接收器配置：`/etc/mseed-tcp-server/server.ini`。

```ini
[server]
host = 0.0.0.0
port = 18000
backlog = 512
recv_size = 8192
socket_timeout_sec = 120
tcp_keepalive = true
max_clients = 512
writer_threads = 8
write_queue_max_packets = 32768

[storage]
base_dir = /var/lib/mseed-tcp-server
db_dir_name = devices
quarantine_dir_name = quarantine
hdf5_compression = gzip
hdf5_compression_opts = 6

[parser]
fixed_record_length = 0
min_record_length = 256
max_record_length = 131072
max_buffer_bytes = 1048576
resync_scan_limit = 1048576
validate_with_obspy = true
store_unvalidated_packets = false
time_gap_tolerance_samples = 1.5
```

Portal 配置：`/etc/mseed-web-portal/portal.ini`。当前服务运行于 1888；配置中 Portal 监听地址和端口必须与 systemd `ExecStart` 保持一致。

```ini
[paths]
receiver_db_dir = /var/lib/mseed-tcp-server/devices
app_db = /var/lib/mseed-web-portal/app.db
log_dir = /var/log/mseed-web-portal

[ui]
refresh_seconds = 2
latest_default_seconds = 120
max_plot_points = 6000
max_query_records = 20000
```

关键依赖：Python 3、ObsPy（miniSEED 解码与 Trace 合并）、NumPy（波形数组）、h5py/HDF5（文件存储与 SWMR）、FastAPI/Uvicorn（Portal）、Jinja2（页面模板）、SQLite（Portal 元数据）、nginx（可选反向代理和 TLS）。

## 7. 日常运维与工具

### 7.1 服务和日志

```bash
sudo systemctl status mseed-tcp-server mseed-web-portal
sudo journalctl -u mseed-tcp-server -f
sudo journalctl -u mseed-web-portal -f
sudo ss -ltnp '( sport = :18000 or sport = :1888 )'
curl -fsS http://127.0.0.1:1888/api/health
```

接收器日志保存在 `/var/log/mseed-tcp-server/`，Portal 日志保存在 `/var/log/mseed-web-portal/`。重点关注 `write queue full`、`database write failed`、`miniSEED validation failed`、`gap detected` 和 `quarantined`。

### 7.2 可用工具

| 命令或入口 | 作用 |
| --- | --- |
| `tools/send_mseed_file.py FILE --host HOST --port 18000 --chunk 1500` | 向接收器发送测试 miniSEED；小 chunk 可验证跨 TCP 分包重组 |
| Portal 管理页“同步设备”或 `tools/sync_devices.py` | 扫描 `.h5` 并登记新设备 |
| `tools/create_admin.py` | 创建或更新管理员/普通用户 |
| `tools/grant_device.py` | 向用户授予指定 device key |
| `tools/add_customer_device_rule.py` | 根据仪器类型和序列号范围创建自动授权规则 |
| `tools/apply_device_access_rules.py` | 将客户授权规则应用到已登记设备 |
| `tools/backup_databases.py` | Portal 元数据和接收器文件备份入口；先核对其备份配置与在线 HDF5 策略 |
| `tools/check_alerts.py` | 运行一次低开销的设备状态/告警检查 |
| `tools/configure_smtp.py`、`tools/test_smtp.py` | 配置和验证邮件告警 |

接收器目录中的 `tools/check_status.py`、`tools/export_mseed.py` 和 `tools/migrate_add_search_keys.py` 是旧 SQLite `.db` 版本遗留工具，不能对当前 HDF5 `.h5` 文件使用。当前 HDF5 数据应通过 Portal 的导出接口读取原始 miniSEED，或使用 `app.data_reader.export_mseed_bytes()`。

## 8. 故障排查

| 现象 | 排查方向 |
| --- | --- |
| 设备连不上 18000 | 检查 `ss`、防火墙、安全组、仪器目标 IP/端口、`max_clients` 与接收器日志 |
| 有连接但 Portal 无新波形 | 检查接收器 `stored` 日志、HDF5 文件修改时间、Portal 用户是否有该设备权限、页面组件选择和刷新窗口 |
| 新仪器不出现在设备列表 | HDF5 文件可能已生成但未登记；执行“同步设备”并授权用户 |
| Portal 偶发 HDF5 打开失败 | 检查是否有多个写端、磁盘/NFS 文件锁配置、旧 HDF5 回退日志；新文件应使用 SWMR |
| `write queue full` 持续出现 | 磁盘写入/压缩或 CPU 跟不上输入；检查 I/O、减轻压缩、增加 writer 线程或升级 SSD，而非无限增加队列 |
| 出现 `sequence_gap` 或 `time_gap` | 确认仪器网络、供电、时钟和固件；系统只记录断档，不能凭空恢复数据 |
| quarantine 文件增长 | 采样一段隔离数据，核对设备是否真发送 miniSEED 2.x、记录长度和 Blockette 1000；必要时设置 `fixed_record_length` |
| 数据盘容量增长过快 | 评估采样率、记录长度、压缩比和保留期；系统当前不自动删除历史 HDF5 数据 |

## 9. 变更和验证流程

每次修改接收器、Portal 或配置后执行：

```bash
sudo systemctl restart mseed-tcp-server.service
sudo systemctl restart mseed-web-portal.service
sudo systemctl status mseed-tcp-server.service mseed-web-portal.service
curl -fsS http://127.0.0.1:1888/api/health
```

本次并发改造已经做过以下验证：120 个独立设备并发写入、共 360 条记录；随后由独立 Portal 进程通过 SWMR 读取，确认每个测试文件记录完整且实时可见。生产上线后仍应在实际仪器采样率下持续观察 CPU、磁盘延迟、队列告警、HDF5 文件增长和 Portal 响应时间。

