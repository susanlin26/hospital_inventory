CREATE TABLE IF NOT EXISTS schema_version(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_version(version) VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS hospitals(code text PRIMARY KEY,name text NOT NULL,active boolean NOT NULL DEFAULT true);
CREATE TABLE IF NOT EXISTS users(id bigserial PRIMARY KEY,username text UNIQUE NOT NULL,name text NOT NULL,password_hash text NOT NULL,role text NOT NULL CHECK(role IN ('admin','manager','accountant','viewer')),active boolean NOT NULL DEFAULT true,can_activate boolean NOT NULL DEFAULT false,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS grants(user_id bigint REFERENCES users(id),hospital text REFERENCES hospitals(code),PRIMARY KEY(user_id,hospital));
CREATE TABLE IF NOT EXISTS sessions(token_hash text PRIMARY KEY,user_id bigint REFERENCES users(id),csrf text NOT NULL,expires timestamptz NOT NULL,last_seen timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS login_attempts(id bigserial PRIMARY KEY,identity text NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS files(id uuid PRIMARY KEY,filename text NOT NULL,sha256 text NOT NULL,content bytea NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS category_versions(id bigserial PRIMARY KEY,file_id uuid REFERENCES files(id),items jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS import_jobs(id bigserial PRIMARY KEY,hospital text REFERENCES hospitals(code),period text NOT NULL,file_id uuid REFERENCES files(id),category_version bigint REFERENCES category_versions(id),operator bigint REFERENCES users(id),status text NOT NULL DEFAULT 'queued',progress integer NOT NULL DEFAULT 0,result jsonb NOT NULL DEFAULT '{}',created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS batches(id bigserial PRIMARY KEY,hospital text REFERENCES hospitals(code),period text NOT NULL,category text NOT NULL DEFAULT 'MATERIAL',version integer NOT NULL,status text NOT NULL,active boolean NOT NULL DEFAULT false,file_id uuid REFERENCES files(id),file_hash text NOT NULL,category_version bigint REFERENCES category_versions(id),parser_version text NOT NULL,report jsonb NOT NULL,operator bigint REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(hospital,period,category,version),UNIQUE(hospital,period,category,file_hash));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_batch ON batches(hospital,period,category) WHERE active;
CREATE TABLE IF NOT EXISTS lines(batch_id bigint REFERENCES batches(id),row_no integer NOT NULL,body jsonb NOT NULL,PRIMARY KEY(batch_id,row_no));
CREATE TABLE IF NOT EXISTS period_closes(hospital text REFERENCES hospitals(code),period text NOT NULL,closed boolean NOT NULL DEFAULT false,reason text NOT NULL,updated_by bigint REFERENCES users(id),updated_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(hospital,period));
CREATE TABLE IF NOT EXISTS beds(hospital text REFERENCES hospitals(code),period text NOT NULL,value numeric(18,6) CHECK(value>0),source text NOT NULL,updated_by bigint REFERENCES users(id),updated_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(hospital,period));
CREATE TABLE IF NOT EXISTS reviews(id bigserial PRIMARY KEY,hospital text REFERENCES hospitals(code),period text NOT NULL,code text NOT NULL,rule text NOT NULL,status text NOT NULL DEFAULT '待確認' CHECK(status IN ('待確認','追蹤中','已結案')),confirmed boolean NOT NULL DEFAULT false,cause text NOT NULL DEFAULT '',measure text NOT NULL DEFAULT '',owner text NOT NULL DEFAULT '',due_date date,note text NOT NULL DEFAULT '',approved boolean NOT NULL DEFAULT false,revision integer NOT NULL DEFAULT 1,updated_by bigint REFERENCES users(id),updated_at timestamptz NOT NULL DEFAULT now(),UNIQUE(hospital,period,code,rule));
CREATE TABLE IF NOT EXISTS rule_versions(id bigserial PRIMARY KEY,hospital text REFERENCES hospitals(code),body jsonb NOT NULL,operator bigint REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS ai_summaries(id bigserial PRIMARY KEY,hospital text REFERENCES hospitals(code),period text NOT NULL,fingerprint text NOT NULL,model text NOT NULL,prompt_version text NOT NULL,input jsonb NOT NULL,output text NOT NULL,status text NOT NULL,error text,approved boolean NOT NULL DEFAULT false,operator bigint REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS audit(id bigserial PRIMARY KEY,user_id bigint REFERENCES users(id),action text NOT NULL,hospital text,target text,detail jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS backups(id bigserial PRIMARY KEY,path text NOT NULL,sha256 text NOT NULL,status text NOT NULL,note text NOT NULL,created_at timestamptz NOT NULL DEFAULT now());

-- v0.3.0: logical deletion preserves source evidence; reimport creates a new version.
ALTER TABLE batches ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE batches DROP CONSTRAINT IF EXISTS batches_hospital_period_category_file_hash_key;
CREATE TABLE IF NOT EXISTS bed_departments(hospital text REFERENCES hospitals(code),period text NOT NULL,department text NOT NULL,value numeric(18,6) CHECK(value>0),source text NOT NULL,updated_by bigint REFERENCES users(id),updated_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(hospital,period,department));
INSERT INTO bed_departments(hospital,period,department,value,source,updated_by,updated_at) SELECT hospital,period,'RCW',value,source,updated_by,updated_at FROM beds ON CONFLICT DO NOTHING;
INSERT INTO schema_version(version) VALUES(2) ON CONFLICT DO NOTHING;

-- Same source with a new classification snapshot is a new reviewable version.
DROP INDEX IF EXISTS live_batch_hash;

INSERT INTO schema_version(version) VALUES(3) ON CONFLICT DO NOTHING;

-- v0.3.3: every admitted replacement gets its own version, including failed jobs.
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS import_version integer;
DROP INDEX IF EXISTS live_batch_hash_master;
CREATE TABLE IF NOT EXISTS workflow_migrations(key text PRIMARY KEY,applied_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_version(version) VALUES(4) ON CONFLICT DO NOTHING;

-- v0.4.0: scoped comparability approval and immutable closed-period rule references.
CREATE TABLE IF NOT EXISTS factor_confirmations(hospital text REFERENCES hospitals(code),period text NOT NULL,code text NOT NULL,fingerprint text NOT NULL,reason text NOT NULL,operator bigint REFERENCES users(id),updated_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(hospital,period,code));
CREATE TABLE IF NOT EXISTS closed_rule_versions(hospital text REFERENCES hospitals(code),period text NOT NULL,rule_id bigint REFERENCES rule_versions(id),PRIMARY KEY(hospital,period));
INSERT INTO closed_rule_versions(hospital,period,rule_id) SELECT p.hospital,p.period,(SELECT id FROM rule_versions r WHERE r.hospital=p.hospital ORDER BY id DESC LIMIT 1) FROM period_closes p WHERE p.closed ON CONFLICT DO NOTHING;
INSERT INTO schema_version(version) VALUES(5) ON CONFLICT DO NOTHING;

-- v0.5.0: additive migration; original averages, sources and review records are retained.
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM schema_version WHERE version=6) THEN
  ALTER TABLE reviews ADD COLUMN IF NOT EXISTS details jsonb NOT NULL DEFAULT '{}';
  ALTER TABLE beds ALTER COLUMN value TYPE numeric;
  ALTER TABLE bed_departments ALTER COLUMN value TYPE numeric;
  INSERT INTO schema_version(version) VALUES(6);
 END IF;
END $$;

-- v0.5.2: independent hospital/month/department activation and review records.
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM schema_version WHERE version=7) THEN
  ALTER TABLE batches ADD COLUMN department text NOT NULL DEFAULT '';
  ALTER TABLE reviews ADD COLUMN department text NOT NULL DEFAULT '';
  DROP INDEX one_active_batch;
  CREATE UNIQUE INDEX one_active_batch ON batches(hospital,period,category,department) WHERE active;
  ALTER TABLE reviews DROP CONSTRAINT reviews_hospital_period_code_rule_key;
  ALTER TABLE reviews ADD CONSTRAINT reviews_scope_key UNIQUE(hospital,period,department,code,rule);
  ALTER TABLE factor_confirmations ADD COLUMN department text NOT NULL DEFAULT '';
  ALTER TABLE factor_confirmations DROP CONSTRAINT factor_confirmations_pkey;
  ALTER TABLE factor_confirmations ADD PRIMARY KEY(hospital,period,department,code);
  INSERT INTO schema_version(version) VALUES(7);
 END IF;
END $$;

-- v0.6.0: additive status support; historical state values and audit remain intact.
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_status_check;
ALTER TABLE reviews ADD CONSTRAINT reviews_status_check CHECK(status IN ('待確認','追蹤中','改善中','待驗證','已結案'));
INSERT INTO schema_version(version) VALUES(8) ON CONFLICT DO NOTHING;
-- v0.8.0 additive tracking: source data and legacy reviews are retained.
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
CREATE TABLE IF NOT EXISTS tracking_observations(
 id bigserial PRIMARY KEY,hospital text NOT NULL REFERENCES hospitals(code),period text NOT NULL,scope text NOT NULL,
 identity text NOT NULL,rule text NOT NULL,basis text NOT NULL,category text NOT NULL,level text NOT NULL,
 snapshot jsonb NOT NULL,fingerprint text NOT NULL,active boolean NOT NULL DEFAULT true,
 confirmation jsonb,confirmed_fingerprint text,case_id bigint,link_origin text,link_suppressed boolean NOT NULL DEFAULT false,
 revision integer NOT NULL DEFAULT 1,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(hospital,period,scope,identity,rule,basis));
CREATE TABLE IF NOT EXISTS tracking_cases(
 id bigserial PRIMARY KEY,hospital text NOT NULL REFERENCES hospitals(code),start_period text NOT NULL,
 title text NOT NULL,status text NOT NULL CHECK(status IN ('改善中','待驗證','改善完成','舊版待確認','舊版結案待分類','合理原因結案')),
 body jsonb NOT NULL DEFAULT '{}',legacy_id bigint UNIQUE REFERENCES reviews(id),revision integer NOT NULL DEFAULT 1,
 updated_by bigint REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS tracking_events(
 id bigserial PRIMARY KEY,hospital text NOT NULL REFERENCES hospitals(code),observation_id bigint REFERENCES tracking_observations(id),
 case_id bigint REFERENCES tracking_cases(id),action text NOT NULL,body jsonb NOT NULL,operator bigint REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS tracking_batches(id bigserial PRIMARY KEY,hospital text NOT NULL REFERENCES hospitals(code),body jsonb NOT NULL,operator bigint REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS tracking_scope ON tracking_observations(hospital,period,scope,basis);
CREATE INDEX IF NOT EXISTS tracking_case_link ON tracking_observations(case_id);
CREATE INDEX IF NOT EXISTS tracking_event_case ON tracking_events(case_id,id);
CREATE INDEX IF NOT EXISTS tracking_event_observation ON tracking_events(observation_id,id);
INSERT INTO schema_version(version) VALUES(9) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS tracking_scans(hospital text NOT NULL,period text NOT NULL,scope text NOT NULL,basis text NOT NULL,PRIMARY KEY(hospital,period,scope,basis));

-- v0.8.1 explicit cross-hospital product correspondence; source/import data unchanged.
CREATE TABLE IF NOT EXISTS cross_item_groups(id bigserial PRIMARY KEY,name text NOT NULL,specification text NOT NULL,note text NOT NULL,active boolean NOT NULL DEFAULT true,confirmed_by bigint REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS cross_item_members(id bigserial PRIMARY KEY,group_id bigint NOT NULL REFERENCES cross_item_groups(id),hospital text NOT NULL REFERENCES hospitals(code),identity text NOT NULL,body jsonb NOT NULL,active boolean NOT NULL DEFAULT true);
CREATE UNIQUE INDEX IF NOT EXISTS cross_item_active_member ON cross_item_members(hospital,identity) WHERE active;
INSERT INTO schema_version(version) VALUES(10) ON CONFLICT DO NOTHING;

-- v0.8.2: transaction-safe cache invalidation; no financial/history rows changed.
CREATE TABLE IF NOT EXISTS performance_state(key text PRIMARY KEY,token text NOT NULL);
INSERT INTO performance_state VALUES('financial',gen_random_uuid()::text) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS tracking_work_state(hospital text NOT NULL,period text NOT NULL,scope text NOT NULL,basis text NOT NULL,source_token text,tracking_token text,scan_state text NOT NULL DEFAULT 'done',last_error text,PRIMARY KEY(hospital,period,scope,basis));
CREATE INDEX IF NOT EXISTS tracking_link_source ON tracking_observations(hospital,scope,identity,rule,basis,period) WHERE case_id IS NOT NULL;
CREATE OR REPLACE FUNCTION invalidate_financial_cache() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM changed_rows) THEN
  UPDATE performance_state SET token=gen_random_uuid()::text WHERE key='financial';
 END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION invalidate_tracking_cache() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE h text;
BEGIN
 FOR h IN SELECT DISTINCT hospital FROM changed_rows LOOP
  INSERT INTO performance_state VALUES('tracking:'||h,gen_random_uuid()::text)
  ON CONFLICT(key) DO UPDATE SET token=excluded.token;
 END LOOP;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION invalidate_truncated_cache() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE performance_state SET token=gen_random_uuid()::text WHERE key='financial';RETURN NULL;
END $$;
DO $$ DECLARE t text;op text;ref text;fn text;BEGIN
 FOREACH t IN ARRAY ARRAY['batches','lines','files','category_versions','beds','bed_departments','rule_versions','closed_rule_versions','period_closes','factor_confirmations','reviews','hospitals','tracking_cases','tracking_observations'] LOOP
  fn:=CASE WHEN t IN ('tracking_cases','tracking_observations') THEN 'invalidate_tracking_cache' ELSE 'invalidate_financial_cache' END;
  FOREACH op IN ARRAY ARRAY['INSERT','UPDATE','DELETE'] LOOP
   ref:=CASE WHEN op='DELETE' THEN 'OLD' ELSE 'NEW' END;
   IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=t::regclass AND tgname='performance_'||lower(op)) THEN
    EXECUTE format('CREATE TRIGGER %I AFTER %s ON %I REFERENCING %s TABLE AS changed_rows FOR EACH STATEMENT EXECUTE FUNCTION %I()', 'performance_'||lower(op),op,t,ref,fn);
   END IF;
  END LOOP;
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=t::regclass AND tgname='performance_truncate') THEN
   EXECUTE format('CREATE TRIGGER performance_truncate AFTER TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION invalidate_truncated_cache()',t);
  END IF;
 END LOOP;
END $$;
INSERT INTO schema_version(version) VALUES(11) ON CONFLICT DO NOTHING;

-- v0.9.0 non-destructive monthly workflow and rule lifecycle.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK(role IN ('admin','manager','accountant','frontline','viewer'));
ALTER TABLE rule_versions ADD COLUMN IF NOT EXISTS disabled_at timestamptz;
CREATE TABLE IF NOT EXISTS monthly_cases(id bigserial PRIMARY KEY,hospital text NOT NULL REFERENCES hospitals(code),period text NOT NULL,kind text NOT NULL CHECK(kind IN ('usage','high','low','idle')),body jsonb NOT NULL DEFAULT '{}',revision integer NOT NULL DEFAULT 1,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),UNIQUE(hospital,period,kind));
CREATE INDEX IF NOT EXISTS monthly_cases_scope ON monthly_cases(hospital,period);
INSERT INTO schema_version(version) VALUES(12) ON CONFLICT DO NOTHING;

-- v0.9.8: historical averages remain averages; only explicit patient-day input is eligible.
ALTER TABLE bed_departments ADD COLUMN IF NOT EXISTS measurement text NOT NULL DEFAULT 'average_beds';

-- v0.9.9：保留原資料，增列採購單價提醒種類。
ALTER TABLE monthly_cases DROP CONSTRAINT IF EXISTS monthly_cases_kind_check;
ALTER TABLE monthly_cases ADD CONSTRAINT monthly_cases_kind_check CHECK(kind IN ('usage','purchase','high','low','idle'));

INSERT INTO schema_version(version) VALUES(13) ON CONFLICT DO NOTHING;

-- v0.9.9.2: source-version synchronization; original monthly cases stay intact.
CREATE TABLE IF NOT EXISTS monthly_sync_state(
 hospital text NOT NULL REFERENCES hospitals(code),period text NOT NULL,basis text NOT NULL,
 source_token text NOT NULL,existing_only boolean NOT NULL DEFAULT false,
 PRIMARY KEY(hospital,period,basis));
INSERT INTO schema_version(version) VALUES(14) ON CONFLICT DO NOTHING;

-- v0.10.1: temporary-password gate; existing users retain their login behavior.
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false;
INSERT INTO schema_version(version) VALUES(15) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS tracking_exclusions(id bigserial PRIMARY KEY,hospital text NOT NULL REFERENCES hospitals(code),code text NOT NULL,name text NOT NULL,unit text NOT NULL,reason text NOT NULL,operator bigint REFERENCES users(id),excluded_at timestamptz NOT NULL DEFAULT now(),active boolean NOT NULL DEFAULT true,UNIQUE(hospital,code,name,unit));

CREATE TABLE IF NOT EXISTS deployment_state(key text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO deployment_state(key) SELECT 'bootstrap_complete' WHERE EXISTS(SELECT 1 FROM users) ON CONFLICT DO NOTHING;
