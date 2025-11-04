# fifo.py

from __future__ import annotations
from typing import Optional, Any, List, Generator

# 导入我们的核心组件
# 'core' 文件夹使用绝对导入
from core.hw_module import HwModule
from core.simulator import Simulator, Delay

# 【关键】: 我们现在必须导入【新版】(协程版)的 SinglePortRAM
# (假设文件名为 'single_port_ram.py')
from SinglePortRAM import SinglePortRAM 

class Fifo(HwModule):
    """
    [新架构]: 一个自包含的FIFO模块 (协程版)。
    
    这个模块在内部创建并管理一个专用的SinglePortRAM实例。
    它的 public 方法 (push, pop) 是协程 (generators)，
    它们 "yield" 子任务，而不是使用回调。
    """
    def __init__(self, name: str, sim: Simulator, 
                 capacity_in_words: int,       # FIFO的用户 facing 规格
                 core_bit_width: int,        # 底层RAM的性能规格
                 core_access_latency: int = 1, # 底层RAM的性能规格
                 data_simulation_enabled: bool = True, # [修正]: 添加此参数
                 parent: Optional[HwModule] = None):
        """
        初始化一个自包含的FIFO。
        """
        super().__init__(name, sim, parent)
        
        self.capacity = capacity_in_words

        # 在内部创建并拥有一个私有的[协程版]RAM实例
        self.ram_backend = SinglePortRAM(
            name="ram_backend",  # 名字会自动变为 "MyFIFO.ram_backend"
            sim=self.sim,
            size_in_words=self.capacity, # RAM的大小 = FIFO的容量
            core_bit_width=core_bit_width,
            core_access_latency=core_access_latency,
            data_simulation_enabled=data_simulation_enabled, # [修正]: 将参数传递下去
            parent=self # 自动向父模块注册
        )

        # --- FIFO内部状态 ---
        self.read_ptr: int = 0
        self.write_ptr: int = 0
        self.current_fill_level: int = 0

        # --- [已删除]: 所有 pending_..._callback 变量已被移除 ---

        # --- 统计指标 ---
        self._register_stat("pushes_performed", 0)
        self._register_stat("pops_performed", 0)
        self._register_stat("pushes_rejected_full", 0)
        self._register_stat("pushes_rejected_busy", 0)
        self._register_stat("pops_rejected_empty", 0)
        self._register_stat("pops_rejected_busy", 0)

    # --- 公共接口 (协程方法) ---

    def push(self, word_data: Any) -> Generator[Any, Any, None]:
        """
        [协程] 请求向FIFO推入一个“字”。
        会 'yield' 直到RAM写入完成。
        """
        
        # 1. 检查是否已满
        if self.current_fill_level == self.capacity:
            self._increment_stat("pushes_rejected_full")
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"PUSH 失败 (FIFO已满)")
            return # 'return' 结束这个协程
            
        # 2. 检查是否正忙
        if self.busy:
            self._increment_stat("pushes_rejected_busy")
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"PUSH 失败 (FIFO正忙)")
            return

        # 3. 设置状态
        self._set_busy()
        ram_address = self.write_ptr
        self.write_ptr = (self.write_ptr + 1) % self.capacity
        self.current_fill_level += 1
        
        # 4. [核心改动]: 'yield' 子任务
        #    Simulator 将暂停 'push'，直到 'ram_backend.write' 完成
        yield self.ram_backend.write(
            word_address=ram_address,
            data=[word_data] 
        )
        
        # 5. [唤醒点]: RAM 写入完成，代码从这里继续
        
        # 6. 完成 'on_push_complete' 的逻辑
        self._set_idle()
        self._increment_stat("pushes_performed")
        
        # 协程结束

    def pop(self) -> Generator[Any, Any, Any]:
        """
        [协程] 请求从FIFO弹出一个“字”。
        会 'yield' 直到RAM读取完成，然后 'return' 读到的数据。
        """
        
        # 1. 检查是否已空
        if self.current_fill_level == 0:
            self._increment_stat("pops_rejected_empty")
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"POP 失败 (FIFO已空)")
            return None # “异步返回” None 表示失败
            
        # 2. 检查是否正忙
        if self.busy:
            self._increment_stat("pops_rejected_busy")
            print(f"警告: [{self.full_name}] 在 t={self.sim.current_time} "
                  f"POP 失败 (FIFO正忙)")
            return None

        # 3. 设置状态
        self._set_busy()
        ram_address = self.read_ptr
        self.read_ptr = (self.read_ptr + 1) % self.capacity
        self.current_fill_level -= 1
        
        # 4. [核心改动]: 'yield' 子任务，并[捕获]其返回值
        data_list = yield self.ram_backend.read(
            word_address=ram_address,
            num_words=1
        )
        
        # 5. [唤醒点]: RAM 读取完成, 'data_list' 已被赋值
        
        # 6. 完成 'on_pop_complete' 的逻辑
        self._set_idle()
        self._increment_stat("pops_performed")
        
        word_data = data_list[0] if data_list else None
        
        # 7. [核心改动]: “异步返回”数据
        return word_data

    # --- [已删除]: _on_push_complete 和 _on_pop_complete
    #     它们的功能已被合并到 'push' 和 'pop' 的协程体中。

    # --- [已删除]: report_stats
    #     基类 HwModule 已自动处理递归报告。