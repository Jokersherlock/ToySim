# simple_alu.py

from __future__ import annotations
from typing import Optional, Any, List, Generator

# core 使用绝对导入
from core.hw_module import HwModule
from core.simulator import Simulator, Delay, Task

# 直接导入同目录下的[协程版]Fifo
# (假设文件名为 fifo.py, 类名为 Fifo)
from Fifo import Fifo 

class SimpleALU(HwModule):
    """
    [新架构]: 一个 SimpleALU 硬件模块 (协程版)。
    
    它封装了两个FIFO，并提供了三个[协程]服务：
    load_a, load_b, execute。
    
    'execute' 服务会[并行]地从两个FIFO中弹出数据。
    
    [已修正]: 此版本已更新，可将 'data_simulation_enabled' 标志
    传递给其子FIFO，以支持真实数据仿真。
    """
    
    def __init__(self, name:str, sim:Simulator, 
                 # 将FIFO的规格作为参数传入
                 fifo_capacity: int = 1024,
                 fifo_bit_width: int = 32,
                 fifo_latency: int = 1,
                 compute_latency: int = 1, # ALU自身的计算延迟
                 data_simulation_enabled: bool = True, # <-- [修正]: 添加此参数
                 parent:Optional[HwModule]=None):
        
        super().__init__(name, sim, parent)
      
        self.compute_latency = compute_latency
        
        # 创建[协程版]的FIFO子模块
        self.fifo0 = Fifo(name="fifo0", sim=sim, 
                          capacity_in_words=fifo_capacity, 
                          core_bit_width=fifo_bit_width, 
                          core_access_latency=fifo_latency, 
                          data_simulation_enabled=data_simulation_enabled, # <-- [修正]: 传递参数
                          parent=self)
        self.fifo1 = Fifo(name="fifo1", sim=sim, 
                          capacity_in_words=fifo_capacity, 
                          core_bit_width=fifo_bit_width, 
                          core_access_latency=fifo_latency, 
                          data_simulation_enabled=data_simulation_enabled, # <-- [修正]: 传递参数
                          parent=self)

        # --- 独立的锁 ---
        self.busy_a: bool = False
        self.busy_b: bool = False
        self.busy_exec: bool = False
        
        # --- [已删除]: 所有 pending_..._callback 变量
        
        # --- 注册统计指标 ---
        self._register_stat("load_a_performed", 0)
        self._register_stat("load_b_performed", 0)
        self._register_stat("execute_performed", 0)
        self._register_stat("ops_failed_fifo_empty", 0)
        self._register_stat("ops_failed_fifo_busy", 0)


    # --- Load A (协程) ---
    def load_a(self, a:Any) -> Generator[Any, Any, None]:
        """
        [协程] 将一个字推入FIFO A。
        会 'yield' 直到FIFO的push操作完成。
        """
        if self.busy_a:
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"load_a 失败 (ALU正忙)")
            self._increment_stat("ops_failed_fifo_busy")
            return
            
        if self.fifo0.current_fill_level == self.fifo0.capacity:
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"load_a 失败 (FIFO0已满)")
            return

        self._set_busy_a()
        
        # [核心改动]: 'yield' 子任务
        yield self.fifo0.push(a) 
        
        # [唤醒点]: push 完成
        self._set_idle_a()
        self._increment_stat("load_a_performed")

    # --- Load B (协程) ---
    def load_b(self, b:Any) -> Generator[Any, Any, None]:
        """
        [协程] 将一个字推入FIFO B。
        """
        if self.busy_b:
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"load_b 失败 (ALU正忙)")
            self._increment_stat("ops_failed_fifo_busy")
            return
            
        if self.fifo1.current_fill_level == self.fifo1.capacity:
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"load_b 失败 (FIFO1已满)")
            return

        self._set_busy_b()
        
        # [核心改动]: 'yield' 子任务
        yield self.fifo1.push(b)
        
        # [唤醒点]: push 完成
        self._set_idle_b()
        self._increment_stat("load_b_performed")

    # --- Execute (协程，并行Pop) ---
    def execute(self, op: str) -> Generator[Any, Any, Any]:
        """
        [协程] 执行计算。
        1. [并行] Pop A 和 Pop B
        2. [等待] 计算延迟
        3. [返回] 结果
        """
        if self.busy_exec:
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"execute 失败 (ALU正忙)")
            return None # 异步返回 None 表示失败
        
        # 检查FIFO是否为空
        if self.fifo0.current_fill_level == 0 or self.fifo1.current_fill_level == 0:
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"execute 失败 (FIFO为空)")
            self._increment_stat("ops_failed_fifo_empty")
            return None

        self._set_busy_exec()
        
        print(f"[{self.sim.current_time: >4}] [{self.full_name}] (Coro) [并行] 启动 Pop A 和 Pop B...")

        # 1. [并行启动]: 'spawn' 启动任务，但不等待
        pop_a_task: Task = self.sim.spawn(self.fifo0.pop())
        pop_b_task: Task = self.sim.spawn(self.fifo1.pop())

        # 2. [并行等待]: 'yield [list]' 是一个“屏障”指令
        results = yield [pop_a_task, pop_b_task]
        
        # 3. [汇合点]: 两个Pop都已完成
        data_a, data_b = results
        print(f"[{self.sim.current_time: >4}] [{self.full_name}] (Coro) [汇合] A={data_a}, B={data_b}。")
        
        # 4. [模拟计算延迟]
        if self.compute_latency > 0:
            yield self.sim.delay(self.compute_latency)
        
        # 5. [唤醒点]: 计算完成
        
        result: Any
        if op == 'add':
            # 【关键】: 确保 data_a 和 data_b 不是 None
            if data_a is not None and data_b is not None:
                result = data_a + data_b
            else:
                result = None # 如果pop失败，结果也是None
        elif op == 'sub':
            if data_a is not None and data_b is not None:
                result = data_a - data_b
            else:
                result = None
        else:
            result = None
            
        print(f"[{self.sim.current_time: >4}] [{self.full_name}] (Coro) 计算完成，结果: {result}。")

        # 6. [清理并返回]
        self._set_idle_exec()
        self._increment_stat("execute_performed")
        
        return result # 'return' 是协程的“异步返回值”

    # --- 辅助方法 (保持不变) ---
    def _set_busy_a(self): self.busy_a = True
    def _set_idle_a(self): self.busy_a = False
    def _set_busy_b(self): self.busy_b = True
    def _set_idle_b(self): self.busy_b = False
    def _set_busy_exec(self): self.busy_exec = True
    def _set_idle_exec(self): self.busy_exec = False