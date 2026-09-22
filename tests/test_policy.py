from controller.policy import (
    INCREASE_CAPACITY,
    MAINTAIN_CAPACITY,
    REDUCE_CAPACITY,
    ScalingPolicy,
)


CONFIG = {
    "capacity": {
        "min_instances": 1,
        "max_instances": 5,
        "scale_step": 1,
    },
    "thresholds": {
        "cpu_scale_out": 60.0,
        "cpu_scale_in": 20.0,
        "cpu_individual_high": 80.0,
        "requests_scale_out": 1000,
        "requests_scale_in": 100,
    },
}


def make_observation(
    capacity,
    average_cpu,
    maximum_cpu,
    request_count,
):
    return {
        "capacity": {
            "running": capacity,
            "healthy": capacity,
        },
        "metrics": {
            "cpu": {
                "average": average_cpu,
                "maximum": maximum_cpu,
                "per_instance": {},
            },
            "request_count": request_count,
        },
        "instances": [],
        "targets": [],
    }


def test_scale_out_by_average_cpu():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=1,
        average_cpu=70.0,
        maximum_cpu=70.0,
        request_count=500,
    )

    decision = policy.evaluate(observation)

    assert decision.action == INCREASE_CAPACITY
    assert decision.current_capacity == 1
    assert decision.target_capacity == 2


def test_scale_out_by_individual_cpu():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=2,
        average_cpu=45.0,
        maximum_cpu=85.0,
        request_count=500,
    )

    decision = policy.evaluate(observation)

    assert decision.action == INCREASE_CAPACITY
    assert decision.target_capacity == 3


def test_scale_out_by_request_count():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=1,
        average_cpu=30.0,
        maximum_cpu=35.0,
        request_count=1200,
    )

    decision = policy.evaluate(observation)

    assert decision.action == INCREASE_CAPACITY
    assert decision.target_capacity == 2


def test_scale_in():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=3,
        average_cpu=10.0,
        maximum_cpu=15.0,
        request_count=50,
    )

    decision = policy.evaluate(observation)

    assert decision.action == REDUCE_CAPACITY
    assert decision.current_capacity == 3
    assert decision.target_capacity == 2


def test_maintain_normal_load():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=2,
        average_cpu=40.0,
        maximum_cpu=45.0,
        request_count=400,
    )

    decision = policy.evaluate(observation)

    assert decision.action == MAINTAIN_CAPACITY
    assert decision.target_capacity == 2


def test_max_capacity_is_respected():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=5,
        average_cpu=90.0,
        maximum_cpu=95.0,
        request_count=2000,
    )

    decision = policy.evaluate(observation)

    assert decision.action == MAINTAIN_CAPACITY
    assert decision.target_capacity == 5


def test_min_capacity_is_respected():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=1,
        average_cpu=5.0,
        maximum_cpu=10.0,
        request_count=10,
    )

    decision = policy.evaluate(observation)

    assert decision.action == MAINTAIN_CAPACITY
    assert decision.target_capacity == 1


def test_cooldown_blocks_scaling():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=2,
        average_cpu=90.0,
        maximum_cpu=95.0,
        request_count=2000,
    )

    decision = policy.evaluate(
        observation,
        cooldown_active=True,
    )

    assert decision.action == MAINTAIN_CAPACITY
    assert decision.target_capacity == 2


def test_missing_cpu_metrics_maintains_capacity():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=2,
        average_cpu=None,
        maximum_cpu=None,
        request_count=1500,
    )

    decision = policy.evaluate(observation)

    assert decision.action == MAINTAIN_CAPACITY
    assert decision.target_capacity == 2


def test_zero_capacity_restores_minimum():
    policy = ScalingPolicy(CONFIG)

    observation = make_observation(
        capacity=0,
        average_cpu=None,
        maximum_cpu=None,
        request_count=None,
    )

    decision = policy.evaluate(observation)

    assert decision.action == INCREASE_CAPACITY
    assert decision.target_capacity == 1