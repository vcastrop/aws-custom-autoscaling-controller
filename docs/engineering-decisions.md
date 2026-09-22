# Engineering Decisions

## Metrics

The controller uses three main signals:

- Fleet average CPU
- Maximum individual CPU
- ALB RequestCount

Target health is used to verify effective capacity after an infrastructure change.

## Scaling Policy

Scale-out occurs when:

- Average CPU >= 60%, OR
- Maximum individual CPU >= 80%, OR
- RequestCount >= 1000

Scale-in occurs when:

- Average CPU <= 20%, AND
- RequestCount <= 100

Each successful scaling action changes capacity by one instance.

## Capacity Limits

- Minimum capacity: 1
- Maximum capacity: 5

The base instance is additionally protected using the `Protected=true` tag.

## Controller Interval

The controller runs every 60 seconds.

CPU uses a 300-second CloudWatch metric period, while ALB RequestCount is collected using 60-second buckets across the observation window.

## Cooldown

A 300-second cooldown follows every successful scaling action.

This prevents repeated actions before the effect of the previous capacity change can be observed.

## Connection Draining

Before terminating an instance, the controller deregisters it from the Target Group and waits 30 seconds.

This reduces the risk of terminating an instance while it is still serving requests.

## Effective Capacity

An EC2 instance reaching `running` does not necessarily mean that it can already receive traffic.

For this reason, scale-out verification waits until the new target becomes `healthy` in the Target Group.

Testing showed that an instance could reach `running` in approximately 6.56 seconds while ALB health verification required significantly more time.

The target health timeout was therefore increased from 180 to 300 seconds.

## Availability Zones

During testing, an instance was created in an Availability Zone that was not enabled for the ALB.

AWS reported:

`Target.NotInUse`

The configuration was corrected to use an ALB-enabled subnet.

## RequestCount

Testing also showed that reading only the latest RequestCount datapoint could hide recent traffic when the newest CloudWatch bucket contained zero requests.

The collector was corrected to sum the ALB 60-second RequestCount buckets across the configured observation window.

## Autonomous Execution

Cron executes the controller every minute.

`flock` prevents multiple controller processes from modifying the infrastructure simultaneously.

## IAM

The AWS Academy environment uses `LabRole`.

For a production environment, a dedicated least-privilege IAM role should be used with only the EC2, CloudWatch and ELBv2 permissions required by the controller.