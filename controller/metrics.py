from datetime import datetime, timedelta, timezone

import boto3


class MetricsCollector:
    """
    Collect all AWS observations required by the custom
    auto-scaling controller.

    Decision metrics:
    - Average fleet CPU
    - Maximum individual CPU
    - ALB RequestCount

    Target health is used to verify effective capacity,
    not as a scaling decision metric.
    """

    def __init__(self, config):
        self.config = config

        region = config["aws"]["region"]

        self.ec2 = boto3.client("ec2", region_name=region)
        self.cloudwatch = boto3.client("cloudwatch", region_name=region)
        self.elbv2 = boto3.client("elbv2", region_name=region)

        self.target_group_arn = config["aws"]["target_group_arn"]
        self.alb_dimension = config["aws"]["alb_dimension"]

    # ---------------------------------------------------------
    # EC2 INSTANCES
    # ---------------------------------------------------------

    def get_running_instances(self):
        """
        Return running EC2 instances managed by the controller.
        """

        filters = [
            {
                "Name": "instance-state-name",
                "Values": ["running"],
            }
        ]

        for key, value in self.config["tags"].items():
            filters.append(
                {
                    "Name": f"tag:{key}",
                    "Values": [value],
                }
            )

        response = self.ec2.describe_instances(Filters=filters)

        instances = []

        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:

                tags = {
                    tag["Key"]: tag["Value"]
                    for tag in instance.get("Tags", [])
                }

                protected = (
                    tags.get("Protected", "false").lower() == "true"
                )

                instances.append(
                    {
                        "instance_id": instance["InstanceId"],
                        "launch_time": instance["LaunchTime"],
                        "protected": protected,
                    }
                )

        instances.sort(
            key=lambda instance: instance["launch_time"]
        )

        return instances

    # ---------------------------------------------------------
    # CLOUDWATCH
    # ---------------------------------------------------------

    def _latest_metric(
        self,
        namespace,
        metric_name,
        dimensions,
        statistic,
    ):
        """
        Return the most recent CloudWatch datapoint.
        """

        lookback = self.config["timing"]["metric_lookback_seconds"]
        period = self.config["timing"]["metric_period_seconds"]

        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=lookback)

        response = self.cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start,
            EndTime=end,
            Period=period,
            Statistics=[statistic],
        )

        datapoints = response.get("Datapoints", [])

        if not datapoints:
            return None

        latest = max(
            datapoints,
            key=lambda datapoint: datapoint["Timestamp"],
        )

        return float(latest[statistic])

    # ---------------------------------------------------------
    # CPU
    # ---------------------------------------------------------

    def get_instance_cpu(self, instance_id):
        """
        Return the latest average CPU utilization for one instance.
        """

        return self._latest_metric(
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            dimensions=[
                {
                    "Name": "InstanceId",
                    "Value": instance_id,
                }
            ],
            statistic="Average",
        )

    def get_fleet_cpu(self, instances):
        """
        Calculate average and maximum CPU utilization
        across the running fleet.
        """

        per_instance = {}

        for instance in instances:
            instance_id = instance["instance_id"]

            cpu = self.get_instance_cpu(instance_id)

            if cpu is not None:
                per_instance[instance_id] = cpu

        if not per_instance:
            return {
                "per_instance": {},
                "average": None,
                "maximum": None,
            }

        values = list(per_instance.values())

        average = sum(values) / len(values)
        maximum = max(values)

        return {
            "per_instance": per_instance,
            "average": average,
            "maximum": maximum,
        }

    # ---------------------------------------------------------
    # REQUEST COUNT
    # ---------------------------------------------------------

    def get_request_count(self):
        """
        Return the total ALB RequestCount observed during the
        configured lookback window.

        ALB RequestCount is published at 60-second granularity.
        All 60-second buckets inside the observation window are
        summed so that a recent zero bucket does not hide traffic
        observed earlier in the window.
        """

        lookback = self.config["timing"]["metric_lookback_seconds"]

        # Application Load Balancer metrics are available at
        # 60-second granularity.
        period = 60

        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=lookback)

        response = self.cloudwatch.get_metric_statistics(
            Namespace="AWS/ApplicationELB",
            MetricName="RequestCount",
            Dimensions=[
                {
                    "Name": "LoadBalancer",
                    "Value": self.alb_dimension,
                }
            ],
            StartTime=start,
            EndTime=end,
            Period=period,
            Statistics=["Sum"],
        )

        datapoints = response.get("Datapoints", [])

        if not datapoints:
            return None

        return float(
            sum(
                datapoint["Sum"]
                for datapoint in datapoints
            )
        )

    # ---------------------------------------------------------
    # TARGET HEALTH
    # ---------------------------------------------------------

    def get_target_health(self):
        """
        Target health is used for action verification.
        It is NOT used as a workload scaling metric.
        """

        response = self.elbv2.describe_target_health(
            TargetGroupArn=self.target_group_arn
        )

        targets = []

        for description in response["TargetHealthDescriptions"]:

            targets.append(
                {
                    "instance_id": description["Target"]["Id"],
                    "state": description["TargetHealth"]["State"],
                }
            )

        return targets

    # ---------------------------------------------------------
    # COMPLETE OBSERVATION
    # ---------------------------------------------------------

    def collect(self):
        """
        Collect one complete observation for the controller.
        """

        timestamp = datetime.now(timezone.utc).isoformat()

        instances = self.get_running_instances()

        cpu = self.get_fleet_cpu(instances)

        request_count = self.get_request_count()

        targets = self.get_target_health()

        healthy_targets = sum(
            1
            for target in targets
            if target["state"] == "healthy"
        )

        return {
            "timestamp": timestamp,
            "capacity": {
                "running": len(instances),
                "healthy": healthy_targets,
            },
            "instances": instances,
            "metrics": {
                "cpu": cpu,
                "request_count": request_count,
            },
            "targets": targets,
        }