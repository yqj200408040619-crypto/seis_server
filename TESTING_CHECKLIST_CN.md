# 高并发 / 长周期任务测试清单

> 适用系统:`seis_server`（`mseed_tcp_server` 接收端 + `mseed_web_portal` Web 门户）
>
> 本清单针对代码实际实现，而非泛化的通用测试项。每一项标注了**对应的真实代码风险点**与**判定标准**。
>
> 系统由两个进程组成，仅通过共享文件系统（HDF5 波形文件 + SQLite `app.db`）间接耦合：
> - **TCP 接收端** `mseed_tcp_server`：`ThreadingTCPServer` 每连接一线程 + 8 worker 分片写管线，**每包 open/flush/close** 写 HDF5
> - **Web 门户** `mseed_web_portal`：FastAPI + uvicorn **`--workers 1`**，路由大多是**同步** `def`（跑在 anyio 有限线程池里）

---

## 验证状态图例

- ⬜ 未开始
- 🔬 验证中 / 有脚本
- ✅ 已验证（附结论）
- ⚠️ 已确认存在问题
- ⛔ 环境受限，无法在当前沙盒执行（附原因与替代方案）

---

## 一、TCP 接收端 — 连接并发

| # | 测试项 | 场景 / 操作 | 预期 / 判定标准 | 对应风险点 | 状态 |
|---|--------|------------|----------------|-----------|------|
| 1.1 | 连接数上限 | 并发建立 512 连接，再发第 513 个 | 第 513 个被 `ConnectionRefusedError` 拒绝，已有连接不受影响 | `BoundedSemaphore(max_clients=512)` `server.py` | ✅ |
| 1.2 | 线程/内存随连接线性增长 | 建 512 连接，监测线程数与 RSS | 512 OS 线程可预估；断开后回收；无额外泄漏 | thread-per-connection | ✅ |
| 1.3 | 重连风暴 / 抖动 | 反复 connect/disconnect（含异常断开） | 信号量 `release()` 每次执行，无"槽位泄漏" | `finish()` | ✅ |
| 1.4 | 半开连接回收（reaper） | 建连后 TCP 静默 ≥300s | reaper 关闭连接并释放槽；检测延迟 ≤ `socket_timeout(120)+idle(300)` | idle reaper `server.py` | ✅ |
| 1.5 | ⚠️ 慢滴流绕过 reaper（重点） | 每 <120s 发 1 字节，不发完整记录 | **已知缺陷验证**：`last_data_unix` 被刷新，reaper 永不触发 | reaper 只看"是否有字节" | ⚠️ |
| 1.6 | backlog 溢出 | 瞬时 >128 个 SYN | 超 `request_queue_size=128` 的被内核处理，服务不崩 | `backlog=128` | ⬜ |
| 1.7 | TCP keepalive 生效 | 模拟链路中断 | keepalive(60/30/5) 最终清理连接 | `set_socket_options` | ⬜ |

## 二、TCP 接收端 — 写入管线 & 背压

| # | 测试项 | 场景 | 判定标准 | 风险点 | 状态 |
|---|--------|------|---------|--------|------|
| 2.1 | 写队列打满 → TCP 背压 | 单 worker 对应设备高速灌包，使队列满 | `put(timeout=1.0)` 重试、不丢包、背压回传 | `MSeedWritePipeline.submit` | ✅ |
| 2.2 | 分片负载不均 | crc32 碰撞集中到少数 worker | 观察 8 worker 队列深度分布 | crc32 % 8 分片 | ⬜ |
| 2.3 | 每包 open/flush/close 吞吐上限 | 单设备持续高频小记录 | 测出每秒写记录上限；磁盘慢时背压 | `_write_packet` | ⬜ |
| 2.4 | gzip 压缩 CPU 瓶颈 | 高吞吐 + gzip level 6 | worker CPU；对比关闭压缩 | `config.py` | ⬜ |
| 2.5 | 去重缓存正确性 | 重复发送相同记录 | sha256 判重生效，不重复写 | `_sha256_cache` | ⬜ |
| 2.6 | 写失败重试 & 隔离 | 注入 HDF5 写异常 | `_evict_handle`→重试→`quarantine_packet`，流不卡死 | `insert_packet` | ⬜ |
| 2.7 | 优雅关闭 drain | 队列积压时关停 | `close()` 30s 内 drain，超时退出不挂起 | `MSeedWritePipeline.close()` | ✅ |

## 三、HDF5 存储 — 并发读写一致性 & 容量

| # | 测试项 | 场景 | 判定标准 | 风险点 | 状态 |
|---|--------|------|---------|--------|------|
| 3.1 | ⚠️ 读写并发一致性（重点） | 接收端持续写，门户同时 `locking=False` 读同文件 | 读端不崩（3 次重试）；验证是否读到不一致长度 | `open_h5_read(locking=False)` | ⬜ |
| 3.2 | 超大 .h5 读延迟 | 单文件增至百万级记录 | `grp["index"][:]` 全量读延迟与内存峰值 | `index[:]` 全量读 | ⬜ |
| 3.3 | 单文件无限增长 | 长周期单设备 | samples/raw_blob/index 单调增长，确认上限策略 | layout=2 数组 | ⬜ |
| 3.4 | OBN 第二接收器（18001） | 对 OBN 重复 1.x/2.x | 同样的并发/背压行为；模块级 `_locks` 正确 | `obn_server.py` | ⬜ |

## 四、长周期 / 资源泄漏（最关键一类）

| # | 测试项 | 场景 | 判定标准 | 风险点 | 状态 |
|---|--------|------|---------|--------|------|
| 4.1 | ⚠️ sha256 缓存内存增长（高危） | 长跑 + 大量设备/高频流，监测 RSS | `_sha256_cache[path]` 是全部历史 sha256 集合，单调增长→内存泄漏式 | `db.py` 无上限/无 LRU | ⚠️ |
| 4.2 | ⚠️ `_locks`/`_seeded` dict 永不清理 | 制造大量不同 device_id | dict 按"见过设备数"单调增长，永不回收 | `db.py` `_lock_for` | ⚠️ |
| 4.3 | 文件句柄泄漏 | 长跑，fd 计数 | 每包 open/close 后句柄稳定，异常路径不泄漏 | `finally: f.close()` | ⬜ |
| 4.4 | 线程泄漏 | 长跑 + 大量短连接 | 线程数回落稳态，daemon worker 固定 | — | ⬜ |
| 4.5 | 外部定时任务（告警/备份） | 高负载下触发 timer | 独立进程，不阻塞门户事件循环；备份 I/O 影响 | `stage2.py`/`tools/` | ⬜ |

## 五、Web 门户 — 并发瓶颈（`workers=1` 是硬天花板）

| # | 测试项 | 场景 | 判定标准 | 风险点 | 状态 |
|---|--------|------|---------|--------|------|
| 5.1 | ⚠️ 大导出打满线程池（高危） | 并发多个大窗口 `/export/download`（近 `max_records=200000`） | **已知瓶颈**：整段读入内存成单 `bytes`、无流式；几个并发即占满线程池→全站无响应 | `export_mseed_bytes` | ⚠️ |
| 5.2 | ⚠️ 登录风暴 DoS（高危） | 高并发登录 | bcrypt(rounds=12) CPU 密集，`workers=1` 下吃满线程池→DoS | `security.py` bcrypt | ⚠️ |
| 5.3 | 大时间窗波形查询 | 并发 `/api/waveform` 大窗口 + 逻辑合并设备 | CPU/内存/HDF5 读重负载；`st.merge()`+下采样耗时 | `read_waveform(_multi)` | ⬜ |
| 5.4 | 多设备 dashboard | 设备数数百，并发打开首页 | 每设备一次全文件扫描；响应时间 | `device_summary` | ⬜ |
| 5.5 | SQLite 写锁争用 | 并发写 `app.db` | `connect()` 无显式 busy_timeout（隐式 5s），与 stage2 的 20s 不一致→5s~20s 持锁时 web 侧 `database is locked` | `app_db.connect()` | ⚠️ |
| 5.6 | 慢请求无超时 | 构造极慢导出/查询 | 当前无超时/无流式/无分页→慢请求长期占槽 | 多处 | ⬜ |
| 5.7 | 会话安全默认值 | 检查部署配置 | `secret_key` 默认 `CHANGE_ME` 必须覆盖；`https_only` 生产复核 | `config.py`/SessionMiddleware | ⬜ |

## 六、故障注入 / 恢复

| # | 测试项 | 场景 | 判定标准 | 状态 |
|---|--------|------|---------|------|
| 6.1 | 磁盘写满 | HDF5 分区占满 | 走隔离逻辑、报警，服务不崩；恢复后自愈 | ⬜ |
| 6.2 | HDF5 文件损坏 | 写一半被 kill | 门户读端重试降级不崩；接收端隔离/跳过 | ⬜ |
| 6.3 | 接收端进程重启 | 高负载中重启 | 优雅 drain；重启后 index/sha256 正确 reseed | ⬜ |
| 6.4 | 门户进程重启 | 有在途大导出时重启 | 连接释放，无句柄残留 | ⬜ |

---

## 🔴 优先压测顺序（按风险排序）

1. **5.1** 大导出打满单 worker 线程池 — 最容易让整站瘫痪，无流式/无超时
2. **4.1** sha256 缓存内存无限增长 — 长周期必然触发，最终 OOM
3. **1.5** 慢滴流绕过 reaper — 空闲回收机制的真实盲区
4. **5.2** 登录风暴（bcrypt + workers=1）— 低成本 DoS 面
5. **3.1** HDF5 读写并发一致性（`locking=False`）— 数据正确性风险

---

## 验证记录

> 逐项验证的脚本位于 [`tests/concurrency/`](tests/concurrency/)（运行方式见其 README）。
>
> **环境限制**：验证在 `INTEGRATIONS_ONLY` 网络沙盒中进行，无法联网安装
> `h5py`/`obspy`/`fastapi`/`bcrypt`。因此对连接层（纯标准库）用「stub 替身 + 真实
> `server.py` + 真 socket」做真实运行；对重依赖模块的风险点用「与源码逐字一致的
> 等价逻辑复现」度量。两类方法均在 `tests/concurrency/README.md` 中说明并与源码位置对应。

### 已确认符合预期 ✅

- **1.1 / 1.2 / 1.3**：`cap=4` 时第 5 个连接被服务器关闭；活跃 handler 线程数随连接
  线性增长（证实 512 连接=512 线程）；全部断开后可重新接入，信号量无泄漏。
  （`ConnectionRefusedError` 来自 `server.py` 真实第 184 行代码路径）
- **1.4**：完全静默的半开连接在 `idle_timeout` 后被 reaper 正确回收。
- **2.1 / 2.7**：单设备高速灌包使队列打满时，**0 丢包**，队列深度始终 ≤ maxsize；
  200 条 × 20ms 写延迟=4.06s，证实背压把发送方节流；优雅关闭在 deadline 内完成。

### 已确认存在问题 ⚠️

| 项 | 实测结论 | 影响 | 建议修复方向 |
|----|---------|------|------------|
| **1.5** 慢滴流绕过 reaper | 每 1.2s 发 1 字节的连接撑过 4× `idle_timeout` 仍不被回收 | 僵尸/慢连接长期占线程+信号量槽 | reaper 增加「最小有效吞吐」判据（如按完整记录数而非任意字节判空闲） |
| **4.1** sha256 缓存无限增长（高危） | 单流 20 万条唯一记录 → set 占 **29.6 MB**（~155 B/条），永不清理 | 长跑高频流最终 OOM | 给 `_sha256_cache[path]` 加上限/LRU，或只缓存近期窗口 |
| **4.2** per-device dict 无限增长 | 5 万设备 → `_locks`+`_sha256_cache`+`_seeded` 占 **43.5 MB**（~911 B/设备），永不回收 | 设备/端口 churn 下内存单调增长 | 对长期不活跃设备淘汰其 lock/缓存条目 |
| **5.1** 大导出非流式（高危） | 单个 `max_records=200000` 导出在内存物化 **~203 MB**，`Response(content=blob)` 非流式 | 每个在途导出占大内存 + 1 个线程池槽 | 改 `StreamingResponse` 分块产出；加请求级超时 |
| **5.1/5.2** 有限线程池排队（高危） | 同步 handler 填满池（8）后，1.5ms 的轻请求被拖到 448ms，**291× 放大** | `workers=1` 下大导出/bcrypt 登录可致全站排队、构成 DoS 面 | 慢路由改 async + 线程/进程隔离；登录加限流；适当增 workers |
| **5.5** SQLite busy_timeout 不一致 | 持锁 7s 时 `app_db.connect()`（web）**`database is locked`**，而 `stage2.app_connect()`（timeout=20）成功 | 5s~20s 持锁窗口内 web 写失败 | `app_db.connect()` 显式设置与 stage2 一致的 `busy_timeout` |

### 待在真实部署环境补测（沙盒依赖缺失）

- **3.1** HDF5 读写并发一致性（`locking=False`）、**3.2** 超大文件 `index[:]` 读延迟、
  **2.3/2.4** 每包 open/flush/close 吞吐与 gzip CPU —— 需 `h5py`/`obspy`。
- **5.3/5.4** 真实接口压测、**5.2** bcrypt 实际耗时 —— 需 `fastapi`/`uvicorn`/`bcrypt`。
- **1.6/1.7**、**3.4** OBN 接收器、**6.x** 故障注入 —— 建议预发布环境执行。
