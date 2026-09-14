# raw_parser.py
import struct
import numpy as np
from datetime import datetime, timezone
from .obn_config import *

def parse_packet(raw: bytes, file_offset: int):
    """
    解析一个 16380 字节的 packet。
    """
    if len(raw) != PACKET_SIZE:
        raise ValueError(f"Invalid packet size: {len(raw)}, expected {PACKET_SIZE}")

    # 解包头
    hdr = struct.unpack(HEADER_STRUCT, raw[:HEADER_SIZE])
    year, month, day, hour, minute, second, no, us = hdr

    # 处理年份
    if YEAR_IS_OFFSET:
        year += 2000

    # 构建 datetime 对象（UTC）
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    timestamp_us = int(dt.timestamp() * 1_000_000) + us

    # 读取 samples
    samples = np.frombuffer(
        raw,
        dtype=DATA_DTYPE,
        count=CHNL_NUM * SAMP_BUF_NUM,
        offset=HEADER_SIZE
    ).reshape(CHNL_NUM, SAMP_BUF_NUM).copy()

    # 根据 TIMESTAMP_ALIGN 调整时间戳
    if TIMESTAMP_ALIGN == 1:   # 对应最后一个样点
        timestamp_us -= (SAMP_BUF_NUM - 1) * DT_US
    elif TIMESTAMP_ALIGN == 2: # 打包时间，需要额外偏移
        timestamp_us -= (SAMP_BUF_NUM // 2) * DT_US

    return {
        'year': year,
        'month': month,
        'day': day,
        'hour': hour,
        'minute': minute,
        'second': second,
        'no': no,
        'us': us,
        'timestamp_us': timestamp_us,
        'samples': samples
    }

def iter_packets(filename: str):
    """生成器，遍历文件中所有 packet，同时返回文件偏移"""
    with open(filename, 'rb') as f:
        offset = 0
        while True:
            raw = f.read(PACKET_SIZE)
            if not raw:
                break
            if len(raw) != PACKET_SIZE:
                print(f"Warning: incomplete packet at offset {offset}, skipped")
                break
            yield offset, parse_packet(raw, offset)
            offset += PACKET_SIZE
