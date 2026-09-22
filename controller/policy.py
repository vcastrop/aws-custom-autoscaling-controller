from dataclasses import dataclass


MAINTAIN_CAPACITY = "MAINTAIN_CAPACITY"
INCREASE_CAPACITY = "INCREASE_CAPACITY"
REDUCE_CAPACITY = "REDUCE_CAPACITY"


@dataclass
class Decision:
    action: str
    reason: str
    current_capacity: int
    target_capacity: int


class ScalingPolicy:
    """
    Reactive threshold-based scaling policy.

    Decision metrics:
    - Average fleet CPU
    - Maximum individual CPU
    - ALB RequestCount

    Possible decisions:
    - INCREASE_CAPACITY
    - REDUCE_CAPACITY
    - MAINTAIN_CAPACITY
    """

    def __init__(self, config):
        self.config = config

        self.min_instances = config["capacity"]["min_instances"]
        self.max_instances = config["capacity"]["max_instances"]
        self.scale_step = config["capacity"]["scale_step"]

        thresholds = config["thresholds"]

        self.cpu_scale_out = thresholds["cpu_scale_out"]
        self.cpu_scale_in = thresholds["cpu_scale_in"]
        self.cpu_individual_high = thresholds["cpu_individual_high"]

        self.requests_scale_out = thresholds["requests_scale_out"]
        self.requests_scale_in = thresholds["requests_scale_in"]

    def evaluate(self, observation, cooldown_active=False):
        """
        Evaluate one observation and return exactly one decision.
        """

        current_capacity = observation["capacity"]["running"]

        cpu = observation["metrics"]["cpu"]
        avg_cpu = cpu["average"]
        max_cpu = cpu["maximum"]

        request_count = observation["metrics"]["request_count"]

        # -----------------------------------------------------
        # SAFETY: NO RUNNING CAPACITY
        # -----------------------------------------------------

        if current_capacity == 0:
            return Decision(
                action=INCREASE_CAPACITY,
                reason=(
                    "No managed running instances were detected. "
                    "Capacity must be restored to the configured minimum."
                ),
                current_capacity=current_capacity,
                target_capacity=self.min_instances,
            )

        # -----------------------------------------------------
        # INCOMPLETE METRICS
        # -----------------------------------------------------

        if avg_cpu is None or max_cpu is None:
            return Decision(
                action=MAINTAIN_CAPACITY,
                reason=(
                    "CPU metrics are incomplete. "
                    "Capacity is maintained to avoid an unsafe decision."
                ),
                current_capacity=current_capacity,
                target_capacity=current_capacity,
            )

        # RequestCount may legitimately have no datapoint when
        # there has been no ALB traffic in the observation window.
        effective_request_count = (
            0.0 if request_count is None else request_count
        )

        # -----------------------------------------------------
        # COOLDOWN
        # -----------------------------------------------------

        if cooldown_active:
            return Decision(
                action=MAINTAIN_CAPACITY,
                reason=(
                    "A scaling action is inside the cooldown period. "
                    "Capacity is maintained to avoid repeated actions."
                ),
                current_capacity=current_capacity,
                target_capacity=current_capacity,
            )

        # -----------------------------------------------------
        # SCALE OUT
        # -----------------------------------------------------

        high_average_cpu = avg_cpu >= self.cpu_scale_out
        high_individual_cpu = max_cpu >= self.cpu_individual_high
        high_requests = (
            effective_request_count >= self.requests_scale_out
        )

        if high_average_cpu or high_individual_cpu or high_requests:

            if current_capacity >= self.max_instances:
                return Decision(
                    action=MAINTAIN_CAPACITY,
                    reason=(
                        "High demand was detected, but the configured "
                        "maximum capacity has already been reached."
                    ),
                    current_capacity=current_capacity,
                    target_capacity=current_capacity,
                )

            target_capacity = min(
                current_capacity + self.scale_step,
                self.max_instances,
            )

            reasons = []

            if high_average_cpu:
                reasons.append(
                    f"average CPU {avg_cpu:.2f}% >= "
                    f"{self.cpu_scale_out:.2f}%"
                )

            if high_individual_cpu:
                reasons.append(
                    f"maximum CPU {max_cpu:.2f}% >= "
                    f"{self.cpu_individual_high:.2f}%"
                )

            if high_requests:
                reasons.append(
                    f"RequestCount {effective_request_count:.0f} >= "
                    f"{self.requests_scale_out}"
                )

            return Decision(
                action=INCREASE_CAPACITY,
                reason="Scale-out conditions met: " + "; ".join(reasons),
                current_capacity=current_capacity,
                target_capacity=target_capacity,
            )

        # -----------------------------------------------------
        # SCALE IN
        # -----------------------------------------------------

        low_cpu = avg_cpu <= self.cpu_scale_in
        low_requests = (
            effective_request_count <= self.requests_scale_in
        )

        if low_cpu and low_requests:

            if current_capacity <= self.min_instances:
                return Decision(
                    action=MAINTAIN_CAPACITY,
                    reason=(
                        "Low demand was detected, but the configured "
                        "minimum capacity has already been reached."
                    ),
                    current_capacity=current_capacity,
                    target_capacity=current_capacity,
                )

            target_capacity = max(
                current_capacity - self.scale_step,
                self.min_instances,
            )

            return Decision(
                action=REDUCE_CAPACITY,
                reason=(
                    "Scale-in conditions met: "
                    f"average CPU {avg_cpu:.2f}% <= "
                    f"{self.cpu_scale_in:.2f}% AND "
                    f"RequestCount {effective_request_count:.0f} <= "
                    f"{self.requests_scale_in}."
                ),
                current_capacity=current_capacity,
                target_capacity=target_capacity,
            )

        # -----------------------------------------------------
        # MAINTAIN
        # -----------------------------------------------------

        return Decision(
            action=MAINTAIN_CAPACITY,
            reason=(
                "Neither scale-out nor scale-in conditions were met. "
                f"Average CPU={avg_cpu:.2f}%, "
                f"maximum CPU={max_cpu:.2f}%, "
                f"RequestCount={effective_request_count:.0f}."
            ),
            current_capacity=current_capacity,
            target_capacity=current_capacity,
        )