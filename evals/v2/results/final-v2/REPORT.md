# 最终重评 v2：G1 仍未通过

源码提交 `cc74628f0145d4f828f220186525db879f5cefaa`，协议见 protocol.json。v2 仅显式披露既有有限字符串 AST 能力；任务清单、执行 guard、验收规则、预算及各类 2/2 门槛均未改变。全部三类重新执行，未复用 v1 成功项。

| 类别 | 第一次 | 第二次 | 结果 |
| --- | --- | --- | --- |
| read | PASSED | PASSED | 2/2 |
| repair | PASSED | FAILED | 1/2 |
| inspect | PASSED | PASSED | 2/2 |

合计 25 请求、39547 tokens、65.893 秒；请求 deepseek-chat，六 Run 的全部 25 次响应实际标识为 deepseek-flash。每 Run 最多六请求、输出 1024 tokens／次、总时限 180 秒、零重试。六 Run 均 COMPLETED，内部 UNVERIFIED，审计完整性 VERIFIED／FINALIZED。原 suite 的全部 49 份文件逐字节复制并核对，见 RESULTS.json 与各类别原始记录；已知凭据及四层转义扫描未发现泄露。

两次修复都生成 guard 允许的实现，均可靠观察初始检查失败及修改后的 exit=0／LABEL_CHECK_PASS。第一次还通过独立复验。第二次随后尝试 read_artifact：供应商请求确实向模型公开该工具，但 fixture 策略与验收范围仅接受 read_file／write_file／run_command，因此该调用被 FROZEN_FIXTURE_SCOPE_DENIED 拒绝，no_scope_violation=false，独立复验未执行，independent_check_matches=false。最终声明区分了命令预览与未能读取制品，不把被拒制品读取称为成功。即使已有通过预览，仍不能回改范围验收或事后补跑独立检查。

v2 整体 FAILED，G1=NOT_PASSED。新发现的是评测提供的工具定义与实际策略不一致，不是 AST 执行失败。下一修订拟仅在新 v3 协议中，将模型收到的 action 工具定义投影为该 fixture 实际允许的三个工具；通用 CommandTools 与 read_artifact 能力不变，旧 v1／v2 保持历史定义，硬拒绝与独立判据不放宽。若模型仍输出隐藏工具，继续拒绝并按失败处理。修订前需交叉审核和提交，随后三类全部重评，不能挑跑修复类别或混用成功项。

v1 与本轮均永久保留失败。所有后续结论仅适用于已见固定样本的接口一致性改进与回归，不是未见任务泛化证明。
