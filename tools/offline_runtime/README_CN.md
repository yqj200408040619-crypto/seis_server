# miniSEED 完整离线运行环境包

这个方案直接复制旧服务器上已经运行成功的完整 Python 环境，不再从 GitHub、Conda 或 PyPI 下载。

包含：

```text
/opt/miniforge3
/opt/miniforge3/envs/mseed-web
/opt/mseed-tcp-server/.venv
```

因此可离线恢复：

- Python 3.10
- FastAPI
- Uvicorn
- Jinja2
- ObsPy
- NumPy
- Plotly
- TCP receiver 所需依赖

## 限制

源服务器和目标服务器必须：

- CPU 架构一致，例如都为 x86_64；
- Ubuntu/glibc 版本相近；
- 恢复到相同绝对路径。

本工具按原路径恢复，所以 systemd 无需修改 Python 路径。

## 在旧服务器生成

```bash
chmod +x mseed_complete_runtime_build.sh
sudo bash mseed_complete_runtime_build.sh
```

输出：

```text
/home/ftp/mseed_complete_runtime_YYYYmmdd_HHMMSS.tar.gz
```

## 传到新服务器

需要上传：

```text
mseed_complete_runtime_*.tar.gz
mseed_complete_runtime_restore.sh
```

## 在新服务器恢复

先完成程序迁移，让 `/opt/mseed-web-portal` 和 `/opt/mseed-tcp-server` 已存在。

然后：

```bash
chmod +x mseed_complete_runtime_restore.sh

sudo bash mseed_complete_runtime_restore.sh \
/home/setscomp/mseed_complete_runtime_YYYYmmdd_HHMMSS.tar.gz
```

完成后检查：

```bash
sudo systemctl status mseed-web-portal --no-pager
sudo systemctl status mseed-tcp-server --no-pager

/opt/miniforge3/envs/mseed-web/bin/python --version
/opt/mseed-tcp-server/.venv/bin/python --version
```

## 系统依赖

这个包解决全部 Python 运行环境，但系统软件仍需安装：

```bash
sudo apt update
sudo apt install -y nginx sqlite3 rsync curl ca-certificates
```

你当前的新服务器能够访问 Ubuntu 软件源，因此这部分已经可以正常安装。
