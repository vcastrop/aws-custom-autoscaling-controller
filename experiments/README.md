# Experimental Results

The controller was validated using real AWS infrastructure and workloads generated against the Application Load Balancer.

## Scale-out

High traffic produced a controller observation of:

- Running capacity: 1
- Healthy targets: 1
- RequestCount: 90,652
- Decision: `INCREASE_CAPACITY`
- Target capacity: 2

The new EC2 instance reached the `running` state in approximately 6.56 seconds. Final verification confirmed:

- Running instances: 2
- Healthy targets: 2

## Scale-in

With low workload:

- Running capacity: 2
- Healthy targets: 2
- Average CPU: 1.63%
- Maximum CPU: 1.80%
- RequestCount: 0

The controller selected `REDUCE_CAPACITY` and removed the unprotected instance.

Scale-in completion time: **56.2 seconds**.

## Maintain

During the 300-second cooldown, autonomous controller cycles selected:

`MAINTAIN_CAPACITY`

This prevented repeated scaling actions while the previous infrastructure change stabilized.

## Findings

Testing demonstrated that:

- EC2 `running` does not necessarily mean effective capacity.
- Target Group health must be verified after scale-out.
- ALB-enabled Availability Zones must be respected.
- CloudWatch RequestCount must be evaluated across the observation window.
- Cooldown is necessary to prevent repeated scaling actions.