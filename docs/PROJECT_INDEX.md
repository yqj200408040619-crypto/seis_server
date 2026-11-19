# 2026-11-19 新增代码导航

原有接收器和 Web Portal 完整保留。本轮增加迁移、离线恢复、历史代码和服务参考，不自动部署。

| 目录 | 用途 |
|---|---|
| tools/migration | 迁移导出与恢复脚本 |
| tools/offline_runtime | 离线环境构建与恢复脚本 |
| tools/diagnostics | 调试包生成脚本 |
| deploy/reference_systemd | 静态提取的历史 timer/service 参考 |
| archive/legacy_snapshots | SQLite 时期及旧 Web 源码、安装脚本、配置模板 |
| archive/historical_patches | Web、权限、语言、告警、备份的历史补丁，禁止整套直接重装 |

8 次后续修复仍在原 test/concurrency-longrun-checklist 分支；根据“不覆盖原有内容”的要求，本次没有合入 main。代码备份、分支合并、部署和恢复验证分别记录。

来源与原始哈希：[docs/CODE_PROVENANCE.csv](CODE_PROVENANCE.csv)。排除数据：[docs/DATA_INDEX.md](DATA_INDEX.md)。
