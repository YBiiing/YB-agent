# 第一阶段契约回归映射

P1-10 针对 DESIGN.md 的第一阶段执行契约整理实际回归。此表列出代表性测试；测试数量不是能力成功率，离线供应商响应不代表真实模型评测。

## 不变量与机制场景

下表文件均位于 `tests/v2/`，测试名为可直接检索的真实函数名。

| 场景／不变量 | 代表性测试 | 证明范围 |
| --- | --- | --- |
| I-01 终态不可再调度 | `test_controller.py::test_completed_run_is_terminal_and_not_automatically_verified`；`test_control.py::test_cancelled_run_ignores_late_resume_or_approval` | 正常与取消终态不可由继续／迟到审批复活，重做需要新 Run |
| I-02 决策／尝试唯一且批次完整 | `test_engine.py::test_multistep_model_uses_observations_and_complete_call_groups`；`test_duplicate_call_ids_fail_before_second_tool_attempt` | 多步真实工具反馈、每 Step 单决定、跨 Step 重复调用 ID 拒绝 |
| 明确失败／混合结果 | `test_engine.py::test_batch_feedback_contains_failure_denial_and_success`；`test_command_tools.py::test_real_tool_loop_observes_failure_repairs_and_rechecks` | 可靠失败观测可继续驱动下一次决策；非零退出不冒充工具系统未知 |
| I-03 硬拒绝、待审批不执行 | `test_execution_approval.py::test_executor_receives_no_call_before_approval_and_batch_resume_never_repeats`；`test_later_hard_deny_is_enforced_without_creating_approval_or_starting_executor` | 硬规则优先，批准之前执行器无调用 |
| I-04 动作／资源版本绑定 | `test_execution_approval.py::test_resource_change_at_admission_requires_new_approval`；`test_command_tools.py::test_dispatch_rechecks_admitted_input_versions` | 审批时与启动时资源变化不能沿用旧许可；限于受控单写者边界，不是文件系统 CAS |
| I-05 取消与许可排序 | `test_engine.py::test_control_winning_immediately_before_boundary_is_a_normal_outcome`；`test_command_tools.py::test_controller_cancel_waits_for_tree_confirmation_and_skips_next_call` | 控制先到不启动，已开始的命令等待实际停止观测，副作用不承诺撤销 |
| 暂停／继续不重复 | `test_engine.py::test_pause_caches_model_response_until_same_process_resume`；`test_control.py::test_control_pause_mid_batch_resumes_only_unobserved_calls` | 模型有效响应缓存和未执行批次保留，同一进程继续不会重发或重复调用 |
| I-06 UNKNOWN 不盲重试 | `test_model_retries.py::test_tool_unknown_is_not_retried_even_when_model_retries_enabled`；`test_contract_scenarios.py::test_approved_effect_then_output_failure_is_archived_as_unknown_without_next_action` | 实际批准命令发生副作用但制品失败后只执行一次，后续 SKIPPED，档案保留未知事项 |
| I-07 完成与验收分开 | `test_evidence.py::test_model_claim_alone_is_unverified_and_criteria_have_explicit_missing_verdict`；`test_actual_file_change_invalidates_prior_validation_without_running_a_new_action`；`test_required_failure_cannot_be_outvoted_and_partial_and_optional_semantics_are_explicit` | 声明不是验证、旧资源版本失效、必需失败不能被多数通过覆盖；检查仅覆盖明确列出的范围 |
| I-08 外部数据不提权 | `test_evidence.py::test_external_tool_json_cannot_promote_itself_to_independent_validation`；`test_context.py::test_injection_text_stays_external_data_and_does_not_replace_constraints`；`test_read_tools.py::test_sensitive_or_escaping_paths_never_return_content` | 外部文本不成为授权或独立验收，工具路径边界保持 |
| I-10 模型意图／预留／发送排序 | `test_model_budget.py::test_control_during_preparation_releases_reservation_without_send`；`test_reservation_and_intent_precede_controller_admission`；`test_engine.py::test_cancel_inflight_model_does_not_accept_late_decision` | 未发送释放预留，在途未知费用保守计入，迟到响应不推进已取消 Run |
| 有限模型重试及等待预算 | `test_model_retries.py`；`test_operator_input.py::test_approval_wait_and_pause_accumulate_separately_across_resume`；`test_operator_input.py` | 只对白名单错误有限重发，重试服从总额度；审批／暂停时间累计独立计量，输入 EOF 不批准 |
| 上下文／制品边界 | `test_context.py::test_adapter_compaction_prepares_only_one_recorded_request_and_preserves_group`；`test_strict_context_budget_still_reads_real_command_tail_without_incomplete_tool_groups`；`test_artifacts.py` | native／JSON 完整批次、严格字节限额、真实命令尾部按 ID 读取；原 Run 观测不压缩 |
| 归档失败与读取不完整记录 | `test_archive.py`；`test_audit_execution.py::test_audit_failure_before_model_send_releases_unsent_intent`；`test_final_archive_failure_is_visible_without_rewriting_terminal_state`；`test_final_response_archive_delay_cannot_complete_after_total_deadline` | 许可前记录失败不派发，结果不抹除，最终审计失败明确非零；半记录和哈希不符不返回完整报告 |
| 旧版兼容与录制回放 | `tests/unit/`；`tests/demo/`；`test_recorded_read_baseline.py`；`test_recorded_action_baselines.py` | 旧行为无已知回归；六次开发基线请求／供应商响应／工具观测可离线复核，不冒充新的真实模型调用 |

I-09 属于第二阶段执行资格／失联接管契约，第一阶段没有 Worker、租约或跨进程接管，不把本地文件记录作为它的实现证据。

## 验证入口与证据

```powershell
python scripts/run_phase1_tests.py tests/v2 tests/unit tests/demo -q
python -m ruff check src tests scripts
```

安全测试入口在导入 pytest 之前隔离系统 keyring，并管理本仓库测试目录。普通回归不调用真实 API。P1-01 在相同隔离条件下旧 unit/demo 基线为 149 passed；首次未隔离凭据／临时目录错误有单独归因，不能将其重述为业务缺陷。

P1-10 首轮全量结果：595 passed、2 skipped、1 条既有 Starlette 弃用警告，62.54 秒。此后新增完整审批→真实副作用→输出保存失败→UNKNOWN→审计／验收场景，专项 1 passed；没有修改旧测试或弱化断言。两项 skip 源于本机 symlink 创建权限，不能声称这两条已验证；实际 Windows junction、硬链接及进程树场景均有独立通过测试。

当前支持声明限于本机实际验证的 Windows 行为；控制台键盘部分为模拟回归，Linux 命令拒绝执行，Linux 控制／文件／进程行为未完成验收。没有自动崩溃恢复、未知副作用自动重试、任意 Python OS 沙箱或完整依赖发现保证。
