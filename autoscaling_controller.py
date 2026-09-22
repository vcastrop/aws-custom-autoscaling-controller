import boto3
from datetime import datetime, timedelta, timezone

# ============================================================
# CONFIGURATION
# ============================================================

REGION = "us-east-1"

# Capacity limits required by the challenge
MIN_INSTANCES = 1
MAX_INSTANCES = 5

# Initial thresholds.
# These will be validated and adjusted during the experiments.
SCALE_OUT_THRESHOLD = 60.0
SCALE_IN_THRESHOLD = 20.0

# For now, only these instances are managed by the controller.
# Later we will replace this with project tags so dynamically
# created instances are automatically detected.
INSTANCE_NAMES = [
    "autoscaling-web-base",
    "autoscaling-web-test-2"
]


# ============================================================
# AWS CLIENTS
# ============================================================

ec2 = boto3.client("ec2", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)


# ============================================================
# OBSERVE
# ============================================================

def get_running_instances():
    """
    Returns the running EC2 instances currently managed
    by the controller.
    """

    response = ec2.describe_instances(
        Filters=[
            {
                "Name": "instance-state-name",
                "Values": ["running"]
            },
            {
                "Name": "tag:Name",
                "Values": INSTANCE_NAMES
            }
        ]
    )

    instances = []

    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:

            # Get Name tag
            instance_name = "N/A"

            for tag in instance.get("Tags", []):
                if tag["Key"] == "Name":
                    instance_name = tag["Value"]
                    break

            instances.append({
                "id": instance["InstanceId"],
                "name": instance_name,
                "type": instance["InstanceType"],
                "private_ip": instance.get(
                    "PrivateIpAddress",
                    "N/A"
                )
            })

    return instances


def get_cpu(instance_id):
    """
    Gets the latest available 5-minute average CPUUtilization
    metric for an EC2 instance from CloudWatch.
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
        key=lambda x: x["Timestamp"]
    )

    return latest["Average"]


# ============================================================
# ANALYZE
# ============================================================

def calculate_fleet_cpu(cpu_values):
    """
    Calculates the average CPU utilization of the fleet.

    Returns None when no valid CloudWatch metrics are available.
    """

    if not cpu_values:
        return None

    return sum(cpu_values) / len(cpu_values)


# ============================================================
# DECIDE
# ============================================================

def decide_capacity(instance_count, fleet_cpu):
    """
    Determines whether capacity should increase, decrease,
    or remain unchanged.

    This function ONLY returns a decision.
    It does not modify AWS resources.
    """

    # Safe behavior if CloudWatch does not return metrics
    if fleet_cpu is None:
        return (
            "MAINTAIN_CAPACITY",
            "No CPU metrics available. Safe fallback."
        )

    # ----------------------------
    # SCALE OUT
    # ----------------------------

    if fleet_cpu >= SCALE_OUT_THRESHOLD:

        if instance_count >= MAX_INSTANCES:
            return (
                "MAINTAIN_CAPACITY",
                f"Maximum capacity reached "
                f"({instance_count}/{MAX_INSTANCES})."
            )

        return (
            "INCREASE_CAPACITY",
            f"Fleet CPU {fleet_cpu:.2f}% >= "
            f"{SCALE_OUT_THRESHOLD:.2f}%."
        )

    # ----------------------------
    # SCALE IN
    # ----------------------------

    if fleet_cpu <= SCALE_IN_THRESHOLD:

        if instance_count <= MIN_INSTANCES:
            return (
                "MAINTAIN_CAPACITY",
                f"Minimum capacity reached "
                f"({instance_count}/{MIN_INSTANCES})."
            )

        return (
            "REDUCE_CAPACITY",
            f"Fleet CPU {fleet_cpu:.2f}% <= "
            f"{SCALE_IN_THRESHOLD:.2f}%."
        )

    # ----------------------------
    # MAINTAIN
    # ----------------------------

    return (
        "MAINTAIN_CAPACITY",
        f"Fleet CPU {fleet_cpu:.2f}% is inside the "
        f"{SCALE_IN_THRESHOLD:.2f}% - "
        f"{SCALE_OUT_THRESHOLD:.2f}% stability range."
    )


# ============================================================
# MAIN CONTROLLER
# ============================================================

def main():

    print("=" * 60)
    print("CUSTOM AUTO SCALING CONTROLLER")
    print("MODE: DRY RUN")
    print("=" * 60)

    timestamp = datetime.now(timezone.utc)

    print(
        f"\nTimestamp (UTC): "
        f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # --------------------------------------------------------
    # OBSERVE
    # --------------------------------------------------------

    print("\n[OBSERVE]")

    instances = get_running_instances()
    instance_count = len(instances)

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

        if cpu is None:
            print("  CPU:        No data")

        else:
            print(f"  CPU:        {cpu:.2f}%")
            cpu_values.append(cpu)

    # --------------------------------------------------------
    # ANALYZE
    # --------------------------------------------------------

    print("\n" + "-" * 60)
    print("[ANALYZE]")

    fleet_cpu = calculate_fleet_cpu(cpu_values)

    if fleet_cpu is None:
        print("Fleet average CPU: No data")

    else:
        print(
            f"Fleet average CPU: "
            f"{fleet_cpu:.2f}%"
        )

    print(
        f"Scale-in threshold:  "
        f"{SCALE_IN_THRESHOLD:.2f}%"
    )

    print(
        f"Scale-out threshold: "
        f"{SCALE_OUT_THRESHOLD:.2f}%"
    )

    # --------------------------------------------------------
    # DECIDE
    # --------------------------------------------------------

    print("\n" + "-" * 60)
    print("[DECIDE]")

    decision, reason = decide_capacity(
        instance_count,
        fleet_cpu
    )

    print(f"Decision: {decision}")
    print(f"Reason:   {reason}")

    print(
        f"Capacity: {instance_count} "
        f"(min={MIN_INSTANCES}, max={MAX_INSTANCES})"
    )

    # --------------------------------------------------------
    # ACT
    # --------------------------------------------------------

    print("\n" + "-" * 60)
    print("[ACT]")

    print("DRY RUN - No AWS resources were modified.")

    if decision == "INCREASE_CAPACITY":
        print(
            "Simulated action: "
            "Launch one additional EC2 instance."
        )

    elif decision == "REDUCE_CAPACITY":
        print(
            "Simulated action: "
            "Remove one EC2 instance."
        )

    else:
        print(
            "Simulated action: "
            "Keep current capacity."
        )

    print("\n" + "=" * 60)
    print("CONTROLLER EXECUTION COMPLETED")
    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()