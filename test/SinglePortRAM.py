# single_port_ram.py (协程版, 支持真实数据)

from __future__ import annotations
from typing import List, Any, Optional, Generator

# core 使用绝对导入
from core.hw_module import HwModule
from core.simulator import Simulator, Delay # <-- 导入 Delay 指令

class SinglePortRAM(HwModule):
    """
    [新架构]: 一个“双模式”的RAM (协程版)。
    
    它既支持“性能模式”(不存数据)，也支持“功能模式”(存储真实数据)。
    它的公共方法 (read, write) 是协程。
    """
    def __init__(self, name: str, sim: Simulator, 
                 size_in_words: int,
                 core_bit_width: int,
                 core_access_latency: int = 1,
                 data_simulation_enabled: bool = True, # <-- 支持真实数据
                 parent: Optional[HwModule] = None):
        
        super().__init__(name, sim, parent)
        
        self.size_in_words = size_in_words
        self.core_bit_width = core_bit_width
        self.core_access_latency = core_access_latency
        self.data_simulation_enabled = data_simulation_enabled
        
        # 根据模式，决定是否分配内存
        if self.data_simulation_enabled:
            # 我们使用 list 来存储 'Any' 类型的“字”
            self.memory: Optional[List[Any]] = [None] * self.size_in_words
        else:
            self.memory = None # 纯性能模式

        # 统计指标
        self._register_stat("reads_performed (words)", 0)
        self._register_stat("writes_performed (words)", 0)
        self._register_stat("core_cycles_busy", 0)

    def _calculate_core_delay(self, num_words: int) -> int:
        """计算核心的总延迟。"""
        # (我们使用您在 user-165 中确认的逻辑: 固定开销 + 访问周期数)
        if num_words <= 0:
            return 0
        
        # 您的代码中是 return self.core_access_latency + num_words
        # 这是一个完全合理的模型，我们坚持使用它。
        return self.core_access_latency + num_words

    def read(self, word_address: int, num_words: int) -> Generator[Any, Any, List[Any]]:
        """
        [协程] 请求读取【N个字】的数据。
        [修正]: 不再接收 'bus_callback'。
        """
        
        # 1. 检查状态
        if self.busy:
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"收到 read 请求，但正忙！")
            return [] # 协程通过 'return' 结束并返回值
            
        if word_address < 0 or word_address + num_words > self.size_in_words:
            print(f"错误: [{self.full_name}] 读取地址越界！")
            return []
            
        self._set_busy()
        
        # 2. 计算延迟
        total_core_delay = self._calculate_core_delay(num_words)
        
        # 3. 更新统计
        self._increment_stat("reads_performed (words)", num_words)
        self._increment_stat("core_cycles_busy", total_core_delay)

        # 4. [修正]: 根据模式，决定是返回真实数据还是虚拟数据
        read_data: List[Any]
        if self.data_simulation_enabled and self.memory is not None:
            read_data = self.memory[word_address : word_address + num_words]
        else:
            read_data = [0] * num_words # 纯性能模式

        # 5. [核心改动]: 'yield' 一个 'Delay' 指令
        if total_core_delay > 0:
            yield self.sim.delay(total_core_delay)

        # 6. [唤醒点]: 延迟结束后，代码从这里继续
        self._set_idle()
        
        # 7. “异步返回”真实数据或虚拟数据
        return read_data

    def write(self, word_address: int, data: List[Any]) -> Generator[Any, Any, None]:
        """
        [协程] 请求写入【N个字】的数据。
        [修正]: 不再接收 'bus_callback'。
        """
        num_words = len(data)
        
        # 1. 检查状态
        if self.busy:
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"收到 write 请求，但正忙！")
            return
            
        if word_address < 0 or word_address + num_words > self.size_in_words:
            print(f"错误: [{self.full_name}] 写入地址越界！")
            return

        self._set_busy()

        # 2. 计算延迟
        total_core_delay = self._calculate_core_delay(num_words)

        # 3. 更新统计
        self._increment_stat("writes_performed (words)", num_words)
        self._increment_stat("core_cycles_busy", total_core_delay)
            
        # 4. [修正]: 在调度延迟之前，【实际写入】数据
        if self.data_simulation_enabled and self.memory is not None:
            self.memory[word_address : word_address + num_words] = data
            
        # 5. [核心改动]: 'yield' 一个 'Delay' 指令
        if total_core_delay > 0:
            yield self.sim.delay(total_core_delay)
            
        # 6. [唤醒点]: 延迟结束后，代码从这里继续
        self._set_idle()
        
        # Write 操作没有返回值，所以我们只 'return'
        return