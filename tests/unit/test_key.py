import pytest
from unittest.mock import patch
from src.cli.key import KeyManager


class TestKeyManager:
    def test_状态无key(self):
        with patch("keyring.get_password", return_value=None):
            mgr = KeyManager()
            info = mgr.status()
            assert info["stored"] is False

    def test_状态有key(self):
        with patch("keyring.get_password", return_value="sk-test123"):
            mgr = KeyManager()
            info = mgr.status()
            assert info["stored"] is True
            assert "sk-test123" not in str(info)

    def test_设置key(self):
        with patch("keyring.set_password") as mock_set, \
             patch("getpass.getpass", return_value="sk-abc123"):
            mgr = KeyManager()
            mgr.set_key()
            mock_set.assert_called_once_with("harness", "api_key", "sk-abc123")

    def test_清除key(self):
        with patch("keyring.delete_password") as mock_delete, \
             patch("keyring.get_password", return_value="sk-test"):
            mgr = KeyManager()
            mgr.clear_key()
            mock_delete.assert_called_once_with("harness", "api_key")