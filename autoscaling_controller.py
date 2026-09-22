import boto3
from datetime import datetime, timedelta, timezone

# =========================
# CONFIGURACION
# =========================

REGION = "us-east-1"

MIN_INSTANCES = 1
MAX_INSTANCES = 5

INSTANCE_NAMES = [
    "autoscaling-web-base",
    "autoscaling-web-test-2"
]

# =========================
# CLIENTES AWS
# =========================

ec2 = boto3.client("ec2", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)


# =========================
# OBSERVE
# =========================

def get_running_instances():
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
            instances.append({
                "id": instance["InstanceId"],
                "type": instance["InstanceType"],
                "private_ip": instance.get("PrivateIpAddress", "N/A")
            })

    return instances


def get_cpu(instance_id):
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

    datapoints = response["Datapoints"]

    if not datapoints:
        return None

    latest = max(
        datapoints,
        key=lambda x: x["Timestamp"]
    )

    return latest["Average"]


# =========================
# MAIN
# =========================

def main():

    print("=" * 60)
    print("AUTO SCALING CONTROLLER - OBSERVE MODE")
    print("=" * 60)

    instances = get_running_instances()

    print(f"\nRunning instances: {len(instances)}")
    print(f"Allowed capacity: {MIN_INSTANCES}-{MAX_INSTANCES}")

    cpu_values = []

    for instance in instances:

        cpu = get_cpu(instance["id"])

        print("\nInstance:")
        print(f"  ID:         {instance['id']}")
        print(f"  Type:       {instance['type']}")
        print(f"  Private IP: {instance['private_ip']}")

        if cpu is None:
            print("  CPU:        No data")
        else:
            print(f"  CPU:        {cpu:.2f}%")
            cpu_values.append(cpu)

    if cpu_values:

        fleet_cpu = sum(cpu_values) / len(cpu_values)

        print("\n" + "-" * 60)
        print(f"Fleet average CPU: {fleet_cpu:.2f}%")

    else:
        print("\nNo CPU metrics available.")

    print("\nNO SCALING ACTIONS ENABLED")
    print("=" * 60)


if __name__ == "__main__":
    main()
