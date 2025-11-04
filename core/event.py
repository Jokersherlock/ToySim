# core/event.py

from __future__ import annotations
import functools
from typing import Any

# 我们需要一个 Task 类的“前向声明”
# 真正的 Task 类将在 simulator_engine.py 中定义
class Task:
    pass

@functools.total_ordering
class Event:
    """
    一个【内部】事件，用于驱动协程调度器。

    它在功能上与旧版类似，但它不再存储用户定义的回调，
    而是存储一个【需要被唤醒的任务】(Task 实例)。
    """
    def __init__(self, timestamp: int | float, priority: int, task: Task):
        """
        参数:
            timestamp (int | float): 事件（唤醒）发生的时间。
            priority (int): 优先级，用于处理同一时刻的事件。
            task (Task): 被暂停的、等待唤醒的协程任务。
        """
        self.timestamp = timestamp
        self.priority = priority
        self.task = task

    def __lt__(self, other: Event) -> bool:
        """为最小堆提供排序功能。"""
        if not isinstance(other, Event):
            return NotImplemented
        # 先按时间戳排序，再按优先级（值越小，优先级越高）
        return (self.timestamp, self.priority) < (other.timestamp, other.priority)

    def __eq__(self, other: Event) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return (self.timestamp, self.priority) == (other.timestamp, other.priority)

    def __repr__(self) -> str:
        # 假设 Task 有一个 'name' 属性
        task_name = getattr(self.task.coro, '__name__', 'coro')
        return f"Event(t={self.timestamp}, prio={self.priority}, task={task_name})"