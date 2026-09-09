# Access Request Process

## How to request access
Ask the access bot in Slack in plain English: name the system, the access level you need (read, write or admin) and why you need it. The bot files a GitLab issue from the standard template and routes it to the right approvers. The bot never grants access itself.

## Risk tiers
Every system has a risk tier: low, medium or high. Any admin request counts as high risk, whatever the system's usual tier.

## Who approves
- Low and medium risk: the requester's manager.
- High risk: the requester's manager and the system owner. That is two approvals, and both are required.
- Nobody approves their own request. If you own the system, your own manager approves in place of the owner.

## Justifications
Low-risk requests can skip the justification. Medium and high-risk requests need a justification of at least eight words, written by the requester. Nobody else can supply it for you.

## What happens after you submit
The issue starts as pending. Approvers add an approval label on the issue; when every required approval is in, the request is approved and the system owner provisions access. A rejected label closes the request. The bot messages you whenever the status changes. Most requests are approved within one working day; high-risk ones can take two.

## Requests for other people
Each person requests their own access, because the justification and the accountability belong to the person who will use it. Managers cannot file on behalf of their reports.
