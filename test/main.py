# main.py

import sys
import os
from typing import List, Any, Optional

# 将项目根目录添加到 Python 路径中
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 将当前目录（test）也添加到路径中，以便可以直接导入同目录下的模块
test_dir = os.path.dirname(os.path.abspath(__file__))
if test_dir not in sys.path:
    sys.path.insert(0, test_dir)

# --- 1. 导入"硬件世界" ---
from core import HwModule
from SinglePortRAM import SinglePortRAM # (协程版)
from Fifo import Fifo                 # (协程版)
from SimpleALU import SimpleALU        # (协程版)

# --- 2. 导入"物理引擎" ---
from core import Simulator, Event

class MyALUTestbench:
    """
    一个【纯粹的】Python类，用于充当测试平台。
    【新】：这个版本演示了如何【灵活】地：
    1. 在循环中“并行”发射和等待 (spawn + yield [list])
    2. 在任意时刻“显式等待” (yield self.sim.delay)
    """
    def __init__(self, sim: Simulator, alu_to_test: SimpleALU):
        self.sim = sim
        self.alu = alu_to_test

    def run_test(self, a_list: List[Any], b_list: List[Any], op: str, exec_count: int):
        """
        这就是我们的“启动方法”（协程）。
        """
        print(f"[t={self.sim.current_time: >4}] [Testbench] 启动【灵活并发 + 任意延时】测试...")
        
        # --- 阶段1 & 2: 【循环中并行】加载所有A和所有B ---
        
        num_pairs = min(len(a_list), len(b_list))
        
        print(f"--- 正在【循环 {num_pairs} 次】，每次发射一对并行的 A/B 任务 ---")

        # 【场景A的实现】：
        for i in range(num_pairs):
            print(f"[t={self.sim.current_time: >4}] [Testbench] (循环 {i}) 正在【并行发射】 A({a_list[i]}) 和 B({b_list[i]})")
            
            # 1. 【并行启动】: 
            #    'spawn' 立即(在t=...)启动两个新任务
            #    ALU的 'busy_a' 和 'busy_b' 被激活
            task_a = self.sim.spawn(self.alu.load_a, a_list[i])
            task_b = self.sim.spawn(self.alu.load_b, b_list[i])
            
            # 2. 【并行等待 (屏障)】: 
            #    "yield" 这个列表，【暂停】这个 for 循环
            #    直到 task_a 和 task_b 【全部】完成
            yield [task_a, task_b]
            
            print(f"[t={self.sim.current_time: >4}] [Testbench] (循环 {i}) 【汇合】: A 和 B 均已完成。")
            
        print(f"\n[t={self.sim.current_time: >4}] [Testbench] === 所有A和B已全部【并行】加载 ===\n")

        
        # --- 阶段 3: 【任意时刻】的 Execute ---
        
        # 【场景B的实现】：
        # 在所有 load 完成后，先【显式等待】50个周期
        print(f"[t={self.sim.current_time: >4}] [Testbench] (任意时刻) 正在等待 50 个周期，然后再开始 Execute...")
        
        # 1. 【这就是您要的“任意时刻”工具】
        #    Testbench主动“暂停”自己，并“预约”在50个周期后被唤醒
        yield self.sim.delay(50) 
        
        
        print(f"\n[t={self.sim.current_time: >4}] [Testbench] 50 周期等待结束，开始 Execute 循环。")
        
        results = []
        for i in range(exec_count):
            print(f"[t={self.sim.current_time: >4}] [Testbench] 正在请求 Execute '{op}' (第 {i+1} 次)")
            
            # (串行等待) 硬件自己完成
            result = yield self.alu.execute(op) 
            
            print(f"[t={self.sim.current_time: >4}] [Testbench] 收到Execute结果: {result}")
            results.append(result)

            # 2. 【“任意时刻”的另一个例子】
            #    在两次 execute 之间，再【显式等待】25个周期
            if i < exec_count - 1: # (如果不是最后一次)
                 print(f"[t={self.sim.current_time: >4}] [Testbench] 正在等待 25 个周期，再执行下一次...")
                 yield self.sim.delay(25)
        
        print(f"\n--- 测试序列成功结束 ---")
        print(f"--- 最终结果: {results} ---")

# ==============================================================================
# 仿真主程序 (if __name__ == '__main__')
# (这部分无需修改)
# ==============================================================================
if __name__ == '__main__':
    
    # (确保所有 py 文件都在路径中)
    
    # 1. 创建仿真世界
    sim_engine = Simulator()
    
    # 2. 组装【硬件】 (HwModule)
    #    (我们假设所有模块都已修正，支持“双模式”数据)
    alu_dut = SimpleALU(name="MyALU", sim=sim_engine, data_simulation_enabled=True)
    
    # 3. 创建【软件】 (纯Python类)
    testbench = MyALUTestbench(sim=sim_engine, alu_to_test=alu_dut)
    
    # 4. 准备测试数据
    a_data = list(range(1, 11))  # 10个A
    b_data = list(range(100, 110)) # 10个B
    
    # 5. 安排“第一推动力”
    sim_engine.spawn(testbench.run_test, # <-- 我们想调用的“启动方法”
                       a_list=a_data,
                       b_list=b_data,
                       op="add",
                       exec_count=5)
    
    # 6. 运行仿真
    sim_engine.run()

    # 7. 报告统计数据
    print("\n" + "="*30 + " 最终统计报告 " + "="*30)
    alu_dut.report_stats()