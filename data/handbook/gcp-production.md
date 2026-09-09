# GCP Production

## What it is
GCP Production is the Google Cloud project that runs the notification workers, search cluster and data pipelines that customers depend on.

## Owner
Devon Price (Infrastructure) owns the production project.

## Access levels
- **Read**: view resources, Cloud Logging and monitoring. Read cannot change anything.
- **Write**: deploy services, change workloads and resize clusters.
- **Admin**: manage IAM policy, service accounts and their keys, and project-wide settings. Admin is the only level that can rotate service account keys.

## Risk tier
High, at every access level.

## Justification expected
A justification of at least eight words is required. It should name the workload or migration and explain why read access is not enough when asking for write or admin.
