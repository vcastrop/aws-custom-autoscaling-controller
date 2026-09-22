import sys
from pathlib import Path

# Allow execution with:
# python3 controller/controller.py
ROOT_DIR = Path(__file__).resolve().parent.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from controller.actuator import ScalingActuator
from controller.config import load_config
from controller.logging_utils import DecisionLogger
from controller.metrics import MetricsCollector
from controller.policy import (
    INCREASE_CAPACITY,
    MAINTAIN_CAPACITY,
    REDUCE_CAPACITY,
    ScalingPolicy,
)
from controller.state import ControllerState


def print_observation(observation):
    """
    Print a human-readable summary of the observed system state.
    """

    capacity = observation["capacity"]
    metrics = observation["metrics"]
    cpu = metrics["cpu"]

    print("\n[OBSERVE]")
    print(f"Running capacity: {capacity['running']}")
    print(f"Healthy targets:  {capacity['healthy']}")

    if cpu["average"] is None:
        print("Average CPU:      unavailable")
    else:
        print(f"Average CPU:      {cpu['average']:.2f}%")

    if cpu["maximum"] is None:
        print("Maximum CPU:      unavailable")
    else:
        print(f"Maximum CPU:      {cpu['maximum']:.2f}%")

    if metrics["request_count"] is None:
        print("RequestCount:     no datapoint")
    else:
        print(
            f"RequestCount:     "
            f"{metrics['request_count']:.0f}"
        )


def print_decision(decision):
    """
    Print the decision and its justification.
    """

    print("\n[DECIDE]")
    print(f"Decision:         {decision.action}")
    print(f"Current capacity: {decision.current_capacity}")
    print(f"Target capacity:  {decision.target_capacity}")
    print(f"Reason:           {decision.reason}")


def print_action_result(result):
    """
    Print the result returned by the actuator.
    """

    print("\n[ACT / VERIFY]")

    if result is None:
        print("No infrastructure change requested.")
        return

    print(f"Success:          {result.get('success')}")
    print(f"Instance ID:      {result.get('instance_id')}")
    print(f"Message:          {result.get('message')}")

    if result.get("ec2_running_seconds") is not None:
        print(
            "EC2 running time: "
            f"{result['ec2_running_seconds']} seconds"
        )

    if result.get("effective_capacity_seconds") is not None:
        print(
            "Effective capacity time: "
            f"{result['effective_capacity_seconds']} seconds"
        )

    if result.get("completion_seconds") is not None:
        print(
            "Scale-in completion time: "
            f"{result['completion_seconds']} seconds"
        )


def run_controller():
    """
    Execute one complete elasticity control cycle:

    OBSERVE
        ↓
    CHECK STATE
        ↓
    DECIDE
        ↓
    ACT
        ↓
    VERIFY
        ↓
    LOG
    """

    print("=" * 65)
    print("AWS CUSTOM AUTO-SCALING CONTROLLER")
    print("=" * 65)

    # -----------------------------------------------------
    # INITIALIZE
    # -----------------------------------------------------

    config = load_config()

    metrics = MetricsCollector(config)
    policy = ScalingPolicy(config)
    actuator = ScalingActuator(config)
    state = ControllerState(config)
    logger = DecisionLogger()

    # -----------------------------------------------------
    # OBSERVE
    # -----------------------------------------------------

    observation = metrics.collect()

    print_observation(observation)

    # -----------------------------------------------------
    # CONTROLLER STATE
    # -----------------------------------------------------

    cooldown = state.cooldown_status()

    print("\n[STATE]")
    print(f"Cooldown active:  {cooldown['active']}")
    print(
        "Cooldown remaining: "
        f"{cooldown['remaining_seconds']} seconds"
    )

    # -----------------------------------------------------
    # DECIDE
    # -----------------------------------------------------

    decision = policy.evaluate(
        observation=observation,
        cooldown_active=cooldown["active"],
    )

    print_decision(decision)

    # -----------------------------------------------------
    # ACT + VERIFY
    # -----------------------------------------------------

    action_result = None

    if decision.action == INCREASE_CAPACITY:

        action_result = actuator.scale_out(
            observation["instances"]
        )

    elif decision.action == REDUCE_CAPACITY:

        action_result = actuator.scale_in(
            observation["instances"]
        )

    elif decision.action == MAINTAIN_CAPACITY:

        action_result = None

    else:
        raise ValueError(
            f"Unknown controller decision: {decision.action}"
        )

    print_action_result(action_result)

    # -----------------------------------------------------
    # UPDATE STATE
    # -----------------------------------------------------

    if (
        action_result is not None
        and action_result.get("success") is True
    ):
        state.record_scaling_action(
            decision.action
        )

        print("\n[STATE UPDATE]")
        print("Successful scaling action recorded.")
        print("Cooldown started.")

    # -----------------------------------------------------
    # LOG
    # -----------------------------------------------------

    logger.log_cycle(
        observation=observation,
        decision=decision,
        cooldown_status=cooldown,
        action_result=action_result,
    )

    print("\n[LOG]")
    print("Controller cycle recorded in logs/decisions.jsonl")

    print("\n" + "=" * 65)
    print("CONTROLLER CYCLE COMPLETED")
    print("=" * 65)


if __name__ == "__main__":
    try:
        run_controller()

    except KeyboardInterrupt:
        print("\nController interrupted.")
        sys.exit(130)

    except Exception as exc:
        print("\n[CONTROLLER ERROR]")
        print(str(exc))
        sys.exit(1)