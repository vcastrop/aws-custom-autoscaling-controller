# Architecture

The solution implements a centralized custom elasticity controller for an EC2 web tier behind an AWS Application Load Balancer.

## Main Components

- Application Load Balancer (ALB)
- Target Group
- EC2 web instances
- Independent EC2 controller
- Amazon CloudWatch
- EC2 Launch Template
- Python + boto3
- Cron + `flock`

## Control Loop

The controller follows:

**Observe → Analyze → Decide → Act → Verify**

### Observe

The controller collects:

- Running EC2 instances
- Healthy targets
- Fleet average CPU
- Maximum individual CPU
- ALB RequestCount
- Cooldown state

### Decide

Every cycle produces one explicit decision:

- `INCREASE_CAPACITY`
- `REDUCE_CAPACITY`
- `MAINTAIN_CAPACITY`

### Act

For scale-out, the controller:

1. Launches a new EC2 instance from the Launch Template.
2. Waits for the instance to reach `running`.
3. Registers it in the Target Group.
4. Waits until the target becomes `healthy`.

For scale-in, the controller:

1. Selects an unprotected managed instance.
2. Deregisters it from the Target Group.
3. Waits for connection draining.
4. Terminates the instance.

## Availability Protection

The base instance uses:

`Protected=true`

This prevents the controller from selecting it for scale-in.

The policy also enforces:

- Minimum capacity: 1
- Maximum capacity: 5

## Autonomous Execution

Cron executes the controller every 60 seconds.

`scripts/run_controller.sh` uses `flock` to prevent overlapping executions.

## Logging

Each controller cycle is recorded in:

`logs/decisions.jsonl`

The log contains the observed metrics, capacity, decision, reason and action result.