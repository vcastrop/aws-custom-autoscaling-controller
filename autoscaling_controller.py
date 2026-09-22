import boto3
import time
from datetime import datetime, timedelta, timezone

# ============================================================
# CONFIGURATION
# ============================================================

REGION = "us-east-1"

MIN_INSTANCES = 1
MAX_INSTANCES = 5

# ------------------------------------------------------------
# REAL ACTIONS
# ------------------------------------------------------------

# False = no AWS resources are modified by the controller.
# True  = real scale-out is allowed.
ENABLE_REAL_ACTIONS = True

# IMPORTANT:
# Real scale-in remains disabled independently for safety.
ENABLE_REAL_SCALE_IN = False

# ------------------------------------------------------------
# THRESHOLDS
# ------------------------------------------------------------

# Initial thresholds - will be validated experimentally
SCALE_OUT_CPU_THRESHOLD = 60.0
SCALE_IN_CPU_THRESHOLD = 20.0

# Detect individual overloaded instances
HIGH_INSTANCE_CPU_THRESHOLD = 80.0

# ALB request thresholds per 5-minute period.
# Initial experimental values; not final.
SCALE_OUT_REQUEST_THRESHOLD = 0
SCALE_IN_REQUEST_THRESHOLD = 100

# ------------------------------------------------------------
# RESOURCE IDENTIFIERS
# ------------------------------------------------------------

PROJECT_TAG = "CustomAutoScaling"
MANAGED_BY_TAG = "CustomController"

ALB_DIMENSION = "app/autoscaling-web-alb/b93f8a5f93d870ab"

LAUNCH_TEMPLATE_ID = "lt-089bd536e5ebf7f28"
LAUNCH_TEMPLATE_VERSION = "2"

TARGET_GROUP_ARN = (
    "arn:aws:elasticloadbalancing:us-east-1:"
    "929298073516:targetgroup/"
    "autoscaling-web-tg/d0df5973794dd8a7"
)

# Subnets attached to the ALB.
SUBNET_IDS = [
    "subnet-0a3897d81e5072e76",  # us-east-1a
    "subnet-00a75d68543daaa53",  # us-east-1d
]


# ============================================================
# AWS CLIENTS
# ============================================================

ec2 = boto3.client("ec2", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)
elbv2 = boto3.client("elbv2", region_name=REGION)


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
    Makes one of three explicit decisions:

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
# ACT - SCALE OUT
# ============================================================

def choose_subnet(instances):
    """
    Chooses between the two ALB subnets.

    The selection alternates based on the current number of
    managed instances so that repeated scale-outs do not always
    use exactly the same subnet.
    """

    index = len(instances) % len(SUBNET_IDS)
    return SUBNET_IDS[index]


def scale_out(instances):
    """
    Creates one EC2 instance from the Launch Template,
    waits until it is running, registers it in the Target Group,
    and waits until the ALB reports it as healthy.

    Returns the new instance ID and elapsed time.
    """

    current_count = len(instances)

    if current_count >= MAX_INSTANCES:
        print(
            "Scale-out cancelled: maximum capacity "
            f"{MAX_INSTANCES} already reached."
        )
        return None

    subnet_id = choose_subnet(instances)

    print("REAL ACTION: SCALE OUT")
    print(f"Current capacity: {current_count}")
    print(f"Target capacity:  {current_count + 1}")
    print(f"Launch Template:  {LAUNCH_TEMPLATE_ID}")
    print(f"Template version: {LAUNCH_TEMPLATE_VERSION}")
    print(f"Subnet:           {subnet_id}")

    start_time = time.monotonic()

    # --------------------------------------------------------
    # CREATE INSTANCE
    # --------------------------------------------------------

    print("\nLaunching new EC2 instance...")

    response = ec2.run_instances(
        LaunchTemplate={
            "LaunchTemplateId": LAUNCH_TEMPLATE_ID,
            "Version": LAUNCH_TEMPLATE_VERSION
        },
        SubnetId=subnet_id,
        MinCount=1,
        MaxCount=1
    )

    instance_id = response["Instances"][0]["InstanceId"]

    print(f"Created instance: {instance_id}")
    print("Waiting for EC2 state = running...")

    # --------------------------------------------------------
    # WAIT FOR RUNNING
    # --------------------------------------------------------

    running_waiter = ec2.get_waiter("instance_running")

    running_waiter.wait(
        InstanceIds=[instance_id],
        WaiterConfig={
            "Delay": 10,
            "MaxAttempts": 30
        }
    )

    print(f"Instance {instance_id} is running.")

    # --------------------------------------------------------
    # REGISTER IN TARGET GROUP
    # --------------------------------------------------------

    print("Registering instance in Target Group...")

    elbv2.register_targets(
        TargetGroupArn=TARGET_GROUP_ARN,
        Targets=[
            {
                "Id": instance_id,
                "Port": 80
            }
        ]
    )

    print("Target registered.")
    print("Waiting for ALB target state = healthy...")

    # --------------------------------------------------------
    # WAIT FOR HEALTHY
    # --------------------------------------------------------

    healthy_waiter = elbv2.get_waiter(
        "target_in_service"
    )

    healthy_waiter.wait(
        TargetGroupArn=TARGET_GROUP_ARN,
        Targets=[
            {
                "Id": instance_id,
                "Port": 80
            }
        ],
        WaiterConfig={
            "Delay": 15,
            "MaxAttempts": 40
        }
    )

    elapsed = time.monotonic() - start_time

    print(
        f"Instance {instance_id} is HEALTHY "
        "in the Target Group."
    )

    print(
        f"Scale-out completed in "
        f"{elapsed:.2f} seconds."
    )

    print(
        f"New capacity: {current_count + 1}"
    )

    return {
        "instance_id": instance_id,
        "elapsed_seconds": elapsed
    }


# ============================================================
# ACT
# ============================================================

def act(decision, instances):

    if decision == "INCREASE_CAPACITY":

        if not ENABLE_REAL_ACTIONS:

            print(
                "DRY RUN - Real AWS actions are disabled."
            )

            print(
                "Simulated action: "
                "Launch one additional managed EC2 instance."
            )

            return

        try:
            scale_out(instances)

        except Exception as error:

            print("ERROR DURING SCALE OUT")
            print(f"{type(error).__name__}: {error}")

            print(
                "Controller stopped the scaling action "
                "instead of attempting additional changes."
            )

        return

    # --------------------------------------------------------
    # SCALE IN
    # --------------------------------------------------------

    if decision == "REDUCE_CAPACITY":

        removable_instances = [
            instance
            for instance in instances
            if not instance["protected"]
        ]

        if not removable_instances:

            print(
                "Scale-in cancelled: "
                "No unprotected instance available."
            )
            return

        candidate = removable_instances[0]

        # Scale-in remains intentionally disabled for now.
        if not ENABLE_REAL_SCALE_IN:

            print(
                "SCALE-IN SAFETY MODE - "
                "Real termination is disabled."
            )

            print(
                "Simulated action: "
                f"Remove {candidate['name']} "
                f"({candidate['id']})."
            )

            return

        # We intentionally do NOT implement termination here yet.
        print(
            "Real scale-in has not been enabled "
            "in this controller version."
        )

        return

    # --------------------------------------------------------
    # MAINTAIN
    # --------------------------------------------------------

    print(
        "No infrastructure change required. "
        "Keeping current capacity."
    )


# ============================================================
# MAIN CONTROLLER
# ============================================================

def main():

    mode = (
        "REAL SCALE-OUT ENABLED"
        if ENABLE_REAL_ACTIONS
        else "DRY RUN"
    )

    print("=" * 65)
    print("CUSTOM AUTO SCALING CONTROLLER")
    print(f"MODE: {mode}")
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

    try:
        instances = get_running_instances()
    except Exception as error:
        print(
            f"ERROR discovering EC2 instances: {error}"
        )
        print(
            "Safe fallback: no scaling action performed."
        )
        return

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

        try:
            cpu = get_cpu(instance["id"])
        except Exception as error:
            print(
                f"\nCloudWatch error for "
                f"{instance['id']}: {error}"
            )
            cpu = None

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

    try:
        request_count = get_request_count()
    except Exception as error:
        print(
            f"\nCloudWatch ALB error: {error}"
        )
        request_count = None

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
    # ACT
    # ========================================================

    print("\n" + "-" * 65)
    print("[ACT]")

    act(
        decision,
        instances
    )

    print("\n" + "=" * 65)
    print("CONTROLLER EXECUTION COMPLETED")
    print("=" * 65)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()