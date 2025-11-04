# core/simulator_engine.py (已修复“智能spawn”)

from __future__ import annotations
import heapq
import collections
from typing import Callable, Any, List, Dict, Generator, Optional

# 从同一个目录导入 Event
from .event import Event

# ==============================================================================
# “指令”类：HwModule 和 Testbench 将 yield 这些对象
# ==============================================================================
class Delay:
    """一个“指令”对象，当协程 'yield' 它时，调度器会明白要暂停"""
    def __init__(self, cycles: int, priority: int = 10):
        if cycles < 0:
            raise ValueError("延迟不能为负数")
        self.cycles = cycles
        self.priority = priority

# ==============================================================================
# “任务”包装器：Simulator 内部管理的核心对象
# ==============================================================================
class Task:
    """
    包装一个协程（生成器），并管理它的“调用栈”和“返回值”。
    """
    _next_task_id = 0
    
    def __init__(self, sim: Simulator, coroutine: Generator, 
                 parent: Optional[Task] = None):
        self.sim = sim
        self.coro = coroutine  # 被包装的协程
        self.parent = parent   # 哪个任务在“串行”等待我
        self.waiting_tasks = [] # 哪些任务在“并行”等待我
        self.result: Any = None
        self.is_done: bool = False
        
        self.task_id = Task._next_task_id
        Task._next_task_id += 1

    def run(self, value_to_send: Any = None):
        """
        “唤醒”或“恢复”这个任务
        """
        try:
            yielded_command = self.coro.send(value_to_send)
            self.sim._handle_yield(self, yielded_command)
            
        except StopIteration as e:
            self.is_done = True
            self.result = e.value
            
            if self.parent:
                self.sim._schedule_task_now(self.parent, with_value=self.result)
            
            for task in self.waiting_tasks:
                task.check_join_barrier(child_task=self)
                
        except Exception as e:
            print(f"错误: 任务 {getattr(self.coro, '__name__', 'coro')} 发生异常: {e}")

# ==============================================================================
# “屏障”：用于 'yield [list]' 的内部帮助器
# ==============================================================================
class JoinBarrier(Task):
    """
    一个特殊的“屏障”任务，用于实现 'yield [list]'。
    """
    def __init__(self, sim: Simulator, tasks_to_join: List[Task], parent: Optional[Task]):
        def _join_coro():
            if False: yield # 只是为了让它成为一个生成器
        
        super().__init__(sim, _join_coro(), parent)
        self.tasks_to_join = tasks_to_join
        self.results = [None] * len(tasks_to_join)
        self.count_down = len(tasks_to_join)

        if self.count_down == 0:
            self.run() 
        else:
            for i, task in enumerate(self.tasks_to_join):
                setattr(task, '_join_barrier_index', i)
                task.waiting_tasks.append(self)

    def check_join_barrier(self, child_task: Task):
        self.count_down -= 1
        index = getattr(child_task, '_join_barrier_index')
        self.results[index] = child_task.result
        
        if self.count_down == 0:
            self.is_done = True
            self.result = self.results
            if self.parent:
                self.sim._schedule_task_now(self.parent, with_value=self.result)

# ==============================================================================
# 模拟器引擎 (协程调度器)
# ==============================================================================
class Simulator:
    """
    一个基于【协程】的离散事件模拟器（调度器）。
    """
    def __init__(self):
        self.event_heap: List[Event] = []
        self.current_time: int | float = 0
        self.ready_queue: collections.deque = collections.deque()
        self._current_task: Optional[Task] = None

    # --- 公共API (供 HwModule 和 Testbench 使用) ---
    
    # ⬇⬇⬇ 【修正：spawn 现在“更智能”】 ⬇⬇⬇
    def spawn(self, coroutine_or_func: Any, *args: Any, **kwargs: Any) -> Task:
        """
        【已修正】: 启动一个新任务。
        
        可以接受两种调用方式：
        1. spawn(func, arg1, kwarg='a') -> (来自 main.py)
        2. spawn(generator_object)       -> (来自 ALU.execute)
        """
        
        coro_to_run: Generator
        
        if isinstance(coroutine_or_func, Generator):
            # --- 情况2: 传入的是一个【已创建】的生成器对象 ---
            if args or kwargs:
                raise ValueError("当 spawn() 接收一个生成器对象时，不能再传递 *args 或 **kwargs")
            coro_to_run = coroutine_or_func
            
        elif callable(coroutine_or_func):
            # --- 情况1: 传入的是一个【函数】和它的参数 ---
            try:
                coro_to_run = coroutine_or_func(*args, **kwargs)
            except Exception as e:
                print(f"错误: 在 'spawn' 期间调用 {coroutine_or_func.__name__} 失败: {e}")
                raise
        else:
            raise TypeError(f"spawn() 必须接收一个可调用对象 (callable) 或一个生成器 (generator)，"
                            f"但收到了 {type(coroutine_or_func)}")

        if not isinstance(coro_to_run, Generator):
            raise TypeError(f"spawn() 调用的 {getattr(coroutine_or_func, '__name__', 'coro')} "
                            f"没有返回一个生成器 (generator)。您是否忘记了 'yield'?")
            
        # 包装并调度任务
        new_task = Task(self, coro_to_run, parent=None)
        self._schedule_task_now(new_task)
        return new_task # 返回“任务句柄”
    # ⬆⬆⬆ 【修正结束】 ⬆⬆⬆


    def delay(self, cycles: int, priority: int = 10) -> Delay:
        """【新】“原子等待”指令"""
        return Delay(cycles, priority)

    # --- 调度器核心逻辑 (保持不变) ---
    
    def _schedule_task_now(self, task: Task, with_value: Any = None):
        self.ready_queue.append((task, with_value))

    def _schedule_task_future(self, task: Task, delay_cycles: int, priority: int):
        timestamp = self.current_time + delay_cycles
        event = Event(timestamp, priority, task)
        heapq.heappush(self.event_heap, event)

    def _handle_yield(self, task: Task, yielded_value: Any):
        """【关键】: 解释一个协程 'yield' 出来的“指令”"""
        
        if isinstance(yielded_value, Delay):
            # 指令1: "yield self.sim.delay(15)"
            self._schedule_task_future(task, yielded_value.cycles, yielded_value.priority)
        
        elif isinstance(yielded_value, Generator):
            # 指令2: "data = yield self.fifo0.pop()"
            sub_task = Task(self, yielded_value, parent=task)
            self._schedule_task_now(sub_task)
            
        elif isinstance(yielded_value, Task):
            # 指令3: "data = yield handle_a"
            child_task = yielded_value
            if child_task.is_done:
                self._schedule_task_now(task, with_value=child_task.result)
            else:
                child_task.parent = task
                
        elif isinstance(yielded_value, list):
            # 指令4: "results = yield [handle_a, handle_b]"
            join_barrier = JoinBarrier(self, yielded_value, parent=task)
            
        elif yielded_value is None:
            # 指令5: "yield"
            self._schedule_task_now(task)
            
        else:
            raise TypeError(f"未知的 yield 类型: {type(yielded_value)} (来自 {task.coro.__name__})")

    # --- 主循环 (保持不变) ---
    
    def run(self, until: int | float = float('inf')):
        print(f"--- 协程仿真在 t={self.current_time} 开始 ---")
        
        while True:
            # 1. 内部Δ-Cycle循环
            while self.ready_queue:
                task, value_to_send = self.ready_queue.popleft()
                self._current_task = task
                task.run(value_to_send)
            
            # 2. 检查是否结束
            if not self.event_heap:
                print(f"--- 仿真在 t={self.current_time} 结束 (无更多事件) ---")
                break
                
            # 3. 检查 'until' 
            if self.event_heap[0].timestamp > until:
                print(f"--- 仿真在 t={self.current_time} 暂停 (已达到 until={until}) ---")
                break
                
            # 4. 弹出【一个】事件，推进时间
            event_to_run = heapq.heappop(self.event_heap)
            self.current_time = event_to_run.timestamp
            self._schedule_task_now(event_to_run.task)
            
            # 5. 唤醒所有在【同一时刻】发生的其他事件
            while self.event_heap and self.event_heap[0].timestamp == self.current_time:
                event = heapq.heappop(self.event_heap)
                self._schedule_task_now(event.task)