import boto3
from datetime import datetime, timedelta, timezone

# ============================================================
# CONFIGURATION
# ============================================================

REGION = "us-east-1"

MIN_INSTANCES = 1
MAX_INSTANCES = 5

# Initial thresholds - will be validated experimentally
SCALE_OUT_CPU_THRESHOLD = 60.0
SCALE_IN_CPU_THRESHOLD = 20.0

# Detect individual overloaded instances
HIGH_INSTANCE_CPU_THRESHOLD = 80.0

# ALB request thresholds per 5-minute period.
# Initial experimental values; not final.
SCALE_OUT_REQUEST_THRESHOLD = 1000
SCALE_IN_REQUEST_THRESHOLD = 100

PROJECT_TAG = "CustomAutoScaling"
MANAGED_BY_TAG = "CustomController"

# CloudWatch LoadBalancer dimension extracted from the ALB ARN
ALB_DIMENSION = "app/autoscaling-web-alb/b93f8a5f93d870ab"


# ============================================================
# AWS CLIENTS
# ============================================================

ec2 = boto3.client("ec2", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)


# ============================================================
# OBSERVE - EC2
# ============================================================

def get_running_instances():
    """
    Returns running EC2 instances managed by this controller.
    Discovery is based on project tags.
    """

    response = ec2.describe_instances(
        Filters=[
            {
                "Name": "instance-state-name",
                "Values": ["running"]
            },
            {
                "Name": "tag:Project",
                "Values": [PROJECT_TAG]
            },
            {
                "Name": "tag:ManagedBy",
                "Values": [MANAGED_BY_TAG]
            }
        ]
    )

    instances = []

    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:

            tags = {
                tag["Key"]: tag["Value"]
                for tag in instance.get("Tags", [])
            }

            instances.append({
                "id": instance["InstanceId"],
                "name": tags.get("Name", "N/A"),
                "type": instance["InstanceType"],
                "private_ip": instance.get(
                    "PrivateIpAddress",
                    "N/A"
                ),
                "protected": (
                    tags.get("Protected", "false").lower()
                    == "true"
                )
            })

    return instances


def get_cpu(instance_id):
    """
    Gets the latest 5-minute Average CPUUtilization datapoint
    from CloudWatch for one EC2 instance.
    """

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=10)

    response = cloudwatch.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[
            {
                "Name": "InstanceId",
                "Value": instance_id
            }
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=300,
        Statistics=["Average"]
    )

    datapoints = response.get("Datapoints", [])

    if not datapoints:
        return None

    latest = max(
        datapoints,
        key=lambda point: point["Timestamp"]
    )

    return latest["Average"]


# ============================================================
# OBSERVE - APPLICATION LOAD BALANCER
# ============================================================

def get_request_count():
    """
    Gets the latest 5-minute RequestCount Sum for the ALB.
    """

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=10)

    response = cloudwatch.get_metric_statistics(
        Namespace="AWS/ApplicationELB",
        MetricName="RequestCount",
        Dimensions=[
            {
                "Name": "LoadBalancer",
                "Value": ALB_DIMENSION
            }
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=300,
        Statistics=["Sum"]
    )

    datapoints = response.get("Datapoints", [])

    if not datapoints:
        return None

    latest = max(
        datapoints,
        key=lambda point: point["Timestamp"]
    )

    return latest["Sum"]


# ============================================================
# ANALYZE
# ============================================================

def analyze_metrics(cpu_values, request_count):
    """
    Calculates fleet-level metrics.

    Returns:
        fleet_cpu_avg
        max_instance_cpu
        request_count
    """

    if cpu_values:
        fleet_cpu_avg = sum(cpu_values) / len(cpu_values)
        max_instance_cpu = max(cpu_values)
    else:
        fleet_cpu_avg = None
        max_instance_cpu = None

    return {
        "fleet_cpu_avg": fleet_cpu_avg,
        "max_instance_cpu": max_instance_cpu,
        "request_count": request_count
    }


# ============================================================
# DECIDE
# ============================================================

def decide_capacity(instance_count, metrics):
    """
    Makes a scaling decision without modifying AWS resources.

    Decisions:
        INCREASE_CAPACITY
        MAINTAIN_CAPACITY
        REDUCE_CAPACITY
    """

    fleet_cpu = metrics["fleet_cpu_avg"]
    max_cpu = metrics["max_instance_cpu"]
    requests = metrics["request_count"]

    # --------------------------------------------------------
    # SAFE FALLBACK
    # --------------------------------------------------------

    if fleet_cpu is None:
        return (
            "MAINTAIN_CAPACITY",
            "CPU metrics unavailable. Safe fallback."
        )

    # --------------------------------------------------------
    # SCALE OUT
    # --------------------------------------------------------

    high_average_cpu = (
        fleet_cpu >= SCALE_OUT_CPU_THRESHOLD
    )

    high_individual_cpu = (
        max_cpu is not None
        and max_cpu >= HIGH_INSTANCE_CPU_THRESHOLD
    )

    high_requests = (
        requests is not None
        and requests >= SCALE_OUT_REQUEST_THRESHOLD
    )

    if high_average_cpu or high_individual_cpu or high_requests:

        if instance_count >= MAX_INSTANCES:
            return (
                "MAINTAIN_CAPACITY",
                f"Scale-out condition detected, but maximum "
                f"capacity is already reached "
                f"({instance_count}/{MAX_INSTANCES})."
            )

        reasons = []

        if high_average_cpu:
            reasons.append(
                f"fleet CPU {fleet_cpu:.2f}% >= "
                f"{SCALE_OUT_CPU_THRESHOLD:.2f}%"
            )

        if high_individual_cpu:
            reasons.append(
                f"max instance CPU {max_cpu:.2f}% >= "
                f"{HIGH_INSTANCE_CPU_THRESHOLD:.2f}%"
            )

        if high_requests:
            reasons.append(
                f"RequestCount {requests:.0f} >= "
                f"{SCALE_OUT_REQUEST_THRESHOLD}"
            )

        return (
            "INCREASE_CAPACITY",
            "Scale-out condition: " + "; ".join(reasons)
        )

    # --------------------------------------------------------
    # SCALE IN
    # --------------------------------------------------------

    low_average_cpu = (
        fleet_cpu <= SCALE_IN_CPU_THRESHOLD
    )

    low_requests = (
        requests is not None
        and requests <= SCALE_IN_REQUEST_THRESHOLD
    )

    # Scale-in is intentionally more conservative.
    # Both CPU and RequestCount must indicate low demand.
    if low_average_cpu and low_requests:

        if instance_count <= MIN_INSTANCES:
            return (
                "MAINTAIN_CAPACITY",
                f"Low demand detected, but minimum capacity "
                f"is already reached "
                f"({instance_count}/{MIN_INSTANCES})."
            )

        return (
            "REDUCE_CAPACITY",
            f"Low demand: fleet CPU {fleet_cpu:.2f}% <= "
            f"{SCALE_IN_CPU_THRESHOLD:.2f}% AND "
            f"RequestCount {requests:.0f} <= "
            f"{SCALE_IN_REQUEST_THRESHOLD}."
        )

    # --------------------------------------------------------
    # MAINTAIN
    # --------------------------------------------------------

    if requests is None:
        request_text = "No RequestCount data"
    else:
        request_text = f"RequestCount={requests:.0f}"

    return (
        "MAINTAIN_CAPACITY",
        f"No scaling condition met. "
        f"Fleet CPU={fleet_cpu:.2f}%, "
        f"Max CPU={max_cpu:.2f}%, "
        f"{request_text}."
    )


# ============================================================
# MAIN CONTROLLER
# ============================================================

def main():

    print("=" * 65)
    print("CUSTOM AUTO SCALING CONTROLLER")
    print("MODE: DRY RUN")
    print("=" * 65)

    timestamp = datetime.now(timezone.utc)

    print(
        f"\nTimestamp (UTC): "
        f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # ========================================================
    # OBSERVE
    # ========================================================

    print("\n[OBSERVE]")

    instances = get_running_instances()
    instance_count = len(instances)

    print(
        f"Discovery tags: "
        f"Project={PROJECT_TAG}, "
        f"ManagedBy={MANAGED_BY_TAG}"
    )

    print(f"Running instances: {instance_count}")

    print(
        f"Allowed capacity: "
        f"{MIN_INSTANCES}-{MAX_INSTANCES}"
    )

    cpu_values = []

    for instance in instances:

        cpu = get_cpu(instance["id"])

        print("\nInstance:")
        print(f"  Name:       {instance['name']}")
        print(f"  ID:         {instance['id']}")
        print(f"  Type:       {instance['type']}")
        print(f"  Private IP: {instance['private_ip']}")
        print(f"  Protected:  {instance['protected']}")

        if cpu is None:
            print("  CPU:        No data")

        else:
            print(f"  CPU:        {cpu:.2f}%")
            cpu_values.append(cpu)

    request_count = get_request_count()

    print("\nApplication Load Balancer:")

    if request_count is None:
        print("  RequestCount (5 min): No data")
    else:
        print(
            f"  RequestCount (5 min): "
            f"{request_count:.0f}"
        )

    # ========================================================
    # ANALYZE
    # ========================================================

    print("\n" + "-" * 65)
    print("[ANALYZE]")

    metrics = analyze_metrics(
        cpu_values,
        request_count
    )

    fleet_cpu = metrics["fleet_cpu_avg"]
    max_cpu = metrics["max_instance_cpu"]

    if fleet_cpu is None:
        print("Fleet average CPU: No data")
    else:
        print(
            f"Fleet average CPU: "
            f"{fleet_cpu:.2f}%"
        )

    if max_cpu is None:
        print("Maximum instance CPU: No data")
    else:
        print(
            f"Maximum instance CPU: "
            f"{max_cpu:.2f}%"
        )

    if request_count is None:
        print("ALB RequestCount: No data")
    else:
        print(
            f"ALB RequestCount (5 min): "
            f"{request_count:.0f}"
        )

    print("\nThresholds:")

    print(
        f"  Scale-in CPU:       "
        f"<= {SCALE_IN_CPU_THRESHOLD:.2f}%"
    )

    print(
        f"  Scale-out CPU:      "
        f">= {SCALE_OUT_CPU_THRESHOLD:.2f}%"
    )

    print(
        f"  High instance CPU:  "
        f">= {HIGH_INSTANCE_CPU_THRESHOLD:.2f}%"
    )

    print(
        f"  Scale-in requests:  "
        f"<= {SCALE_IN_REQUEST_THRESHOLD}"
    )

    print(
        f"  Scale-out requests: "
        f">= {SCALE_OUT_REQUEST_THRESHOLD}"
    )

    # ========================================================
    # DECIDE
    # ========================================================

    print("\n" + "-" * 65)
    print("[DECIDE]")

    decision, reason = decide_capacity(
        instance_count,
        metrics
    )

    print(f"Decision: {decision}")
    print(f"Reason:   {reason}")

    print(
        f"Capacity: {instance_count} "
        f"(min={MIN_INSTANCES}, "
        f"max={MAX_INSTANCES})"
    )

    # ========================================================
    # ACT - DISABLED
    # ========================================================

    print("\n" + "-" * 65)
    print("[ACT]")

    print(
        "DRY RUN - No AWS resources were modified."
    )

    if decision == "INCREASE_CAPACITY":

        print(
            "Simulated action: "
            "Launch one additional managed EC2 instance."
        )

    elif decision == "REDUCE_CAPACITY":

        removable_instances = [
            instance
            for instance in instances
            if not instance["protected"]
        ]

        if removable_instances:

            candidate = removable_instances[0]

            print(
                "Simulated action: "
                f"Remove {candidate['name']} "
                f"({candidate['id']})."
            )

        else:

            print(
                "Simulated action cancelled: "
                "No unprotected instance available."
            )

    else:

        print(
            "Simulated action: "
            "Keep current capacity."
        )

    print("\n" + "=" * 65)
    print("CONTROLLER EXECUTION COMPLETED")
    print("=" * 65)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()