
import unittest
from unittest.mock import MagicMock, patch
import re
import os
import sys

# Add project root to path to ensure we can import donkeycar
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from donkeycar.management.train_online import OnlineTrainer

class TestOnlineTrainerWorkspace(unittest.TestCase):
    def setUp(self):
        # Patch _load_config to avoid file operations during init
        with patch.object(OnlineTrainer, '_load_config', return_value={}) as mock_load:
            self.trainer = OnlineTrainer()
        
        # Mock dependencies
        self.trainer.config = MagicMock()
        self.trainer.get_config_value = MagicMock(return_value="~/projects")
        self.trainer._resolve_remote_path = MagicMock(return_value="/home/user/projects")
        self.trainer.ssh_client = MagicMock()
        self.trainer.ssh_client.get_transport = MagicMock(return_value=MagicMock(active=True))
        
        # Mock logging to avoid file writes
        self.trainer._log = MagicMock()

    def test_generate_workspace_name_format(self):
        """测试目录命名格式正确性: mycar-YYMMDD-XXX-ABCD"""
        date_str = "231027"
        name = self.trainer._generate_workspace_name([], date_str=date_str)
        
        # Verify prefix and date
        self.assertTrue(name.startswith(f"mycar-{date_str}-"))
        
        # Verify format using regex
        pattern = re.compile(rf"^mycar-{date_str}-(\d{{3}})-[0-9A-Z]{{4}}$")
        self.assertTrue(pattern.match(name), f"Name {name} does not match expected format")

    def test_generate_workspace_name_increment(self):
        """测试序号递增逻辑"""
        date_str = "231027"
        existing = [
            f"mycar-{date_str}-001-AAAA",
            f"mycar-{date_str}-002-BBBB"
        ]
        name = self.trainer._generate_workspace_name(existing, date_str=date_str)
        self.assertIn("-003-", name)

    def test_generate_workspace_name_first_run(self):
        """测试每日首次运行序号从001开始"""
        date_str = "231027"
        existing = [] # No existing dirs for this day
        name = self.trainer._generate_workspace_name(existing, date_str=date_str)
        self.assertIn("-001-", name)

    def test_generate_workspace_name_gap(self):
        """测试序号存在空缺时的处理（应取最大值+1）"""
        date_str = "231027"
        existing = [
            f"mycar-{date_str}-001-AAAA",
            f"mycar-{date_str}-005-BBBB"
        ]
        name = self.trainer._generate_workspace_name(existing, date_str=date_str)
        self.assertIn("-006-", name)

    def test_generate_workspace_name_random_code_uniqueness(self):
        """测试随机码生成"""
        name1 = self.trainer._generate_workspace_name([], date_str="231027")
        name2 = self.trainer._generate_workspace_name([], date_str="231027")
        
        # Even if seq is same (001), random code likely different
        # Note: Since random is used, there's a tiny chance of collision, but very small.
        # We mainly check format here.
        code1 = name1.split('-')[-1]
        self.assertEqual(len(code1), 4)
        for char in code1:
            self.assertTrue(char.isdigit() or (char.isalpha() and char.isupper()))

    @patch('donkeycar.management.train_online.console')
    def test_setup_remote_workspace_success(self, mock_console):
        """测试目录创建成功流程"""
        # Mock SSH responses
        # 1. Check parent dir: success (exit 0)
        # 2. List dir: empty (return "")
        # 3. Create car: success (exit 0)
        # 4. uname -s: Linux (macOS 补丁检查，非 Darwin 直接跳过)

        stdout_ok = MagicMock(channel=MagicMock(recv_exit_status=lambda: 0))
        stdout_ls = MagicMock(read=lambda: b"")
        stdout_uname = MagicMock(read=lambda: b"Linux\n")

        self.trainer.ssh_client.exec_command.side_effect = [
            (None, stdout_ok, None), # check parent
            (None, stdout_ls, None), # ls
            (None, stdout_ok, None), # createcar
            (None, stdout_uname, None), # uname -s
        ]

        path = self.trainer.setup_remote_workspace()

        # Verify path
        self.assertTrue(path.startswith("/home/user/projects/mycar-"))
        self.assertEqual(self.trainer.remote_work_dir, path)

        # Verify createcar command was called with full path
        calls = self.trainer.ssh_client.exec_command.call_args_list
        createcar_cmd = calls[2][0][0]
        self.assertIn("createcar --path", createcar_cmd)
        self.assertIn(path, createcar_cmd)

        # 非 macOS 远端不应执行 sed 补丁
        all_cmds = [c[0][0] for c in calls]
        self.assertFalse(any("sed -i" in cmd for cmd in all_cmds))

    @patch('donkeycar.management.train_online.console')
    def test_setup_remote_workspace_parent_fail(self, mock_console):
        """测试父目录不可写时抛出PermissionError"""
        # Mock SSH responses
        # 1. Check parent dir: fail (exit 1)
        
        stdout_fail = MagicMock(channel=MagicMock(recv_exit_status=lambda: 1))
        
        self.trainer.ssh_client.exec_command.side_effect = [
            (None, stdout_fail, None), # check parent
        ]
        
        with self.assertRaises(PermissionError):
            self.trainer.setup_remote_workspace()

    @patch('donkeycar.management.train_online.console')
    def test_setup_remote_workspace_retry(self, mock_console):
        """测试目录冲突时的重试逻辑"""
        # Mock SSH responses
        # 1. Check parent dir: success
        # 2. List dir: returns existing "mycar-..."
        # 3. Create car attempt 1: fail (File exists)
        # 4. Create car attempt 2: success
        # 5. uname -s: Linux (macOS 补丁检查)

        stdout_ok = MagicMock(channel=MagicMock(recv_exit_status=lambda: 0))
        stdout_ls = MagicMock(read=lambda: b"mycar-231027-001-AAAA")
        stdout_fail = MagicMock(channel=MagicMock(recv_exit_status=lambda: 1))
        stderr_exist = MagicMock(read=lambda: b"File exists")
        stdout_uname = MagicMock(read=lambda: b"Linux\n")

        self.trainer.ssh_client.exec_command.side_effect = [
            (None, stdout_ok, None), # check parent
            (None, stdout_ls, None), # ls
            (None, stdout_fail, stderr_exist), # createcar attempt 1
            (None, stdout_ok, None), # createcar attempt 2
            (None, stdout_uname, None), # uname -s
        ]

        path = self.trainer.setup_remote_workspace()

        # Should succeed eventually
        self.assertIsNotNone(path)
        # Verify exec_command called 5 times
        self.assertEqual(self.trainer.ssh_client.exec_command.call_count, 5)

    @patch('donkeycar.management.train_online.console')
    def test_setup_remote_workspace_max_retries_fail(self, mock_console):
        """测试超过最大重试次数抛出异常"""
        stdout_ok = MagicMock(channel=MagicMock(recv_exit_status=lambda: 0))
        stdout_ls = MagicMock(read=lambda: b"")
        stdout_fail = MagicMock(channel=MagicMock(recv_exit_status=lambda: 1))
        stderr_exist = MagicMock(read=lambda: b"File exists")

        # check, ls, fail, fail, fail
        self.trainer.ssh_client.exec_command.side_effect = [
            (None, stdout_ok, None),
            (None, stdout_ls, None),
            (None, stdout_fail, stderr_exist),
            (None, stdout_fail, stderr_exist),
            (None, stdout_fail, stderr_exist),
        ]

        with self.assertRaises(RuntimeError):
            self.trainer.setup_remote_workspace()

    @patch('donkeycar.management.train_online.console')
    def test_setup_remote_workspace_macos_patches_train_py(self, mock_console):
        """macOS 远端：createcar 成功后对 train.py 执行 sed 禁用 mixed_float16"""
        stdout_ok = MagicMock(channel=MagicMock(recv_exit_status=lambda: 0))
        stdout_ls = MagicMock(read=lambda: b"")
        stdout_uname = MagicMock(read=lambda: b"Darwin\n")

        self.trainer.ssh_client.exec_command.side_effect = [
            (None, stdout_ok, None), # check parent
            (None, stdout_ls, None), # ls
            (None, stdout_ok, None), # createcar
            (None, stdout_uname, None), # uname -s
            (None, stdout_ok, None), # sed patch
        ]

        path = self.trainer.setup_remote_workspace()

        calls = self.trainer.ssh_client.exec_command.call_args_list
        self.assertEqual(calls[3][0][0], "uname -s")
        sed_cmd = calls[4][0][0]
        self.assertIn("sed -i", sed_cmd)
        self.assertIn("mixed_precision", sed_cmd)
        self.assertIn("set_global_policy", sed_cmd)
        self.assertIn(f"{path}/train.py", sed_cmd)
        # 日志应有补丁记录
        log_msgs = [c[0][0] for c in self.trainer._log.call_args_list]
        self.assertTrue(any("disabled mixed_float16" in m for m in log_msgs))

    @patch('donkeycar.management.train_online.console')
    def test_setup_remote_workspace_macos_patch_failure_non_fatal(self, mock_console):
        """macOS 远端 sed 补丁失败只记日志，不阻断训练流程"""
        stdout_ok = MagicMock(channel=MagicMock(recv_exit_status=lambda: 0))
        stdout_fail = MagicMock(channel=MagicMock(recv_exit_status=lambda: 1))
        stderr_fail = MagicMock(read=lambda: b"sed: command not found")
        stdout_ls = MagicMock(read=lambda: b"")
        stdout_uname = MagicMock(read=lambda: b"Darwin\n")

        self.trainer.ssh_client.exec_command.side_effect = [
            (None, stdout_ok, None), # check parent
            (None, stdout_ls, None), # ls
            (None, stdout_ok, None), # createcar
            (None, stdout_uname, None), # uname -s
            (None, stdout_fail, stderr_fail), # sed patch fails
        ]

        path = self.trainer.setup_remote_workspace()
        self.assertIsNotNone(path)

if __name__ == '__main__':
    unittest.main()
