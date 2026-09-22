# Workload Scenario

The workload generator sends concurrent HTTP requests to the Application Load Balancer.

## Command

```bash
python3 scripts/generate_load.py \
  --url http://YOUR-ALB-DNS/ \
  --duration 60 \
  --workers 20
```

## Example Result

A 60-second experiment produced:

- Total requests: 67,761
- Successful requests: 67,761
- Failed requests: 0
- Success rate: 100%
- Average latency: 0.0131 seconds

The workload is intended to increase ALB RequestCount above the scale-out threshold of 1000 requests.

## Expected Controller Behavior

High workload:

`INCREASE_CAPACITY`

Low workload:

`REDUCE_CAPACITY`

Cooldown or intermediate conditions:

`MAINTAIN_CAPACITY`