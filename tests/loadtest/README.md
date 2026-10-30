# 端到端负载测试(需真实依赖环境)

这组脚本在**安装了项目依赖**的环境(staging / 本地 venv)里对真实的接收端 +
门户施压,覆盖 [`TESTING_CHECKLIST_CN.md`](../../TESTING_CHECKLIST_CN.md) 中因沙盒
依赖缺失而无法在 CI 执行的项(1.x / 2.x / 3.x / 5.x),并实测修复后的行为。

> ⚠️ **不能在 `INTEGRATIONS_ONLY` 沙盒运行**:该环境无法安装 `h5py`/`obspy`/
> `fastapi`/`bcrypt`。脚本检测到依赖缺失会**明确报错并退出(非 0)**,绝不伪装通过。

## 准备

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r mseed_tcp_server/requirements.txt
pip install -r mseed_web_portal/requirements.txt
```

## 一键编排

```bash
python tests/loadtest/run_e2e.py                      # 默认参数
python tests/loadtest/run_e2e.py --connections 600 --records 4000   # 加压
```

`run_e2e.py` 会:生成 miniSEED 测试数据 → 启动接收端(临时数据目录、带本次修复的
配置项)→ 并发灌包 → 启动门户 → 跑登录洪泛与 mixed 场景 → 清理。日志路径在结束时打印。

## 单独运行各驱动(对已运行的服务)

```bash
# 1) 生成测试数据
python tests/loadtest/gen_mseed.py --out /tmp/fx --stations 8 --channels 3 --records 2000

# 2) TCP 并发灌包(1.x 连接并发 / 2.x 背压 / 3.x 大文件)
python tests/loadtest/loadtest_tcp.py --fixtures /tmp/fx --port 18000 --connections 64
#   - connections 超过接收端 max_clients 时出现的拒绝 = 清单 1.1,属预期
#   - --inter-chunk-delay 可模拟实时/慢速馈送,配合观察 reaper(1.4/1.5)

# 3) 门户压测(5.x)
python tests/loadtest/loadtest_portal.py --base http://127.0.0.1:8000 \
    --scenario login  --concurrency 50 --requests 200      # 5.2 登录洪泛
python tests/loadtest/loadtest_portal.py --base http://127.0.0.1:8000 \
    --scenario export --concurrency 10 --requests 30 \
    --device-id 1 --start 1704067200 --end 1704070800      # 5.1 大导出
python tests/loadtest/loadtest_portal.py --base http://127.0.0.1:8000 \
    --scenario mixed  --concurrency 50 --requests 200       # 池隔离验证
```

## 各项预期(修复后)

| 场景 | 覆盖 | 修复后预期 |
|------|------|-----------|
| TCP `--connections` > max_clients | 1.1 | 超出部分被拒绝,已连接不受影响 |
| TCP `--inter-chunk-delay` 很大、不发完整记录 | 1.5 | 连接在 `idle_no_record_sec` 后被回收 |
| TCP 单设备高速灌包 | 2.1 | 不丢包;队列满时发送端被背压节流 |
| 长时间多设备灌包后观察接收端 RSS | 4.1/4.2 | 内存趋于平稳(LRU 封顶 + TTL 淘汰),不单调增长 |
| portal `login` 洪泛 | 5.2 | 先 401,触发阈值后出现 **429/499→503**;进程不被拖垮 |
| portal `export` 高并发 | 5.1 | 超过导出闸门的请求返回 **503**;成功的导出**流式**返回、内存不随窗口暴涨 |
| portal `mixed` | 5.1/5.2 | 慢导出运行时,廉价 `/login` 页仍低延迟响应 |

## 场景前置数据说明

- `login` 场景即使用户不存在也会走到限流逻辑(返回 401 `no_such_user`),**无需预置用户**即可验证 5.2。
- `export` / `waveform` 场景需要 app.db 中存在 `--device-id` 对应、且当前用户有权限的设备;
  请用门户的管理流程注册设备后再压测(或在 staging 用既有数据)。
- 建议配合 `top`/`/proc/<pid>/status` 观察接收端与门户进程的 RSS 曲线,验证 4.x 的内存平稳性。
