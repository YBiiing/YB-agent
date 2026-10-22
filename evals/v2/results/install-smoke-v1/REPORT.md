# 独立安装与真实冒烟验证

- 日期：2026-10-22（Asia/Shanghai）。源码提交：`5a4891f29e653b768cf30274fc5de7d0ea71e784`，与本次文档修订前的生产代码一致。
- wheel：`harness-0.1.1-py3-none-any.whl`；SHA-256 `4102180f9682196f9d4ecfbbd656ad40538286d0c07bd4894fe3e9a2a2520021`。本地正式构建输出保留在 setup.json 指向的 wheels 目录，未发布。
- 环境：Windows／Python 3.13.7，新建 venv，未启用 system-site-packages；33 个已安装 distributions 的完整版本见 verification.json。新环境实际解析得到 openai 3.36.1、httpx 0.28.1、keyring 25.7.0、PyYAML 6.0.3、fastapi 0.159.1、uvicorn 0.54.0、socksio 1.0.0。未升级原系统环境，不据此宣称所有依赖版本兼容。

## 实际检查

- 通过默认隔离构建生成 wheel，安装 wheel 加 proxy extra 及全部运行依赖；`pip check` 通过。
- 清除 PYTHONPATH、禁用 user site，从仓库目录外运行 `harness-v2 --help`、`harness --help` 和 `python -m src.v2 --help`，均返回 0。导入路径实际位于新环境 site-packages，未借用源码目录。
- 安装后的 mock 完成实际文件读取与最终报告、独立归档查询，返回内容、报告完全对应，Assessment=UNVERIFIED。
- 安装后的 CommandTools 经正常审批实际执行合成 Python 脚本，退出 0、tree_stopped=true、观测到 INSTALLED_CHECK_OK；归档正常。它是离线机制验证，没有模型费用。
- wheel 包含 V2 核心与原 Web 模板；旧入口帮助仍可用，没有声称完整旧 REPL／Web 在该新环境逐项验收。

## 真实模型冒烟

新环境读取合成 README.md，内容仅为 INSTALL_SMOKE_42 加换行；使用本机已有显式配置和安全凭据，没有发送私有项目代码。

- 一次 Run，最多两个 Step／两个实际模型请求、重试 0、每次输出最多 1024 tokens、输入最多 16384 bytes、总时限 60 秒；SDK 重试 0。
- 实际两次请求、一次只读工具，1257 tokens、6.239 秒。请求名称 deepseek-chat，供应商响应 deepseek-flash；原始脱敏请求／响应、用量和完整报告位于 run/ 子目录。
- Run=COMPLETED，audit=FINALIZED，Assessment=UNVERIFIED。独立后置核对实际读到了标记、答案包含该标记，以及调用前后的文件内容 SHA 一致；这是一条窄冒烟，不是三类任务的最终能力评测。
- 调用前 mock 档案保存在 preflight/，用于独立复核最初文件哈希。两份归档重新读取均完整性通过，复制内容逐字保持原文件；本次已知凭据及四层转义扫描未出现泄露。

## 环境与验证事件

首次自行使用 `--no-build-isolation`，本机没有 setuptools.build_meta，构建尚未成功、没有模型请求。改用 pip 默认隔离构建后成功，无须修改系统 Python。fresh install 共 190.302 秒；这不是依赖安装卡住未完成。

真实调用后的初始后置断言误用 LF 字节常量，而测试准备的 write_text 在 Windows 产生 CRLF，导致 wrapper 报 input_unchanged=false。原误判 summary 保留为 real-smoke-result.json；后续直接用调用前已保存的 mock 观测哈希与当前文件 SHA 对照，得到一致，修正依据和结果见 real-smoke-verified.json。未删除原始尝试、改输入文件或重新请求模型。

完整 wheel／临时安装与原始档案的位置见 setup.json。虚拟环境属于本次验证临时内容，审查完成后可清理，wheel 和正式本目录证据保留；历史路径用于记录当时的导入来源，不表示临时环境长期存在。
