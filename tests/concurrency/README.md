# 高并发 / 长周期任务 — 验证测试

对应清单:仓库根目录 [`TESTING_CHECKLIST_CN.md`](../../TESTING_CHECKLIST_CN.md)。

## 运行

```bash
cd tests/concurrency
for t in test_0*.py; do python3 "$t"; done
```

全部仅依赖 Python 标准库，无需安装第三方包，可在隔离环境直接运行。

## 测试环境与方法说明（重要）

验证在 `INTEGRATIONS_ONLY` 网络沙盒中完成，**无法联网安装** `h5py` / `obspy` /
`fastapi` / `bcrypt` 等第三方依赖。因此采用两种互补方法：

1. **真实运行被测代码（白盒 + 真 socket）**
   `server.py` 的连接并发逻辑（信号量闸门、idle reaper、写队列背压、优雅关闭）
   是纯标准库，仅对 `db` / `mseed` / `util` 有少量符号依赖。`_stubs.py` 把这三个
   模块替换为忠实的轻量替身并注入 `sys.modules`，于是 **genuine `server.py` 原样
   执行**，再用真实 TCP 套接字去打它。→ 测试 1.x / 2.x。

2. **等价逻辑复现（针对不可导入的重依赖模块）**
   `db.py`（h5py）、`data_reader.py`（obspy）、`security.py`（bcrypt）无法导入，
   但相关风险点要么是**纯 Python 数据结构**（sha256 缓存 / `_locks` dict 的无限
   增长），要么是**可独立度量的行为**（SQLite busy_timeout、有限线程池排队、
   `b''.join` 内存模型）。测试逐字复现源码中的对应逻辑，并与源码位置一一对应标注。
   → 测试 4.x / 5.x。

## 测试清单映射

| 脚本 | 覆盖项 | 结论 |
|------|--------|------|
| `test_01_connection_limit.py` | 1.1 连接上限 / 1.2 线程增长 / 1.3 信号量释放 | ✅ 符合预期 |
| `test_02_idle_reaper.py` | 1.4 reaper 回收 / 1.5 慢滴流绕过 | 1.4 ✅；**1.5 ✅ 已修复并验证**（`idle_no_record_sec`）|
| `test_03_write_backpressure.py` | 2.1 写队列背压 / 2.7 优雅 drain | ✅ 符合预期 |
| `test_04_cache_growth.py` | 4.1 sha256 缓存增长 / 4.2 per-device dict 增长 | **✅ 已修复并验证**（LRU 封顶 + TTL 淘汰）|
| `test_05_sqlite_busy.py` | 5.5 SQLite 写锁 busy_timeout | **✅ 已修复并验证**（显式 timeout=20）|
| `test_06_portal_blocking.py` | 5.1 大导出内存/非流式 + 导出闸门 / 线程池排队 | **✅ 已修复并验证**（流式 + 闸门）|
| `test_07_login_guard.py` | 5.2 登录限流 + bcrypt 并发闸门 | **✅ 已修复并验证** |
| `test_08_no_record_quarantine.py` | 1.5 回归：no-record 超时路径的日志与 quarantine | **✅ 修复并验证**（见下方缺陷说明）|

所有脚本现在断言的是**修复后的预期行为**（而非仅复现缺陷），8/8 通过。

## 本轮复核发现并修复的缺陷

- **缺陷 1（`server.py` no-record 超时日志 `NameError`）**：1.5 慢滴流守卫触发时，
  日志语句误用裸变量 `last_record_unix`（应为 `self.last_record_unix`），抛出
  `NameError`，在 `self._quarantine(...)` **之前**就崩溃了 handler。后果：慢滴流
  连接的半包既没有被 quarantine，也没有告警日志，数据静默丢失。`test_02` 只断言
  连接被回收，因而漏掉了此路径。已修复，并新增 `test_08_no_record_quarantine.py`
  作为回归守卫（去掉修复会断言失败、无 quarantine 文件；修复后通过）。

## 未能在沙盒中执行的项（需在真实部署环境补测）

- 真实 miniSEED 协议解析与 HDF5 实际读写（需 `h5py`/`obspy`）：3.1 读写并发一致性、
  3.2 超大文件 `index[:]` 读延迟、2.3/2.4 每包 open/flush/close 吞吐与 gzip CPU。
- FastAPI 端到端负载（需 `fastapi`/`uvicorn`/`bcrypt`）：5.3/5.4 的真实接口压测、
  5.2 的 bcrypt 实际耗时。本套用等价模型证实了其并发行为。
- OBN 第二接收器（18001）、故障注入（6.x）：建议在预发布环境用真实依赖执行。
