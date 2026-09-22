import time

import boto3


class ScalingActuator:
    """
    Executes real horizontal scaling actions on AWS.

    Scale-out:
        launch -> running -> register -> healthy

    Scale-in:
        select -> deregister -> drain -> terminate -> terminated
    """

    def __init__(self, config):
        self.config = config

        region = config["aws"]["region"]

        self.ec2 = boto3.client("ec2", region_name=region)
        self.elbv2 = boto3.client("elbv2", region_name=region)

        aws_config = config["aws"]

        self.launch_template_id = aws_config["launch_template_id"]
        self.launch_template_version = aws_config[
            "launch_template_version"
        ]
        self.target_group_arn = aws_config["target_group_arn"]
        self.subnet_ids = aws_config["subnet_ids"]

    # ---------------------------------------------------------
    # SCALE OUT
    # ---------------------------------------------------------

    def scale_out(self, current_instances):
        """
        Launch one EC2 instance and verify that it becomes
        healthy in the Target Group.

        Returns a structured action result.
        """

        started_at = time.time()

        subnet_id = self._select_subnet(current_instances)

        try:
            response = self.ec2.run_instances(
                LaunchTemplate={
                    "LaunchTemplateId": self.launch_template_id,
                    "Version": self.launch_template_version,
                },
                SubnetId=subnet_id,
                MinCount=1,
                MaxCount=1,
            )

            instance_id = response["Instances"][0]["InstanceId"]

            # ---------------------------------------------
            # WAIT FOR EC2 RUNNING
            # ---------------------------------------------

            running_waiter = self.ec2.get_waiter(
                "instance_running"
            )

            running_waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={
                    "Delay": 5,
                    "MaxAttempts": 60,
                },
            )

            running_at = time.time()

            # ---------------------------------------------
            # REGISTER TARGET
            # ---------------------------------------------

            self.elbv2.register_targets(
                TargetGroupArn=self.target_group_arn,
                Targets=[
                    {
                        "Id": instance_id,
                    }
                ],
            )

            # ---------------------------------------------
            # VERIFY TARGET HEALTH
            # ---------------------------------------------

            healthy = self._wait_until_target_healthy(
                instance_id
            )

            completed_at = time.time()

            if not healthy:
                return {
                    "success": False,
                    "action": "INCREASE_CAPACITY",
                    "instance_id": instance_id,
                    "message": (
                        "Instance reached running state and was "
                        "registered, but did not become healthy "
                        "before the verification timeout."
                    ),
                    "ec2_running_seconds": round(
                        running_at - started_at,
                        2,
                    ),
                    "effective_capacity_seconds": None,
                }

            return {
                "success": True,
                "action": "INCREASE_CAPACITY",
                "instance_id": instance_id,
                "message": (
                    "Instance launched, registered and verified "
                    "healthy in the Target Group."
                ),
                "ec2_running_seconds": round(
                    running_at - started_at,
                    2,
                ),
                "effective_capacity_seconds": round(
                    completed_at - started_at,
                    2,
                ),
            }

        except Exception as exc:
            return {
                "success": False,
                "action": "INCREASE_CAPACITY",
                "instance_id": None,
                "message": str(exc),
                "ec2_running_seconds": None,
                "effective_capacity_seconds": None,
            }

    # ---------------------------------------------------------
    # SCALE IN
    # ---------------------------------------------------------

    def scale_in(self, current_instances):
        """
        Remove the newest unprotected instance.

        The protected base instance is never selected.
        """

        started_at = time.time()

        candidate = self._select_scale_in_candidate(
            current_instances
        )

        if candidate is None:
            return {
                "success": False,
                "action": "REDUCE_CAPACITY",
                "instance_id": None,
                "message": (
                    "No unprotected instance is available "
                    "for safe scale-in."
                ),
                "completion_seconds": None,
            }

        instance_id = candidate["instance_id"]

        try:
            # ---------------------------------------------
            # DEREGISTER
            # ---------------------------------------------

            self.elbv2.deregister_targets(
                TargetGroupArn=self.target_group_arn,
                Targets=[
                    {
                        "Id": instance_id,
                    }
                ],
            )

            # ---------------------------------------------
            # CONNECTION DRAINING
            # ---------------------------------------------

            draining_seconds = self.config["timing"][
                "connection_draining_seconds"
            ]

            time.sleep(draining_seconds)

            # ---------------------------------------------
            # TERMINATE
            # ---------------------------------------------

            self.ec2.terminate_instances(
                InstanceIds=[instance_id]
            )

            terminated_waiter = self.ec2.get_waiter(
                "instance_terminated"
            )

            terminated_waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={
                    "Delay": 5,
                    "MaxAttempts": 60,
                },
            )

            completed_at = time.time()

            return {
                "success": True,
                "action": "REDUCE_CAPACITY",
                "instance_id": instance_id,
                "message": (
                    "Instance deregistered, drained and terminated."
                ),
                "completion_seconds": round(
                    completed_at - started_at,
                    2,
                ),
            }

        except Exception as exc:
            return {
                "success": False,
                "action": "REDUCE_CAPACITY",
                "instance_id": instance_id,
                "message": str(exc),
                "completion_seconds": None,
            }

    # ---------------------------------------------------------
    # TARGET HEALTH VERIFICATION
    # ---------------------------------------------------------

    def _wait_until_target_healthy(self, instance_id):
        timeout = self.config["timing"][
            "target_health_timeout_seconds"
        ]

        poll_interval = 5
        deadline = time.time() + timeout

        while time.time() < deadline:

            response = self.elbv2.describe_target_health(
                TargetGroupArn=self.target_group_arn,
                Targets=[
                    {
                        "Id": instance_id,
                    }
                ],
            )

            descriptions = response.get(
                "TargetHealthDescriptions",
                []
            )

            if descriptions:
                state = descriptions[0][
                    "TargetHealth"
                ]["State"]

                if state == "healthy":
                    return True

            time.sleep(poll_interval)

        return False

    # ---------------------------------------------------------
    # INSTANCE SELECTION
    # ---------------------------------------------------------

    def _select_scale_in_candidate(self, instances):
        """
        Select newest unprotected instance.
        """

        candidates = [
            instance
            for instance in instances
            if not instance["protected"]
        ]

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda instance: instance["launch_time"],
        )

    def _select_subnet(self, instances):
        """
        Distribute newly created instances across configured subnets.
        """

        if not self.subnet_ids:
            raise ValueError(
                "At least one subnet must be configured."
            )

        index = len(instances) % len(self.subnet_ids)

        return self.subnet_ids[index]