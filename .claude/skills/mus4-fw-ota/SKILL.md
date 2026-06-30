---
name: mus4-fw-ota
description: 编译并 OTA 上传 MUS4_FW 固件到 ESP32 设备。Linux 端执行 arduino-cli.py 编译 + 上传。
---

# MUS4_FW 固件编译与 OTA 上传

## 概述

在 Linux 环境下编译 `MUS4_FW.ino` 并通过 HTTP OTA 上传到 ESP32 设备（默认 `192.168.3.52`）。

## 工作目录

固件工程位于：

```
/home/dkc/projects/Firmware/MUS4_FW/
```

所有命令必须在该目录下执行，相对路径均以此为基准。

## 执行命令

### 默认目标（192.168.3.52）

```bash
cd /home/dkc/projects/Firmware/MUS4_FW && python arduino-cli.py -c -u --ota --ota-host 192.168.3.52 --input-file ./build/MUS4_FW.ino.bin
```

### 自定义目标

用户指定 OTA host 时，替换 `--ota-host` 参数：

```bash
cd /home/dkc/projects/Firmware/MUS4_FW && python arduino-cli.py -c -u --ota --ota-host <目标IP或主机名> --input-file ./build/MUS4_FW.ino.bin
```

### 仅编译（不上传）

```bash
cd /home/dkc/projects/Firmware/MUS4_FW && python arduino-cli.py -c --sketch MUS4_FW.ino
```

## 参数说明

| 参数 | 说明 |
|------|------|
| `-c` | 编译 sketch |
| `-u` | 上传固件 |
| `--ota` | 使用 ArduinoOTA 协议上传 |
| `--ota-host` | OTA 目标设备 IP 或主机名，默认端口 3232 |
| `--input-file` | 预编译的 .bin 固件文件路径（相对于工作目录） |

## 前置条件

- ESP32 设备需已开启 OTA 窗口（Web Console 中执行 `ENABLE_OTA`，需要认证且 Park 锁定；DEV 模式下无需 Park 锁定）
- 设备需与当前主机在同一网络（当前默认目标为 `192.168.3.52`）
- 如使用 HTTP OTA 替代 ArduinoOTA，可改用 curl：`curl -F "file=@./build/MUS4_FW.ino.bin" http://<host>/update`

## 编译产物

编译输出在 `./build/` 目录下，主要产物：
- `MUS4_FW.ino.bin` — 固件二进制文件（约 1.5MB）
- `MUS4_FW.ino.elf` — ELF 文件（含调试符号）
