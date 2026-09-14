# miniSEED 平台迁移说明

## 重要区别

之前生成的 `mseed_portal_debug_*.tar.gz` 是调试包：

- 配置密码被遮盖；
- 没有真实 `app.db`；
- 没有完整接收数据库；
- 不能用于完整恢复。

迁移必须重新在旧服务器运行：

```bash
sudo bash mseed_migration_export.sh
```

生成：

```text
/home/ftp/mseed_full_migration_YYYYmmdd_HHMMSS.tar.gz
```

该迁移包包含真实 SMTP 密码、session secret、用户数据库和可能的波形数据。不要上传到公开聊天或网盘。

## 推荐迁移流程

### 一、在旧服务器导出

把 `mseed_migration_export.sh` 上传到旧服务器：

```bash
chmod +x mseed_migration_export.sh
sudo bash mseed_migration_export.sh
```

脚本会短暂停止 Web、TCP 接收器和相关 timer，完成一致性快照后自动恢复服务。

不迁移历史波形数据：

```bash
sudo bash mseed_migration_export.sh --no-waveform-data
```

指定输出目录：

```bash
sudo bash mseed_migration_export.sh --output /home/ftp
```

### 二、把迁移包传到新服务器

推荐服务器之间直接传输：

```bash
scp /home/ftp/mseed_full_migration_*.tar.gz root@新服务器IP:/root/
```

也可以先用 FileZilla 下载到 Windows，再上传到新服务器。

### 三、在新服务器恢复

把 `mseed_migration_restore.sh` 和迁移包放到新服务器：

```bash
chmod +x mseed_migration_restore.sh
sudo bash mseed_migration_restore.sh /root/mseed_full_migration_YYYYmmdd_HHMMSS.tar.gz
```

### 四、开放端口

云平台安全组和 Ubuntu 防火墙根据实际情况开放：

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 18000/tcp
```

如果使用 FRP，还需要开放 FRP 服务端口，例如 7000/TCP。

### 五、切换公网入口

迁移不会自动获得旧服务器的公网 IP。需要选择一种方式：

- 把地震仪服务器地址改成新服务器公网 IP；
- 修改域名 A 记录到新 IP；
- 使用云服务商的浮动 IP；
- 保留旧服务器作为 FRP/反向代理入口，把流量转给新服务器。

地震仪连接示例：

```text
New server public IP:18000
```

Web Portal：

```text
http://New server public IP/
```

### 六、验证

```bash
sudo systemctl status mseed-tcp-server --no-pager
sudo systemctl status mseed-web-portal --no-pager
sudo systemctl status nginx --no-pager

sudo ss -lntp | grep -E '(:80|:8080|:18000)'
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1/
```

浏览器检查：

1. admin 可以进入 System 和 Admin；
2. 普通用户只能看到授权设备；
3. Live waveform、Historical waveform 正常；
4. Data export 可以导出；
5. Alerts 只显示授权设备告警；
6. 中英文切换正常；
7. SMTP 测试邮件正常。

## 降低停机时间

如果未来波形数据库很大，不要直接打几百 GB 的 tar 包。推荐：

1. 服务运行时，先用 `rsync` 预复制 `/var/lib/mseed-tcp-server/devices/`；
2. 正式切换时停止旧 TCP receiver；
3. 再执行一次增量 `rsync`；
4. 启动新服务器 receiver；
5. 修改设备地址或 DNS。

当前数据量较小时，直接使用完整迁移包更简单。
