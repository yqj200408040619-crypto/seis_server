# h5_writer.py
import h5py
import numpy as np
from tqdm import tqdm   # 可选
from .config import *
from .raw_parser import iter_packets

def build_h5_from_raw(raw_filename: str, h5_filename: str, instrument_id: str = None):
    """
    将原始二进制文件转换为 HDF5。
    instrument_id 若未提供，则从文件名解析（可自定义逻辑）。
    """
    # 若未提供 instrument_id，从文件名提取，此处示例简单取文件名第一部分
    if instrument_id is None:
        import os
        base = os.path.basename(raw_filename)
        instrument_id = base.split('_')[0]  # 例如 "OBN00123"

    with h5py.File(h5_filename, 'w') as h5:

        # ---------- 创建 datasets ----------
        # samples: 可扩展 (N, 4, 1023)
        samples_ds = h5.create_dataset(
            'samples',
            shape=(0, CHNL_NUM, SAMP_BUF_NUM),
            maxshape=(None, CHNL_NUM, SAMP_BUF_NUM),
            dtype=DATA_DTYPE,
            chunks=H5_CHUNK_SHAPE,
            compression=H5_COMPRESSION,
            shuffle=H5_SHUFFLE
        )

        # packet_time_us: int64
        time_ds = h5.create_dataset(
            'packet_time_us',
            shape=(0,),
            maxshape=(None,),
            dtype=np.int64,
            chunks=(1024,)
        )

        # packet_no: uint16
        no_ds = h5.create_dataset(
            'packet_no',
            shape=(0,),
            maxshape=(None,),
            dtype=np.uint16,
            chunks=(1024,)
        )

        # packet_flags: uint16 (可扩展)
        flags_ds = h5.create_dataset(
            'packet_flags',
            shape=(0,),
            maxshape=(None,),
            dtype=np.uint16,
            chunks=(1024,)
        )

        # file_offset: int64 (可选，用于调试)
        offset_ds = h5.create_dataset(
            'file_offset',
            shape=(0,),
            maxshape=(None,),
            dtype=np.int64,
            chunks=(1024,)
        )

        # ---------- 写入 metadata ----------
        meta = h5.create_group('metadata')
        meta.attrs['instrument_id'] = instrument_id
        meta.attrs['sample_rate'] = SAMPLE_RATE
        meta.attrs['sample_interval_us'] = DT_US
        meta.attrs['channels'] = CHNL_NUM
        meta.attrs['samples_per_packet'] = SAMP_BUF_NUM
        meta.attrs['raw_endian'] = DATA_DTYPE.byteorder
        meta.attrs['time_basis'] = 'UTC'
        meta.attrs['timestamp_align'] = TIMESTAMP_ALIGN
        meta.attrs['year_is_offset'] = YEAR_IS_OFFSET
        meta.attrs['channel_names'] = CHANNEL_NAMES

        # ---------- 逐 packet 写入 ----------
        packet_list = []
        prev_timestamp = None
        packet_count = 0
        for offset, pkt in tqdm(iter_packets(raw_filename), desc="Parsing packets"):
            ts = pkt['timestamp_us']
            flags = 0

            # 检测丢包：如果前一个 packet 存在且时间差不是精确 1.023s，标记 gap
            if prev_timestamp is not None:
                delta = ts - prev_timestamp
                if delta != PACKET_DURATION_US:
                    flags |= 0x01   # bit0: gap before this packet
                    # 还可以记录丢包数量，这里简单标记
            prev_timestamp = ts

            # 检查 No 是否连续（可选）
            # ...

            # 将数据追加到 datasets
            samples_ds.resize((packet_count + 1, CHNL_NUM, SAMP_BUF_NUM))
            samples_ds[packet_count] = pkt['samples']

            time_ds.resize((packet_count + 1,))
            time_ds[packet_count] = ts

            no_ds.resize((packet_count + 1,))
            no_ds[packet_count] = pkt['no']

            flags_ds.resize((packet_count + 1,))
            flags_ds[packet_count] = flags

            offset_ds.resize((packet_count + 1,))
            offset_ds[packet_count] = offset

            packet_count += 1

        print(f"Successfully wrote {packet_count} packets to {h5_filename}")