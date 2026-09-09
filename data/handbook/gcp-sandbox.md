# GCP Sandbox

## What it is
The GCP Sandbox is a Google Cloud project for trying out services, running small prototypes and testing infrastructure changes before they go near production. Nothing in it is backed up and it contains no customer data.

## Owner
Devon Price (Infrastructure) owns the sandbox project.

## Access levels
- **Read**: browse resources, view Cloud Logging and monitoring dashboards.
- **Write**: deploy Cloud Run services, create Compute Engine VMs and buckets, and change resources you created. Write access to the sandbox is meant for prototyping internal tools.
- **Admin**: change IAM policy, enable new APIs and manage project settings. Admin always counts as high risk.

## Risk tier
Low. Backend Engineers get write access by default as part of their role baseline.

## Justification expected
A justification is optional for read and write access. Admin requests need a full reason describing the change you need to make.
