# core/hw_module.py (与我们之前最终的版本完全相同)

from __future__ import annotations
from typing import Optional, Dict, Any, List

# 假设 simulator_engine.py 也在 core 目录中
from .simulator import Simulator 


class HwModule:
    """
    【最终版】所有硬件模块的通用基类。
    
    【已修正】：重新添加了 _set_busy 和 _set_idle 辅助方法。
    """
    def __init__(self, name: str, sim: "Simulator", parent: Optional[HwModule] = None):
        
        self.name: str = name
        self.sim: Simulator = sim
        self.parent: Optional[HwModule] = parent
        
        # --- 容器功能 ---
        self._children: List[HwModule] = []
        if self.parent:
            self.parent._add_child_module(self)
        
        # --- 核心功能 ---
        if self.parent:
            self.full_name: str = f"{self.parent.full_name}.{self.name}"
        else:
            self.full_name: str = self.name
            
        self.busy: bool = False
        self.stats: Dict[str, int | float] = {}

    def _add_child_module(self, child_module: HwModule):
        if child_module.parent is not self:
             print(f"警告: 模块 {child_module.full_name} 的父模块 "
                   f"未正确设置为 {self.full_name}")
        self._children.append(child_module)

    # ⬇⬇⬇ 【修正：重新添加这些方法】 ⬇⬇⬇
    def _set_busy(self):
        """将模块状态设置为繁忙。"""
        self.busy = True

    def _set_idle(self):
        """将模块状态设置为空闲。"""
        self.busy = False
    # ⬆⬆⬆ 【修正结束】 ⬆⬆⬆

    def _register_stat(self, name: str, initial_value: int | float = 0):
        self.stats[name] = initial_value

    def _increment_stat(self, name: str, value: int | float = 1):
        if name not in self.stats:
            self._register_stat(name, 0)
        self.stats[name] += value
        
    def report_stats(self) -> None:
        """
        【已升级】: 打印此模块的统计，并【递归】打印所有子模块的统计。
        """
        print(f"--- 统计报告: [{self.full_name}] ---")
        if not self.stats:
            print("    (无统计数据)")
        else:
            max_key_len = max(len(key) for key in self.stats.keys())
            for key, value in self.stats.items():
                print(f"    {key:<{max_key_len}} : {value}")
        
        for child in self._children:
            child.report_stats()