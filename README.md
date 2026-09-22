# AWS Custom Auto-Scaling Controller

Custom elasticity controller developed in Python for an EC2 web application behind an AWS Application Load Balancer (ALB).

The controller implements the complete **Observe → Analyze → Decide → Act → Verify** loop without using AWS managed dynamic Auto Scaling policies.

## Architecture

The solution uses:

- Application Load Balancer (ALB)
- Target Group
- EC2 web instances
- Independent EC2 controller
- Amazon CloudWatch
- EC2 Launch Template
- Python + boto3
- Cron + `flock`
- Persistent cooldown and JSONL logs

The controller manages EC2 instances using the tags:

- `Project=CustomAutoScaling`
- `ManagedBy=CustomController`

The base instance also has `Protected=true`, preventing it from being removed during scale-in.

## Scaling Policy

Every cycle produces one explicit decision:

- `INCREASE_CAPACITY`
- `REDUCE_CAPACITY`
- `MAINTAIN_CAPACITY`

### Scale-out

One instance is added when:

- Average CPU >= 60%, **OR**
- Maximum individual CPU >= 80%, **OR**
- ALB RequestCount >= 1000

### Scale-in

One instance is removed when:

- Average CPU <= 20%, **AND**
- ALB RequestCount <= 100

### Limits and stability

- Minimum capacity: 1 instance
- Maximum capacity: 5 instances
- Scaling step: 1 instance
- Controller interval: 60 seconds
- Cooldown: 300 seconds
- Connection draining: 30 seconds
- Target health timeout: 300 seconds

`flock` prevents overlapping controller executions.

## Effective Capacity

A new EC2 instance is not considered effective capacity just because it reaches the `running` state.

During scale-out, the controller:

1. Launches the EC2 instance.
2. Waits for the `running` state.
3. Registers it in the Target Group.
4. Waits until the target becomes `healthy`.

Only then is the scaling action considered successfully verified.

## Experimental Validation

The controller was validated with real AWS infrastructure.

### Scale-out

Under high workload, the controller observed:

- Running capacity: 1
- Healthy targets: 1
- RequestCount: 90,652
- Decision: `INCREASE_CAPACITY`
- Target capacity: 2

The new EC2 instance reached `running` in approximately 6.56 seconds and was registered in the Target Group. Final verification confirmed **2 running instances and 2 healthy targets**.

### Scale-in

Under low workload:

- Running capacity: 2
- Healthy targets: 2
- Average CPU: 1.63%
- RequestCount: 0
- Decision: `REDUCE_CAPACITY`

The controller removed the unprotected instance and returned to the minimum capacity of 1. Scale-in completed in **56.2 seconds**.

### Maintain

During cooldown, autonomous executions produced `MAINTAIN_CAPACITY`, preventing repeated scaling actions.

## Autonomous Execution

The controller runs automatically every minute using cron:

```cron
* * * * * cd /home/ssm-user/aws-custom-autoscaling-controller && ./scripts/run_controller.sh >> /home/ssm-user/aws-custom-autoscaling-controller/logs/cron.log 2>&1
```

## Run Manually

Install the dependencies and create the local configuration:

```bash
pip install -r requirements.txt
cp config/config.example.json config/config.json
```

Then run:

```bash
python3 controller/controller.py
```

## Generate Workload

```bash
python3 scripts/generate_load.py \
  --url http://YOUR-ALB-DNS/ \
  --duration 60 \
  --workers 20
```

## Tests

```bash
PYTHONPATH=. python3 -m pytest -q
```

Current result:

```text
10 passed
```

## Repository Structure

```text
app/             Example web application
config/          Configuration template
controller/      Custom elasticity controller
docs/            Architecture and engineering decisions
experiments/     Experimental methodology
infrastructure/  AWS deployment configuration
scripts/         Execution, workload and cleanup utilities
tests/           Scaling policy tests
```

## Logs

Every controller cycle is recorded in:

```text
logs/decisions.jsonl
```

Each record contains the observed metrics, capacity, cooldown state, decision, reason and result of the requested infrastructure action.

## Important

This project does **not** use AWS managed dynamic Auto Scaling policies. Scaling decisions and EC2 capacity changes are performed by the custom Python controller.