# ToySim: 一个基于协程的Python硬件架构模拟器

`ToySim` 是一个轻量级的、纯Python的离散事件模拟框架。它专为硬件架构的性能探索和功能验证而设计。正如其名，这是一个"玩具"级别的实现，适合学习和实验。

本框架的核心设计是**基于协程 (`yield`)**，而不是传统的回调（callback）。这使得测试平台（Testbench）的编写极其直观、灵活，并能以“顺序”的代码风格轻松实现**复杂的并发**和**异步**硬件行为，彻底告别了“回调地狱”。

## 核心架构：三个“世界”

我们的模拟器将系统清晰地划分为三个独立的部分：

### 1. `Simulator` (物理引擎)

* **文件**: `core/simulator.py`
* **角色**: 这是“宇宙的法则”。它是一个**协程调度器**，负责管理**时间和事件**。
* **原理**: 它维护一个**时间堆**（`event_heap`）来管理未来的“唤醒”事件，以及一个**就绪队列**（`ready_queue`）来处理当前时刻（Δ-cycle）的所有并发任务。它对“硬件”或“软件”一无所知，只负责“暂停”和“恢复”任务。

### 2. `HwModule` (硬件世界)

* **文件**: `core/hw_module.py`, `test/SinglePortRAM.py`, `test/Fifo.py`, `test/SimpleALU.py`
* **角色**: 这是被模拟的**“设备” (Device)**。
* **原理**:
    * 所有硬件模块都继承自`HwModule`基类。
    * 硬件模块**是“容器”**，它们可以由其他子模块组成（例如`SimpleALU`包含`Fifo`，`Fifo`包含`SinglePortRAM`）。
    * 它们的方法是**异步协程**（`generator`）。
    * 它们通过 `yield self.sim.delay(N)` 来**模拟延迟**。
    * 它们通过 `yield self.child.method()` 来**串行等待**子任务。
    * 它们通过 `yield [task_a, task_b]` 来**并行等待**多个子任务。

### 3. `Testbench` (软件世界)

* **文件**: `test/main.py`
* **角色**: 这是**“主机软件” (Host Software)**，负责驱动硬件。
* **原理**:
    * 它是一个**纯粹的Python类**（不继承`HwModule`）。
    * 它在`__init__`中获取`Simulator`和它想测试的硬件（“待测设备”或DUT）的引用。
    * 它提供一个（或多个）“启动”协程（例如`run_test`）。
    * 它使用与`HwModule`相同的`yield`原语，来编排复杂的、并发的测试序列。

## 项目结构

```text
toy/
├── core/                  # 1. 模拟器核心引擎
│   ├── __init__.py        # (使 'core' 成为一个Python包)
│   ├── event.py           # (内部) 定义调度器使用的 Event 对象
│   ├── simulator.py       # 【关键】: Simulator 协程调度器
│   └── hw_module.py       # 【关键】: HwModule (硬件) 基类
│
└── test/                  # 2. 硬件模块与测试脚本
    ├── SinglePortRAM.py   # HwModule: 单端口RAM（协程版）
    ├── Fifo.py            # HwModule: FIFO（协程版，内部使用RAM）
    ├── SimpleALU.py       # HwModule: ALU（协程版，内部使用FIFO）
    └── main.py            # 【关键】: 纯Python的Testbench和仿真主程序

## 示例硬件架构
`test/`文件夹中的文件共同构建了一个3层结构的、用于演示的硬件系统：
1.  **`SimpleALU` (顶层硬件)**:
    * 这是一个ALU（算术逻辑单元）的“容器”模块。它本身不存储数据。
    * 它在内部创建并拥有**两个**`Fifo`子模块（`fifo0`和`fifo1`），分别用于两个操作数。
    * 它向外界（如`Testbench`）提供了三个主要的协程服务：`load_a()`、`load_b()`和`execute()`。
    * `load_a`和`load_b`是**并行**的（使用独立锁），允许同时向两个FIFO加载数据。
    * `execute`被设计为**并行**地从`fifo0`和`fifo1`弹出数据。

2.  **`Fifo` (中间层)**:
    * 这是一个自包含的FIFO（先进先出队列）控制器。
    * 它的职责是管理内部的读/写指针和填充状态（`current_fill_level`）。
    * 每个`Fifo`实例在内部创建并**拥有一个**专用的`SinglePortRAM`子模块，用作其后端存储。
    * 它将`push()`和`pop()`请求转换为对其内部`RAM`的`write()`和`read()`调用。

3.  **`SinglePortRAM` (最底层)**:
    * 这是一个“字可寻址”的内存核心的性能模型。
    * 它是系统的“叶子”模块，不包含任何子模块。
    * 它的`read()`和`write()`协程通过`yield self.sim.delay(...)`来模拟真实的核心访问延迟（固定开销 + 突发传输时间）。
    * 默认情况下，它也支持**真实的数据存储**（“功能模式”），以验证计算结果的正确性。