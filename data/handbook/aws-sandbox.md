# AWS Sandbox

## What it is
The AWS Sandbox is a separate AWS account for experiments, prototypes and onboarding labs. It holds no customer data and untagged resources are wiped every Sunday. You can spin up test EC2 instances, Lambda functions and S3 buckets here without touching anything customers depend on.

## Owner
Devon Price (Infrastructure) owns the sandbox account and its budget alerts.

## Access levels
- **Read**: view resources, CloudWatch logs and billing in the sandbox console. Good for onboarding labs and following along with a demo.
- **Write**: create, change and delete resources such as EC2 instances, Lambda functions and S3 buckets. Spend is capped per person.
- **Admin**: manage IAM roles, service quotas and account settings for the sandbox. Admin always counts as high risk.

## Risk tier
Low. Backend Engineers get write access by default as part of their role baseline, so they never need to file a request for it.

## Justification expected
A justification is optional for read and write; a short note about the experiment helps the owner keep the budget in check. Admin requests need a full reason, like any high-risk request.
