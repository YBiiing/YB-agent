import getpass


class KeyManager:
    SERVICE = "harness"
    USERNAME = "api_key"

    def status(self) -> dict:
        try:
            import keyring
            key = keyring.get_password(self.SERVICE, self.USERNAME)
            return {
                "stored": key is not None,
                "backend": self._detect_backend(),
            }
        except Exception as e:
            return {"stored": False, "error": str(e)}

    def set_key(self) -> None:
        print("请输入你的 API key（输入将被隐藏）:")
        key = getpass.getpass("API key: ")
        if not key.strip():
            print("错误: key 不能为空")
            return
        try:
            import keyring
            keyring.set_password(self.SERVICE, self.USERNAME, key.strip())
            print("API key 已安全存储。")
        except Exception as e:
            print(f"存储 key 失败: {e}")
            print("备用方案: 设置 HARNESS_API_KEY 环境变量或 .env 文件")

    def clear_key(self) -> None:
        try:
            import keyring
            keyring.delete_password(self.SERVICE, self.USERNAME)
            print("API key 已删除。")
        except Exception as e:
            print(f"删除 key 失败: {e}")

    def _detect_backend(self) -> str:
        import platform
        system = platform.system()
        if system == "Windows":
            return "Windows Credential Manager"
        elif system == "Darwin":
            return "macOS Keychain"
        else:
            return "Linux Secret Service / keyring"