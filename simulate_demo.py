# File: simulate_demo.py
#
# Root entry point for the PQC_DSS toy simulator demo.

from __future__ import annotations

import argparse

from core import Simulator
from examples.pipeline_demo import (
    DemoTestbench,
    ToyPipelineAccelerator,
    expected_payload,
    format_token_trace,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PQC_DSS toy simulator demo.")
    parser.add_argument(
        "--mode",
        choices=sorted(ToyPipelineAccelerator.MODES),
        default="fast",
        help="Pipeline timing mode to simulate.",
    )
    parser.add_argument(
        "--first-wave",
        type=int,
        default=8,
        help="Number of tokens in the first burst.",
    )
    parser.add_argument(
        "--second-wave",
        type=int,
        default=3,
        help="Number of tokens in the second burst.",
    )
    parser.add_argument(
        "--gap",
        type=int,
        default=3,
        help="Delay cycles between the two traffic waves.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sim = Simulator()
    dut = ToyPipelineAccelerator("toy_pqc_pipeline", sim, mode=args.mode)
    tb = DemoTestbench(
        sim,
        dut,
        first_wave_tokens=args.first_wave,
        second_wave_tokens=args.second_wave,
        gap_cycles=args.gap,
    )

    tb_task = sim.spawn(tb.run)
    sim.run()

    print("\n=== Token results ===")
    failures = []
    for token in tb_task.result:
        input_payload = token.token_id + 1
        expected = expected_payload(input_payload)
        status = "PASS" if token.payload == expected else "FAIL"
        if status == "FAIL":
            failures.append((token.token_id, token.payload, expected))
        print(
            f"token={token.token_id}, input={input_payload}, "
            f"payload={token.payload}, expected={expected}, {status}, "
            f"trace={format_token_trace(token)}"
        )

    print("\n=== Module statistics ===")
    dut.report_stats()

    if failures:
        print("\n=== Validation failed ===")
        for token_id, actual, expected in failures:
            print(f"token={token_id}: actual={actual}, expected={expected}")
        raise SystemExit(1)

    print("\n=== Validation passed ===")


if __name__ == "__main__":
    main()
