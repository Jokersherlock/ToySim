"""
离散事件模拟器 (Discrete-Event Simulation) 包

这个包提供了一个基于事件驱动的硬件架构模拟器框架。
主要组件包括：
- Event: 事件类，封装仿真中的未来行为
- Simulator: 核心模拟器引擎，管理事件调度和执行（协程版）
- HwModule: 硬件模块基类，所有硬件组件的基础
- Delay: 延迟指令类，用于协程中暂停执行
- Task: 任务包装器类，用于管理协程任务

使用示例（协程版）：
    from core import Simulator, HwModule, Delay, Task
    
    # 创建模拟器
    sim = Simulator()
    
    # 创建硬件模块
    module = MyHwModule("my_module", sim)
    
    # 在协程中使用
    def my_coroutine():
        yield sim.delay(10)  # 延迟10个周期
        yield module.some_operation()
    
    # 启动协程任务
    sim.spawn(my_coroutine())
    
    # 运行仿真
    sim.run()
"""

from .event import Event
from .simulator import Simulator, Delay, Task
from .hw_module import HwModule

__version__ = "1.0.0"
__author__ = "PQC_DSS Project"

__all__ = ["Event", "Simulator", "HwModule", "Delay", "Task"]
