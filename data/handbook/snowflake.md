# Snowflake

## What it is
Snowflake is the company data warehouse. It holds product events, billing records, CRM exports and support data. Some schemas contain customer personal data (PII) such as names and email addresses; those schemas are masked for read-only roles.

## Owner
Lena Fischer (Data Platform) owns Snowflake, its warehouses and its role hierarchy.

## Access levels
- **Read**: run queries against the analytics schemas through masked views. Enough for dashboards, reports and ad hoc analysis.
- **Write**: create and load tables in your team's staging schema, for example to build models or backfill data.
- **Admin**: manage warehouses, sizing, roles and grants. Admin always counts as high risk.

## Risk tier
Medium, because the warehouse contains customer and financial data. Data Analysts get read access by default as part of their role baseline.

## Justification expected
Every Snowflake request needs a justification of at least eight words that names the dataset or project and what you will do with it. "For analysis" is not enough; "to build the weekly churn report for the finance team" is.
