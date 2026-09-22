# Elasticity Taxonomy

The custom controller can be classified according to the main dimensions of cloud elasticity.

| Dimension | Classification |
|---|---|
| Scaling direction | Bidirectional |
| Scaling method | Horizontal |
| Resource | EC2 virtual machines |
| Cloud layer | Infrastructure level |
| Application scope | Web tier |
| Trigger | Performance and workload metrics |
| Strategy | Reactive |
| Decision mechanism | Threshold-based |
| Automation | Automatic |
| Control architecture | Centralized |
| Provider | AWS |

## Horizontal and Bidirectional

The controller changes the number of EC2 instances instead of changing the resources of an existing instance.

It supports both directions:

- Scale-out adds an instance.
- Scale-in removes an instance.

## Reactive

The controller reacts to metrics already observed through Amazon CloudWatch.

It does not predict future workload.

## Threshold-Based

Scaling decisions use predefined thresholds for:

- Average CPU
- Maximum individual CPU
- ALB RequestCount

Different scale-out and scale-in thresholds help reduce unnecessary oscillation.

## Automatic

Cron executes the controller automatically every minute without requiring manual intervention.

AWS managed dynamic Auto Scaling policies are not used.

## Centralized

A dedicated EC2 controller observes the complete managed web tier and makes the scaling decision for the system.