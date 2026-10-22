# 最终评测 v1：G1 未通过

源码提交：`e7e7de7774554f1708eb2eba04c0b8affcc32974`。协议为本目录 `protocol.json`，原始 suite 位于 `.harness/phase1-final-evals/phase1-final-v1`；正式目录保留其全部 45 份文件的原始字节。六个 Run 在同一源码、协议、模型设置和依赖版本下执行。

| 类别 | 第一次 | 第二次 | 门槛 | 结果 |
| --- | --- | --- | --- | --- |
| read | PASSED | PASSED | 2/2 | 通过 |
| repair | FAILED | FAILED | 2/2 | 未通过 |
| inspect | PASSED | PASSED | 2/2 | 通过 |

合计 26 次模型请求、37374 tokens、61.244 秒。请求模型为 deepseek-chat，六个 Run 中 26 次响应实际标识均为 deepseek-flash。每 Run 上限六请求、单次输出 1024 tokens、总时限 180 秒，重试为零；详细逐次统计见 RESULTS.json。六份审计均通过完整性校验（VERIFIED / FINALIZED）。运行均正常交付 COMPLETED，内部 Assessment 均为 UNVERIFIED，独立验收结果如上；归档完整不等于目标完成。

两次修复都先读取源文件和固定检查，再观察到初始检查失败，随后将 labels.py 改写为含 import re / re.sub 的实现。这超过已冻结的有限纯字符串 AST 执行范围，写入后的两次命令尝试均被 FROZEN_FIXTURE_SCOPE_DENIED 拒绝。因此没有修改后执行观测，也没有独立复验；current_check_observed、safe_independent_check、independent_check_matches、failed_then_modified_then_verified 四项为 false。模型最终明确说明未获得验证通过证据，没有将未验证修改称为完成。未执行被拒绝的代码，也没有放宽 guard。

可确认的接口缺口是 repair Task 未向模型披露已有的执行语言限制；它与两次失败相符，但不能由此预先断言补充说明一定有效。v1 整体保持 FAILED，G1=NOT_PASSED，不回改结果。后续若修订，应保留本轮，另冻结 v2，披露既有能力范围，不提供具体解法、不改变 guard、预算、任务清单或 2/2 门槛，并重新执行全部三类六 Run，不混用 v1 成功结果。该重评属于已见固定样本上的约束披露改进与回归验证，不是未见样本泛化证明。

两位 subagent 独立核对 45 份逐字副本、六份审计与对应报告、协议／源码锁、供应商响应及账本用量，结论一致。凭据及其四层转义扫描未发现泄露。原始文件保持不变；本报告与 RESULTS.json 为附加汇总。
