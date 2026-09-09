# Tableau

## What it is
Tableau Server hosts the company's BI dashboards: revenue, retention, support SLAs, API latency and more. Dashboards read from curated Snowflake views, never from raw tables.

## Owner
Lena Fischer (Data Platform) owns Tableau Server and its project structure.

## Access levels
- **Read**: view published dashboards and download images or filtered data. Read cannot edit or publish workbooks.
- **Write**: publish and edit workbooks in projects you have been given, and schedule extract refreshes.
- **Admin**: manage projects, folders, permissions and site settings. Admin always counts as high risk because it controls who sees which dashboards.

## Risk tier
Low. Data Analysts get read access by default as part of their role baseline.

## Justification expected
A justification is optional for read and write access. Admin requests need a full reason explaining what has to be restructured and why.
