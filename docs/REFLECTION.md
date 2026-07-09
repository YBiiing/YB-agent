# 反思报告

> AI4SE 期末项目 · A · Coding Agent Harness
>
> 本文由我本人撰写，部分表述经 AI 辅助润色。

---

## 一、Superpowers 技能：哪些有用，哪些走形式

整个项目按 Superpowers 七步流程走了一遍，有用程度差别很大。

brainstorming 是我觉得最有价值的技能。它会在你给出一句话需求后持续追问边界条件，比如 harness 和普通脚本有什么区别，移除 LLM 后代码还剩什么，危险动作的判定优先级你写了吗。最后产出的核心概念澄清表比功能列表更有用，它定的是项目底线的边界。

test-driven-development 也很关键。它把先红后绿变成了硬规则，subagent 不能跳过写失败测试直接交实现。项目 106 个测试全部基于 mock LLM 且不依赖网络，能做到这点，TDD 的硬约束是关键原因。

using-git-worktrees 对我的项目基本没用。单人开发、单分支迭代、没有真正的 PR review 流程，worktree 的隔离价值完全体现不出来。我开了 8 个 worktree 分支，但后面 task 粒度太小、依赖太密，直接在 main 上做了。

requesting-code-review 的 reviewer agent 确实抓到过一些具体问题，比如主循环里 result.output[:500] 在 output 为 None 时会 TypeError，OpenAI 适配器的异常捕获太窄。但大部分 review 输出是 Spec ✅, Quality Approved, Minor 问题：缺末尾换行。这句话在我的 AGENT_LOG 里出现了五六次，到后面我已经不信了。

finishing-a-development-branch 更像个象征性收尾，对于没有 PR workflow 的项目，跟直接 commit 没区别。

---

## 二、TDD 在 AI 协作下的效果

对护栏、反馈解析、工具分发这类确定性逻辑，TDD 是完美的。你脑子里想清楚了这个函数吃 X 应该吐 Y，写成测试就是一句话，subagent 来填空。agent 写实现时不会偷懒跳过边界情况，因为它知道测试在等着它。

但对 CLI help 输出、WebUI HTML 响应、Dockerfile 构建成功这类集成验证，TDD 很别扭。test_cli_help_可运行 测试本质上是在验证 argparse 能打印帮助信息，跟 harness 的工程深度没关系，纯粹是交付清单逼出来的。我把这类测试叫做清单测试，它的存在价值是 CAS 通过而不是发现 bug。

总的来说 TDD 最大的功劳在于防住了 AI 的差不多就行心态，发现 bug 反而是次要的。subagent 在没有失败测试的情况下，倾向于写一个看起来对的实现然后声称做完了。失败测试逼它直面代码还没跑通这个事实。

---

## 三、Subagent 工作流：能跑多远不脱轨

纯粹机械任务（数据模型、LLM 抽象、工具、护栏、反馈解析）每个边界清晰，输入输出明确，subagent 基本不需要我来回纠正，跑两三个 task 不脱轨很正常。

到了 agent 主循环这种集成任务，问题就暴露了。brief 里的模板代码有隐藏 bug，result.output[:500] 在 output 为 None 时抛 TypeError。subagent 对集成后各模块的实际交互盲区很大，它不会主动推演如果上一步的 result 是 None这段代码还能不能跑。

gap fix 阶段我改了策略：不再把实现和修补交给同一个 subagent，而是先让一个 agent 写实现，再让另一个 reviewer agent 做对抗检查。效果好了不少，OpenAI 适配器的 review 就抓到了 except ImportError 太窄的问题。

关于 task 颗粒度，我认为最优的是一个职责加一个测试文件加两三个源文件。Agent 主循环太大，同时做了循环逻辑、上下文构建、step 记录、停机判断、异常处理，review 面太宽容易漏。Docker、CI、README 太小，三个 task 每个只有几十行，分给三个 subagent 不如一个人一口气做完。Action 解析器的粒度最好，一个类、一个测试文件、六个测试用例，十五分钟从红到绿。

---

## 四、SPEC / PLAN 质量如何影响实现质量

冷启动验证暴露了最典型的问题。PLAN.md 里写 config.yaml 由 Task 2 的 src/config.py 加载，但 Task 2 是数据模型，真正的 config.py 在 Task 8。写 plan 的 agent 把数据模型和配置加载器混为一谈了。

如果没做冷启动验证，后续 subagent 看到 Task 2 的产出里有 config.py，可能误以为配置加载器已经实现，在 Task 8 之前尝试 import 而失败。好在这个问题在修订阶段就修掉了。

另一个教训是 SPEC 里的模糊地带会在实现阶段放大。rm -rf / 同时命中 DangerousCmd（直接拦截）和 DestructiveOp（需审批），最终判定应该是什么？原 SPEC 没写，冷启动验证暴露后补上了拦截优先于审批的规则。如果没补，不同的 subagent 可能做出不同的实现，集成时出不一致。

我的结论：SPEC 和 PLAN 的清晰度能显著降低 subagent 的出错率。但写完美 SPEC 的成本可能比直接写实现还高，冷启动验证是性价比最高的折中方案。

---

## 五、最有效的 prompt / context 策略

第一条，brief 里放错误的实现示例比放正确的实现示例更有效。给 subagent 看一段假如你这样写会触发哪个测试失败的代码，它立刻知道边界在哪。纯文字描述需要注意 X 对 agent 基本无效。

第二条，每个 brief 开头写死一句话：不要猜测，不确定的地方停下来问，继续猜测是浪费时间。我第一次没加这句话的 task（agent 主循环），agent 瞎猜了 context builder 的接口，产出了一段能跑但逻辑错的代码。后来加了这句话，agent 停下来问的情况明显增多，虽然多花了一点交互时间，但避免了大方向跑偏。

第三条，review 阶段换一个 agent，别让同一个 agent 审自己的代码。implementer 和 reviewer 用不同 agent 实例且不共享上下文，reviewer 的发现率明显更高。

---

## 六、凭据与分发：被迫想清的事

keyring 不是银弹。我一开始以为 Windows Credential Manager 存 key 就万事大吉了。结果 CI 的 Linux runner 上 keyring 能 import 但没后端，直接抛 NoKeyringError 炸掉了四个测试。修了 except ImportError 改成 except Exception 才解决。这件事让我意识到降级路径比主方案更重要，主方案每个人都有，降级路径才是工程差别。

Docker 里的安全边界也类似。容器内 keyring 不可用，只能走环境变量或 .env。我在 README 里写了威胁模型表，但没有做 pre-commit hook 扫描 key 泄露，这是下一步该做的事。

分发方面，Docker 构建本身很简单（十几行的 Dockerfile），但别人怎么拿到我的项目跑起来这个问题逼我做了好几件额外的事：写 README 的安装章节、加 .env.example 文件、确保 pip install -e .[dev] 在全新环境能跑通。这些东西跟 harness 内核没关系，但对于一个完整的软件项目是不可或缺的。

---

## 七、如果重做，我会改什么

先写 demo，再写单元测试。我做反了，先写了一堆原子测试（ActionParser、ToolRegistry、GuardrailChain），最后才写 demo。但如果先写三个完整 demo 脚本，它们天然就定义好了各模块的接口和交互方式。单元测试应该追着 demo 的边界补全。

减少 task 数量，增大每个 task 的深度。二十个 task 太多了。把能合并的合并（OpenAI 适配器加凭据管理，Docker 加 CI），每个 task 的 brief 写得更详细，让 subagent 在一个 task 上花更多时间。

SPEC 里面的领域与机制设计应该一上来就画数据流加代码对应表。最有价值的部分是机制对照表和系统架构图，功能列表反而次之。AI 读表格比读自然语言描述准确得多，我应该把更多 spec 内容表化。

WebUI 不要做。从项目定位（CLI harness）和作业真实评分权重来看，FastAPI 加 HTML 的 WebUI 占了六个测试和几百行代码，但对展现 harness 工程深度的贡献几乎为零。不如把这些精力用来把机制演示做得更深。

---

## 八、对 Superpowers 方法论的看法

Superpowers 是一个纪律工具，用流程限制了你和 AI 双向偷懒的空间。你不能跳过测试、不能跳过 review、不能让 agent 在 main 上乱改。这种约束在多人协作加 AI 辅助的场景下价值巨大，但在单人加快速迭代的场景下，有时会觉得它在用流程完整性换效率。

Superpowers 有几个预设在我的项目里不完全成立。第一个预设是工程师知道要做什么，brainstorming 能把模糊变清晰，但不会把错误变正确。第二个预设是 task 可以预先规划，gap fix 阶段的六个 task 全部是做完主干之后发现的，计划阶段不可能预见 REPL 缺少 !step 命令或 keyring 在 CI 会炸。第三个预设是 subagent 可以独立完成 task，但对于需要理解上下文的任务，真正的瓶颈在 brief 撰写者的知识储备，不是 subagent 的执行力。

我用下来最大的收获是终于知道哪些流程值得坚持、哪些可以按场景裁剪，Superpowers 好不好用反而是次要的。这可能才是这门课想让学生自己悟到的答案。
