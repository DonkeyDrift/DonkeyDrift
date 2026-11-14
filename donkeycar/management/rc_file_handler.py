import atexit
from datetime import datetime
import logging
import os
from collections import namedtuple

import yaml

logger = logging.getLogger(__name__)

# Data struct to show tub field in the progress bar, containing the name,
# the name of the maximum value in the config file and if it is centered.
FieldProperty = namedtuple('FieldProperty',
                           ['field', 'max_value_id', 'centered'])


def recursive_update(target, source):
    """ Recursively update dictionary """
    if isinstance(target, dict) and isinstance(source, dict):
        for k, v in source.items():
            v_t = target.get(k)
            if not recursive_update(v_t, v):
                target[k] = v
        return True
    else:
        return False


def log_safe(level, msg):
    """ atexit 阶段日志句柄/捕获流可能已关闭（如 pytest 退出），日志失败
        不应中断 rc 文件持久化；logging 内部的错误报告也一并静默。 """
    prev = logging.raiseExceptions
    logging.raiseExceptions = False
    try:
        logger.log(level, msg)
    except Exception:
        pass
    finally:
        logging.raiseExceptions = prev


class RcFileHandler:
    """ This handles the config file which stores the data, like the field
        mapping for displaying of bars and last opened car, tub directory. """

    # These entries are expected in every tub, so they don't need to be in
    # the file
    known_entries = [
        FieldProperty('user/angle', '', centered=True),
        FieldProperty('user/throttle', '', centered=False),
        FieldProperty('pilot/angle', '', centered=True),
        FieldProperty('pilot/throttle', '', centered=False),
    ]

    def __init__(self, file_path='~/.donkeyrc'):
        self.file_path = os.path.expanduser(file_path)
        self.data = self.create_data()
        recursive_update(self.data, self.read_file())
        self.field_properties = self.create_field_properties()

        def exit_hook():
            self.write_file()
        # Automatically save config when program ends
        atexit.register(exit_hook)

    def create_field_properties(self):
        """ Merges known field properties with the ones from the file """
        field_properties = {entry.field: entry for entry in self.known_entries}
        field_list = self.data.get('field_mapping')
        if field_list is None:
            field_list = {}
        for entry in field_list:
            assert isinstance(entry, dict), \
                'Dictionary required in each entry in the field_mapping list'
            field_property = FieldProperty(**entry)
            field_properties[field_property.field] = field_property
        return field_properties

    def create_data(self):
        data = dict()
        data['user_pilot_map'] = {'user/throttle': 'pilot/throttle',
                                  'user/angle': 'pilot/angle'}
        data['pilots'] = []
        data['config_params'] = []
        return data

    def read_file(self):
        if os.path.exists(self.file_path):
            with open(self.file_path) as f:
                data = yaml.load(f, Loader=yaml.FullLoader)
                log_safe(logging.INFO,
                         f'Donkeyrc: Donkey file {self.file_path} loaded.')
                return data
        else:
            log_safe(logging.WARNING,
                     f'Donkeyrc: Donkey file {self.file_path} does not '
                     f'exist.')
            return {}

    def write_file(self):
        if os.path.exists(self.file_path):
            log_safe(logging.INFO,
                     f'Donkeyrc: Donkey file {self.file_path} updated.')
        with open(self.file_path, mode='w') as f:
            self.data['time_stamp'] = datetime.now()
            data = yaml.dump(self.data, f)
            return data


rc_handler = RcFileHandler()
