# -*- coding: utf-8 -*-
"""
Created on Wed Sep 13 21:27:44 2017

@author: wroscoe
"""
import os
import types
import logging

logger = logging.getLogger(__name__)


def _deep_merge_dicts(base, override):
    """递归合并两个 dict：override 的键覆盖 base，嵌套 dict 逐键合并。

    用于 myconfig 覆盖 config.py 的 dict 型配置（如 GYM_CONF）：myconfig
    只需声明要改的键，config.py 后续新增的键不再被整体重定义静默丢失。
    非 dict 值（标量/list/tuple）一律整体替换。
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


class Config:

    def from_pyfile(self, filename):
        d = types.ModuleType('config')
        d.__file__ = filename
        try:
            with open(filename, mode='rb') as config_file:
                exec(compile(config_file.read(), filename, 'exec'), d.__dict__)
        except IOError as e:
            e.strerror = 'Unable to load configuration file (%s)' % e.strerror
            raise
        self.from_object(d)
        return True

    def from_object(self, obj):
        """拷贝 obj 的全大写属性；dict 值与已有同名 dict 做键级深合并，其余整体覆盖。"""
        for key in dir(obj):
            if key.isupper():
                value = getattr(obj, key)
                if isinstance(value, dict):
                    existing = getattr(self, key, None)
                    if isinstance(existing, dict):
                        value = _deep_merge_dicts(existing, value)
                setattr(self, key, value)

    def from_dict(self, d, keys=[]):
        msg = 'Overwriting config with: '
        for k, v in d.items():
            if k.isupper():
                if k in keys or not keys:
                    setattr(self, k, v)
                    msg += f'{k}:{v}, '
        logger.info(msg)

    def __str__(self):
        result = []
        for key in dir(self):
            if key.isupper():
                result.append((key, getattr(self, key)))
        return str(result)

    def show(self):
        for attr in dir(self):
            if attr.isupper():
                print(attr, ":", getattr(self, attr))

    def to_pyfile(self, path):
        lines = []
        for attr in dir(self):
            if attr.isupper():
                v = getattr(self, attr)
                if isinstance(v, str):
                    v = f'"{v}"'
                lines.append(f'{attr} = {v}{os.linesep}')
        with open(path, 'w') as f:
            f.writelines(lines)


def load_config(config_path=None, myconfig="myconfig.py"):
    
    if config_path is None:
        main_path = os.getcwd()
        config_path = os.path.join(main_path, 'config.py')
        if not os.path.exists(config_path):
            local_config = os.path.join(os.path.curdir, 'config.py')
            if os.path.exists(local_config):
                config_path = local_config
    
    logger.info(f'loading config file: {config_path}')
    cfg = Config()
    cfg.from_pyfile(config_path)

    # look for the optional myconfig.py in the same path.
    personal_cfg_path = config_path.replace("config.py", myconfig)
    if os.path.exists(personal_cfg_path):
        logger.info(f"loading personal config over-rides from {myconfig}")
        personal_cfg = Config()
        personal_cfg.from_pyfile(personal_cfg_path)
        cfg.from_object(personal_cfg)
    else:
        logger.warning(f"personal config: file not found {personal_cfg_path}")

    return cfg
