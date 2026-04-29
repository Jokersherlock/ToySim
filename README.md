# ToySim

ToySim 是一个轻量级 Python 离散事件硬件架构模拟器。它的目标不是替代 Verilog/SystemVerilog 这类 RTL 仿真器，而是用于更高层次的架构探索：模块延迟、并发任务、流水线吞吐、缓冲区容量、资源等待、反压传播和事务级数据流。

当前的核心思想是：用 Python 协程写出接近“顺序程序”的硬件行为描述，再由 `Simulator` 负责暂停、恢复、延迟和唤醒。这样可以避免大量手写回调，也避免把所有模块都写成逐周期 `tick()`。

## 当前能力

ToySim 目前支持这些基本建模动作：

- `yield sim.delay(cycles)`：让当前任务暂停若干仿真周期。
- `sim.spawn(...)`：启动一个并发任务。
- `yield child_coroutine()`：串行等待一个子协程完成并取得返回值。
- `yield task`：等待一个已经启动的任务完成。
- `yield [task_a, task_b, ...]`：等待多个并发任务全部完成。
- `Signal.wait()`：等待一个事件信号。
- `Signal.notify_one()` / `Signal.notify_all()`：唤醒等待该信号的任务。
- `HwModule`：组织硬件模块层次、完整路径名和统计信息。

适合用 ToySim 表达的内容：

- 一个模块处理请求需要若干周期；
- 一个流水线级每隔若干周期能接受一个新 token；
- 一个通道容量不足会导致上游等待；
- 多个子任务并发执行，之后汇合；
- 模块之间通过信号等待事件发生；
- 对不同架构模式的吞吐、延迟和缓冲需求进行比较。

不建议用 ToySim 表达的内容：

- 每个寄存器每周期更新；
- 每个组合逻辑信号的精确传播；
- 每个 stage 每周期醒来检查 `valid/ready`；
- RTL 级时序精确验证。

## 目录结构

```text
PQC_DSS/
├── core/
│   ├── __init__.py
│   ├── event.py          # 调度器内部使用的事件对象
│   ├── hw_module.py      # 硬件模块基类，负责层次结构和统计
│   └── simulator.py      # 协程调度器、Delay、Task、Signal
│
├── examples/
│   ├── __init__.py
│   └── pipeline_demo.py  # 事件级三段流水线示例
│
├── test/                 # 当前留空，旧示例已删除
├── simulate_demo.py      # 根目录仿真入口
├── .gitignore
└── README.md
```

## 快速运行

默认运行 `fast` 模式：

```powershell
python simulate_demo.py
```

指定模式：

```powershell
python simulate_demo.py --mode fast
python simulate_demo.py --mode compact
```

调整测试流量：

```powershell
python simulate_demo.py --mode compact --first-wave 10 --second-wave 4 --gap 5
```

参数含义：

- `--mode`：选择流水线时序模式，可选 `fast` 或 `compact`。
- `--first-wave`：第一波突发提交的 token 数量，默认 8。
- `--second-wave`：第二波突发提交的 token 数量，默认 3。
- `--gap`：两波流量之间等待的仿真周期数，默认 3。

如果你的系统里 `python` 不在 `PATH`，请换成实际可用的 Python 可执行文件。

## 核心模块说明

### Simulator

`Simulator` 是整个系统的调度器。它维护两个关键结构：

- `ready_queue`：当前仿真时间可以立即运行的任务队列。
- `event_heap`：未来某个时间点需要被唤醒的任务堆。

协程运行时会 `yield` 出不同类型的对象，调度器根据对象类型决定下一步：

- `Delay`：把任务放到未来时间；
- 子协程：启动子任务并让父任务等待；
- `Task`：等待已有任务；
- `list[Task]`：等待一组任务全部完成；
- `WaitSignal`：等待信号通知；
- `None`：当前时间重新排队。

### HwModule

`HwModule` 是所有硬件模块的基类。它提供：

- `name`：局部模块名；
- `full_name`：带父模块路径的完整名；
- `parent` / `_children`：模块层次；
- `busy`：适合简单独占资源的忙闲标记；
- `stats`：统计项字典；
- `report_stats()`：递归打印模块和子模块统计。

`HwModule` 故意保持简单。更具体的结构，例如通道、流水线级、存储器、仲裁器、功能单元，都可以在它之上扩展。

## 示例模拟的硬件架构

当前示例位于 `examples/pipeline_demo.py`，入口是 `simulate_demo.py`。它模拟的是一个名为 `ToyPipelineAccelerator` 的小型三段流水线加速器。

这个示例不是一个真实的 PQC 算法实现。它更像一个架构骨架，用来展示如何在当前模拟器里表达流水线、通道、反压、token 追踪和模式切换。

整体结构如下：

```text
测试平台 DemoTestbench
        │
        ▼
ToyPipelineAccelerator
        │
        ▼
输入通道 input
        │
        ▼
Load 阶段
        │
        ▼
中间通道 load_to_compute
        │
        ▼
Compute 阶段
        │
        ▼
中间通道 compute_to_store
        │
        ▼
Store 阶段
        │
        ▼
token 完成信号
```

### Token

测试平台提交的是 `Token`。每个 token 表示一笔流经加速器的事务，包含：

- `token_id`：事务编号；
- `payload`：示例数据；
- `mode`：当前加速器模式；
- `done`：完成时用于唤醒提交方的信号；
- `trace`：记录 token 经过每个模块的时间点。

为了让结果容易检查，三段流水线对 `payload` 做了简单变换：

```text
Load:    payload += 10
Compute: payload *= 2
Store:   payload -= 3
```

所以输入 `1` 的最终结果是：

```text
(1 + 10) * 2 - 3 = 19
```

主程序会为每个 token 打印实际结果和期望结果，如果不一致会退出失败。

### Channel

`Channel` 是 stage 之间的有界事件通道。它不是精确的硬件 SRAM/FIFO 宏模型，而是用于架构级流控：

- 内部有一个队列；
- 有固定容量；
- 队列空时，消费者等待 `not_empty`；
- 队列满时，生产者等待 `not_full`；
- 统计 `puts`、`gets`、阻塞次数和最大占用。

这让示例可以表达 backpressure，而不用每周期轮询。

### PipelineStage

`PipelineStage` 表示一个流水线级。每一级有：

- `latency`：token 从进入该级到完成该级需要的周期数；
- `initiation_interval`：该级两次接受 token 之间的最小间隔；
- `max_inflight`：该级允许同时在途的 token 数；
- 输入通道；
- 输出通道；
- 数据变换函数。

关键设计点是：stage 的主循环不会因为一个 token 的完整 `latency` 被阻塞。它接受 token 后，会派生一个“完成任务”：

```text
在 t 时刻接受 token
派生 completion task
completion task 在 t + latency 时刻完成
stage 自身按 initiation_interval 决定何时接受下一个 token
```

这和下面这种写法不同：

```text
接受 token
yield delay(latency)
完成 token
再接受下一个 token
```

后者模拟的是阻塞式多周期单元，不是流水线级。当前示例特意采用 completion task，是为了展示“事件级流水线”而不是逐周期仿真。

## 两种时序模式

`ToyPipelineAccelerator` 支持两个模式。

`fast` 模式：

```text
Load:    latency=2, initiation_interval=1
Compute: latency=4, initiation_interval=1
Store:   latency=2, initiation_interval=1
```

`compact` 模式：

```text
Load:    latency=2, initiation_interval=2
Compute: latency=6, initiation_interval=3
Store:   latency=2, initiation_interval=1
```

直观理解：

- `fast` 更像资源较多、流水化更充分的实现；
- `compact` 更像资源更少、面积更省、吞吐更低的实现。

外部测试平台仍然把加速器当作黑盒，只调用 `dut.submit(...)` 并等待返回。加速器内部则拆成 channel 和 stage，因此可以观察每一级的接受时间、完成时间、在途 token 数、通道占用和阻塞情况。

## DemoTestbench 做了什么

当前测试平台比最早的冒烟示例更完整一些。默认行为是：

1. 启动三段流水线的长期 worker。
2. 第一波一次性并发提交 8 个 token。
3. 用 `yield [task0, task1, ...]` 等待第一波全部完成。
4. 等待 `gap` 个周期。
5. 第二波并发提交 3 个 token。
6. 再次 join 第二波。
7. 主程序逐个校验 token 的实际输出。
8. 打印每个 token 的 trace。
9. 递归打印模块统计。

第一波 token 数量默认大于输入通道容量，因此比旧版本更容易暴露通道排队、反压和 stage 重叠行为。

输出中的 trace 类似：

```text
token=0, input=1, payload=19, expected=19, PASS,
trace=toy_pqc_pipeline:submit@0 -> toy_pqc_pipeline.load:accept@0 -> ...
```

你可以从 trace 里看到不同 token 不是串行穿过整个加速器，而是在不同 stage 中重叠推进。

## 建模建议

如果要继续扩展这个项目，建议保持事件级建模风格。

推荐写法：

```text
stage 接受 token
stage 安排该 token 的完成事件
stage 按 II 接受后续 token
完成事件把 token 推入下一级 channel
```

不推荐写法：

```text
stage 接受 token
stage 主循环 yield delay(latency)
stage 完成 token
stage 才能接受下一个 token
```

除非你明确想模拟的是“不可重入的阻塞式功能单元”，否则第二种写法会低估流水线吞吐。

## 当前限制

当前 core 还比较小，主要限制包括：

- 任务异常目前主要是打印，没有强异常传播；
- 没有 first-class 的取消、flush、kill 机制；
- `Signal` 只是简单通知器，不是带谓词的条件变量；
- 还没有标准资源仲裁器；
- 还没有正式单元测试体系；
- `test/` 目前留空，旧示例已移除。

后续如果要继续演进，比较自然的方向是：标准化 `Channel`、引入 `Resource`/`Arbiter`、增强异常传播、增加 pipeline flush/cancel、补充 pytest 回归测试。

