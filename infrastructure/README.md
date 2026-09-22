# AWS Infrastructure

The project uses the following AWS components:

- Application Load Balancer
- Target Group
- EC2 web instances
- EC2 controller instance
- EC2 Launch Template
- Amazon CloudWatch
- IAM role

## Web Tier

Web instances are created from a Launch Template and registered in the ALB Target Group.

Managed instances use:

- `Project=CustomAutoScaling`
- `ManagedBy=CustomController`

The base instance additionally uses:

- `Protected=true`

## Controller

The controller runs independently from the web tier and uses boto3 to interact with EC2, CloudWatch and ELBv2.

The AWS Academy deployment uses `LabRole`.

## Autonomous Execution

Cron executes the controller every minute:

```cron
* * * * * cd /home/ssm-user/aws-custom-autoscaling-controller && ./scripts/run_controller.sh >> /home/ssm-user/aws-custom-autoscaling-controller/logs/cron.log 2>&1
```

`scripts/run_controller.sh` uses `flock` to prevent overlapping executions.

## Network Requirement

Configured subnets must belong to Availability Zones enabled for the Application Load Balancer.

During testing, using a subnet in a non-enabled Availability Zone resulted in:

`Target.NotInUse`

The production configuration was therefore restricted to an ALB-enabled subnet.

## Configuration

Copy:

```bash
cp config/config.example.json config/config.json
```

Then provide the AWS region, Launch Template ID, Target Group ARN, ALB CloudWatch dimension and ALB-enabled subnet.

Runtime configuration is excluded from Git.