from __future__ import annotations
from typing import Any, Generator, Optional

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core import Simulator, HwModule
from core.simulator import Signal

def banner(title: str):
    print("\n" + "=" * 28 + f" {title} " + "=" * 28)


# =============================================================================
# 测试1：模块A等待模块B的 on_idle
#   - ResourceModule: 拥有 busy / on_idle
#   - RequesterModule: 等待 ResourceModule 的 signal
# =============================================================================
class ResourceModule(HwModule):
    def __init__(self, name: str, sim: Simulator, parent: Optional[HwModule] = None):
        super().__init__(name, sim, parent)
        self.on_idle = Signal(sim)

    def is_busy(self) -> bool:
        return self.busy

    def acquire(self, owner_name: str) -> bool:
        if self.busy:
            return False
        self._set_busy()
        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 被 {owner_name} 占用")
        return True

    def release(self, owner_name: str):
        self._set_idle()
        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 被 {owner_name} 释放")
        self.on_idle.notify_one()


class RequesterModule(HwModule):
    def __init__(self, name: str, sim: Simulator, work_cycles: int,
                 parent: Optional[HwModule] = None):
        super().__init__(name, sim, parent)
        self.work_cycles = work_cycles

    def request_and_use(self, resource: ResourceModule) -> Generator[Any, Any, None]:
        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 请求 {resource.full_name}")

        while resource.is_busy():
            print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 等待 {resource.full_name}.on_idle")
            yield resource.on_idle.wait()

        ok = resource.acquire(self.full_name)
        if not ok:
            # 理论上 while 已经挡住了，这里只是保险
            print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 抢占失败，重新等待")
            yield

        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 开始使用 {resource.full_name}")
        yield self.sim.delay(self.work_cycles)

        resource.release(self.full_name)
        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 使用完成")


class TB_ResourceWait:
    def __init__(self, sim: Simulator):
        self.sim = sim
        self.resource = ResourceModule("res0", sim)
        self.req_a = RequesterModule("reqA", sim, work_cycles=5)
        self.req_b = RequesterModule("reqB", sim, work_cycles=4)

    def run(self) -> Generator[Any, Any, None]:
        self.sim.spawn(self.req_a.request_and_use, self.resource)
        yield self.sim.delay(1)
        self.sim.spawn(self.req_b.request_and_use, self.resource)
        yield self.sim.delay(20)


# =============================================================================
# 测试2：模块A/B 等待同一个资源模块的 on_idle
#   看多个外部模块竞争一个资源模块
# =============================================================================
class TB_MultiRequester:
    def __init__(self, sim: Simulator):
        self.sim = sim
        self.resource = ResourceModule("shared_res", sim)
        self.req_a = RequesterModule("reqA", sim, work_cycles=4)
        self.req_b = RequesterModule("reqB", sim, work_cycles=3)
        self.req_c = RequesterModule("reqC", sim, work_cycles=2)

    def launch(self, requester: RequesterModule, delay_cycles: int) -> Generator[Any, Any, None]:
        if delay_cycles > 0:
            yield self.sim.delay(delay_cycles)
        yield requester.request_and_use(self.resource)

    def run(self) -> Generator[Any, Any, None]:
        self.sim.spawn(self.launch, self.req_a, 0)
        self.sim.spawn(self.launch, self.req_b, 1)
        self.sim.spawn(self.launch, self.req_c, 1)
        yield self.sim.delay(30)


# =============================================================================
# 测试3：Producer/Consumer 等待 MailboxModule 的 on_data_ready
#   - MailboxModule: 拥有数据状态和 on_data_ready
#   - ProducerModule: 写入 Mailbox
#   - ConsumerModule: 等待 Mailbox 的 signal
# =============================================================================
class MailboxModule(HwModule):
    def __init__(self, name: str, sim: Simulator, parent: Optional[HwModule] = None):
        super().__init__(name, sim, parent)
        self.data = None
        self.has_data = False
        self.on_data_ready = Signal(sim)

    def write_data(self, value: Any, producer_name: str):
        self.data = value
        self.has_data = True
        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 收到来自 {producer_name} 的数据: {value}")
        self.on_data_ready.notify_one()

    def read_data(self) -> Any:
        if not self.has_data:
            return None
        value = self.data
        self.data = None
        self.has_data = False
        return value


class ProducerModule(HwModule):
    def __init__(self, name: str, sim: Simulator, parent: Optional[HwModule] = None):
        super().__init__(name, sim, parent)

    def produce_after(self, mailbox: MailboxModule, value: Any, delay_cycles: int) -> Generator[Any, Any, None]:
        yield self.sim.delay(delay_cycles)
        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 产生数据 {value}")
        mailbox.write_data(value, self.full_name)


class ConsumerModule(HwModule):
    def __init__(self, name: str, sim: Simulator, parent: Optional[HwModule] = None):
        super().__init__(name, sim, parent)

    def consume_once(self, mailbox: MailboxModule) -> Generator[Any, Any, Any]:
        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 请求读取 {mailbox.full_name}")

        while not mailbox.has_data:
            print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 等待 {mailbox.full_name}.on_data_ready")
            yield mailbox.on_data_ready.wait()

        value = mailbox.read_data()
        print(f"[t={self.sim.current_time:>4}] [{self.full_name}] 读到数据 {value}")
        return value


class TB_ProducerConsumer:
    def __init__(self, sim: Simulator):
        self.sim = sim
        self.mailbox = MailboxModule("mailbox0", sim)
        self.producer = ProducerModule("producer0", sim)
        self.consumer = ConsumerModule("consumer0", sim)

    def run(self) -> Generator[Any, Any, None]:
        consumer_task = self.sim.spawn(self.consumer.consume_once, self.mailbox)
        self.sim.spawn(self.producer.produce_after, self.mailbox, 123, 6)

        value = yield consumer_task
        print(f"[t={self.sim.current_time:>4}] [TB] consumer 返回值 = {value}")

        yield self.sim.delay(10)


# =============================================================================
# 主程序：依次运行三个测试
# =============================================================================
def run_test_1():
    banner("测试1：一个模块等待另一个模块的 on_idle")
    sim = Simulator()
    tb = TB_ResourceWait(sim)
    sim.spawn(tb.run)
    sim.run()


def run_test_2():
    banner("测试2：多个模块等待同一个资源模块的 on_idle")
    sim = Simulator()
    tb = TB_MultiRequester(sim)
    sim.spawn(tb.run)
    sim.run()


def run_test_3():
    banner("测试3：Consumer 模块等待 Mailbox 模块的 on_data_ready")
    sim = Simulator()
    tb = TB_ProducerConsumer(sim)
    sim.spawn(tb.run)
    sim.run()


if __name__ == "__main__":
    run_test_1()
    run_test_2()
    run_test_3()