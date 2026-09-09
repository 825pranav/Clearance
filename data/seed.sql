-- Mock directory, system catalogue and role baselines. All people and emails are fictional.

INSERT INTO employees (email, name, role, department, manager_email) VALUES
  ('morgan.lee@example.com',   'Morgan Lee',    'Engineering Manager', 'Engineering',    NULL),
  ('priya.nair@example.com',   'Priya Nair',    'Engineering Manager', 'Engineering',    'morgan.lee@example.com'),
  ('devon.price@example.com',  'Devon Price',   'Engineering Manager', 'Infrastructure', 'morgan.lee@example.com'),
  ('lena.fischer@example.com', 'Lena Fischer',  'Engineering Manager', 'Data Platform',  'morgan.lee@example.com'),
  ('kai.walker@example.com',   'Kai Walker',    'IT Admin',            'IT',             'morgan.lee@example.com'),
  ('riley.kim@example.com',    'Riley Kim',     'Operations Manager',  'Operations',     'morgan.lee@example.com'),
  ('alex.chen@example.com',    'Alex Chen',     'Backend Engineer',    'Engineering',    'priya.nair@example.com'),
  ('sam.okafor@example.com',   'Sam Okafor',    'Backend Engineer',    'Engineering',    'priya.nair@example.com'),
  ('jordan.reyes@example.com', 'Jordan Reyes',  'Data Analyst',        'Data',           'priya.nair@example.com'),
  ('casey.martin@example.com', 'Casey Martin',  'Sales Ops',           'Sales',          'riley.kim@example.com'),
  ('drew.patel@example.com',   'Drew Patel',    'Support Agent',       'Support',        'riley.kim@example.com'),
  ('avery.santos@example.com', 'Avery Santos',  'Designer',            'Design',         'riley.kim@example.com');

-- Owners are deliberately not the managers of the usual requesters, so high-risk
-- requests end up with two different approvers.
INSERT INTO systems (key, name, aliases, risk_tier, owner_email, handbook_doc) VALUES
  ('aws-sandbox',    'AWS Sandbox',        ARRAY['aws dev', 'aws sandbox account', 'aws test account'],          'low',    'devon.price@example.com',  'aws-sandbox.md'),
  ('gcp-sandbox',    'GCP Sandbox',        ARRAY['gcp dev', 'google cloud sandbox', 'gcp test project'],         'low',    'devon.price@example.com',  'gcp-sandbox.md'),
  ('figma',          'Figma',              ARRAY['figma workspace', 'design files'],                             'low',    'kai.walker@example.com',   'figma.md'),
  ('tableau',        'Tableau',            ARRAY['tableau server', 'bi dashboards', 'the bi tool'],              'low',    'lena.fischer@example.com', 'tableau.md'),
  ('snowflake',      'Snowflake',          ARRAY['the data warehouse', 'warehouse', 'dwh'],                      'medium', 'lena.fischer@example.com', 'snowflake.md'),
  ('salesforce',     'Salesforce',         ARRAY['sfdc', 'the crm'],                                             'medium', 'kai.walker@example.com',   'salesforce.md'),
  ('zendesk',        'Zendesk',            ARRAY['the helpdesk', 'support ticketing'],                           'medium', 'kai.walker@example.com',   'zendesk.md'),
  ('aws-production', 'AWS Production',     ARRAY['aws prod', 'production aws', 'the prod aws account'],          'high',   'devon.price@example.com',  'aws-production.md'),
  ('gcp-production', 'GCP Production',     ARRAY['gcp prod', 'production gcp', 'google cloud prod'],             'high',   'devon.price@example.com',  'gcp-production.md'),
  ('okta-admin',     'Okta Admin Console', ARRAY['okta admin', 'sso admin', 'the identity provider admin'],      'high',   'kai.walker@example.com',   'okta-admin.md');

INSERT INTO role_baseline (role, system_key, access_level) VALUES
  ('Backend Engineer', 'aws-sandbox', 'write'),
  ('Backend Engineer', 'gcp-sandbox', 'write'),
  ('Data Analyst',     'snowflake',   'read'),
  ('Data Analyst',     'tableau',     'read'),
  ('Support Agent',    'zendesk',     'write'),
  ('Designer',         'figma',       'write'),
  ('Sales Ops',        'salesforce',  'write');
