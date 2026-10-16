import atexit
import os
import queue
import threading
import time
from datetime import datetime
import json

import numpy as np
from PIL import Image
import logging

from donkeycar.parts.datastore_v2 import Manifest, ManifestIterator


logger = logging.getLogger(__name__)


class Tub(object):
    """
    A datastore to store sensor data in a key, value format. \n
    Accepts str, int, float, image_array, image, and array data types.
    """

    def __init__(self, base_path, inputs=[], types=[], metadata=[],
                 max_catalog_len=1000, read_only=False):
        self.base_path = base_path
        self.images_base_path = os.path.join(self.base_path, Tub.images())
        self.inputs = inputs
        self.types = types
        self.metadata = metadata
        self.manifest = Manifest(base_path, inputs=inputs, types=types,
                                 metadata=metadata, max_len=max_catalog_len,
                                 read_only=read_only)
        self.input_types = dict(zip(self.inputs, self.types))
        # Create images folder if necessary
        if not os.path.exists(self.images_base_path):
            os.makedirs(self.images_base_path, exist_ok=True)

    def write_record(self, record=None):
        """
        Can handle various data types including images.
        """
        contents = dict()
        for key, value in record.items():
            if value is None:
                continue
            elif key not in self.input_types:
                continue
            else:
                input_type = self.input_types[key]
                if input_type == 'float':
                    # Handle np.float() types gracefully
                    contents[key] = float(value)
                elif input_type == 'str':
                    contents[key] = value
                elif input_type == 'int':
                    contents[key] = int(value)
                elif input_type == 'boolean':
                    contents[key] = bool(value)
                elif input_type == 'nparray':
                    contents[key] = value.tolist()
                elif input_type == 'list' or input_type == 'vector':
                    contents[key] = list(value)
                elif input_type == 'image_array':
                    # Handle image array
                    image = Image.fromarray(np.uint8(value))
                    name = Tub._image_file_name(self.manifest.current_index, key)
                    image_path = os.path.join(self.images_base_path, name)
                    image.save(image_path)
                    contents[key] = name
                elif input_type == 'gray16_array':
                    # save np.uint16 as a 16bit png
                    image = Image.fromarray(np.uint16(value))
                    name = Tub._image_file_name(self.manifest.current_index, key, ext='.png')
                    image_path = os.path.join(self.images_base_path, name)
                    image.save(image_path)
                    contents[key]=name

        # Private properties
        contents['_timestamp_ms'] = int(round(time.time() * 1000))
        contents['_index'] = self.manifest.current_index
        contents['_session_id'] = self.manifest.session_id[1]
        self.manifest.write_record(contents)

    def delete_records(self, record_indexes):
        self.manifest.delete_records(record_indexes)

    def delete_last_n_records(self, n):
        # build ordered list of non-deleted indexes
        all_alive_indexes = sorted(set(range(self.manifest.current_index))
                                   - self.manifest.deleted_indexes)
        to_delete_indexes = all_alive_indexes[-n:]
        self.manifest.delete_records(to_delete_indexes)

    def restore_records(self, record_indexes):
        self.manifest.restore_records(record_indexes)

    def close(self):
        logger.info(f'Closing tub {self.base_path}')
        self.manifest.close()

    def __iter__(self):
        return ManifestIterator(self.manifest)

    def __len__(self):
        return self.manifest.__len__()

    @classmethod
    def images(cls):
        return 'images'

    @classmethod
    def _image_file_name(cls, index, key, extension='.jpg'):
        key_prefix = key.replace('/', '_')
        name = '_'.join([str(index), key_prefix, extension])
        # Return relative paths to maintain portability
        return name


class TubWriter(object):
    """
    A Donkey part, which can write records to the datastore.

    async_write=True（模板经 cfg.TUB_ASYNC_WRITE 默认开启）时，run() 只把记录
    投递进有界队列立即返回，磁盘写入（图像编码 + catalog 落盘）由后台线程串行
    执行——同步写会把录制时毫秒级的磁盘抖动直接灌进车辆主循环，任一轮超时即
    掉帧。队列满时丢最旧、保最新（计数并限频告警）；new_tub 的换 tub 命令与
    记录共用同一队列，先后顺序天然保持；close/shutdown 排空队列后再关闭。
    """
    _SENTINEL = object()

    def __init__(self, base_path, inputs=[], types=[], metadata=[],
                 max_catalog_len=1000, async_write=False, queue_size=120):
        self.inputs = inputs
        self.types = types
        self.metadata = metadata
        self.max_catalog_len = max_catalog_len
        self.tub = Tub(base_path, inputs, types, metadata, max_catalog_len)
        self.async_write = bool(async_write)
        self._queue = None
        self._thread = None
        self._dropped = 0
        if self.async_write:
            # 120 条 ≈ 60Hz 下 2s 抖动缓冲；320x240 图像约占 30MB 内存上限
            self._queue = queue.Queue(maxsize=queue_size)
            self._thread = threading.Thread(
                target=self._writer_loop, name='tub-writer', daemon=True)
            self._thread.start()

    def num_records(self):
        """已落盘 + 仍在队列中的记录数（TubRotator 判断是否需要换 tub 用）。"""
        count = self.tub.manifest.current_index
        if self.async_write and self._queue is not None:
            count += self._queue.qsize()
        return count

    def new_tub(self, base_path):
        """
        Close the current tub and switch to a fresh one with the same
        schema. Recording continues in the new tub with the record count
        (manifest.current_index) restarting from zero.
        """
        if self.async_write:
            if self._thread is not None:
                # 换 tub 命令进同一队列串行化：此前入队的记录仍写进旧 tub
                self._enqueue(('tub', base_path))
                return
            self._close_tub()
            self.tub = Tub(base_path, self.inputs, self.types, self.metadata,
                           self.max_catalog_len)
            return
        self.close()
        self.tub = Tub(base_path, self.inputs, self.types, self.metadata,
                       self.max_catalog_len)

    def _enqueue(self, item):
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except queue.Full:
                # 丢最旧保最新：驾驶录制里越新的数据越接近当前操控意图
                try:
                    self._queue.get_nowait()
                    self._dropped += 1
                    if self._dropped % 100 == 1:
                        print(f"[TubWriter] 写入队列已满，丢弃最旧记录"
                              f"（累计 {self._dropped} 条）；磁盘写入跟不上录制帧率")
                except queue.Empty:
                    pass

    def _writer_loop(self):
        while True:
            item = self._queue.get()
            if item is self._SENTINEL:
                break
            kind, payload = item
            try:
                if kind == 'record':
                    self.tub.write_record(payload)
                elif kind == 'tub':
                    self._close_tub()
                    self.tub = Tub(payload, self.inputs, self.types,
                                   self.metadata, self.max_catalog_len)
            except Exception as e:
                # 单条失败不能拖死 writer 线程，继续消费后续记录
                print(f"[TubWriter] 后台写入失败: {e}")

    def _close_tub(self):
        try:
            self.tub.close()
        except Exception as e:
            logger.warning(f"Closing tub {self.tub.base_path} failed: {e}")

    def _flush_and_stop_worker(self):
        if self._thread is None:
            return
        # 哨兵排在队列尾：先入队的记录都会被写完再退出
        self._queue.put(self._SENTINEL)
        self._thread.join(timeout=10.0)
        self._thread = None

    def run(self, *args):
        assert len(self.tub.inputs) == len(args), \
            f'Expected {len(self.tub.inputs)} inputs but received {len(args)}'
        record = dict(zip(self.tub.inputs, args))
        if self.async_write:
            self._enqueue(('record', record))
            # 返回已落盘记录数；队列未排空时略滞后于投递数（被丢弃的记录不计入）
            return self.tub.manifest.current_index
        self.tub.write_record(record)
        return self.tub.manifest.current_index

    def __iter__(self):
        return self.tub.__iter__()

    def close(self):
        if self.async_write:
            self._flush_and_stop_worker()
        self._close_tub()

    def shutdown(self):
        self.close()


class TubRotator:
    """
    Donkey part which starts a new tub on each rising edge of the
    'recording' flag, so every recording session begins with a record
    count of zero instead of appending to the previously filled tub.
    The current tub is only rotated when it already holds records;
    an empty tub (e.g. freshly created at drive start) is reused.
    """
    def __init__(self, tub_writer, data_path):
        """
        :param tub_writer: the TubWriter part whose tub gets rotated
        :param data_path: data directory the new tub path is created in
        """
        self.tub_writer = tub_writer
        self.data_path = data_path
        self._was_recording = False

    def run(self, recording):
        if recording and not self._was_recording:
            # 延迟 import 避免 datastore <-> tub_v2 循环依赖
            from donkeycar.parts.datastore import TubHandler
            # 异步 TubWriter 下 current_index 只含已落盘数，须叠加队列中的
            # 待写记录，否则写盘滞后时上一段会话被误判为空 tub 而不轮转
            if hasattr(self.tub_writer, 'num_records'):
                has_records = self.tub_writer.num_records() > 0
            else:
                has_records = self.tub_writer.tub.manifest.current_index > 0
            if has_records:
                tub_path = TubHandler(path=self.data_path).create_tub_path()
                self.tub_writer.new_tub(tub_path)
        self._was_recording = recording


class TubWiper:
    """
    Donkey part which deletes a bunch of records from the end of tub.
    This allows to remove bad data already during recording. As this gets called
    in the vehicle loop the deletion runs only once in each continuous
    activation. A new execution requires to release of the input trigger. The
    action could result in a multiple number of executions otherwise.
    """
    def __init__(self, tub, num_records=20):
        """
        :param tub: tub to operate on
        :param num_records: number or records to delete
        """
        self._tub = tub
        self._num_records = num_records
        self._active_loop = False

    def run(self, is_delete):
        """
        Method in the vehicle loop. Delete records when trigger switches from
        False to True only.
        :param is_delete: if deletion has been triggered by the caller
        """
        # only run if input is true and debounced
        if is_delete:
            if not self._active_loop:
                # action command
                self._tub.delete_last_n_records(self._num_records)
                # increase the loop counter
                self._active_loop = True
        else:
            # trigger released, reset active loop
            self._active_loop = False