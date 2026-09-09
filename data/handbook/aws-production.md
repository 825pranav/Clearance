# AWS Production

## What it is
AWS Production is the account that runs every customer-facing service: the API, checkout, background workers and the production databases. Mistakes here cause outages or data exposure.

## Owner
Devon Price (Infrastructure) owns the production account and its IAM setup.

## Access levels
- **Read**: view the console, CloudWatch logs, metrics and resource configuration. Enough for debugging incidents.
- **Write**: deploy, change and restart services and infrastructure.
- **Admin**: manage IAM, organisation settings, billing and security tooling.

## Risk tier
High, at every access level.

## Approval process
Production requests need two approvals: the requester's manager and the system owner. Both must approve before access is provisioned, and neither can be skipped, even during an incident. If the requester is the owner, the owner's manager approves instead.

## Justification expected
A justification of at least eight words is required, naming the service, incident or project and why the access level you asked for is the lowest one that works.
