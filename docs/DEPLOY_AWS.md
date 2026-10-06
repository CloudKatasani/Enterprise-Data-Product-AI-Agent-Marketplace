# Hosting the marketplace on AWS — step by step

This is the executable companion to [`build-spec/05-cloud-aws.md`](build-spec/05-cloud-aws.md).
That document is the reference architecture; this one is the ordered list of things to type to get
the repository running in an AWS account, written against what the code actually does today.

Region used throughout: **`us-east-2`** (Ohio). Change `AWS_REGION` once and every command follows.

---

## 0. Read this first — what the review found

These facts come from reading the code, not the spec. Each one changes a deployment step.

| # | Finding | Where | What it means for hosting |
|---|---|---|---|
| F1 | **No infrastructure code exists**, and until this guide there was no Dockerfile — `docker-compose.yml` only runs Postgres and Redis for local development. | repo root | `Dockerfile.backend`, `Dockerfile.portal` and `.dockerignore` are now at the repository root (step 2); steps 3–10 build the infrastructure with the AWS CLI. |
| F2 | **There is no working production sign-in yet.** The portal only ever sends `X-Marketplace-Subject: $PORTAL_DEV_SUBJECT`. The API honours that header *only* when `OIDC_ISSUER` contains a local marker (`localhost`, `.local`, `.invalid`, `oidc.local`). Pointed at a real IdP, the API ignores the header and expects a bearer token the portal never sends — and it verifies that token with `OIDC_CLIENT_SECRET` as an HS256 key, which no RS256/JWKS identity provider (Cognito, Entra, Okta) produces. | `portal/lib/api.ts`, `services/api/auth.py` | Keep `OIDC_ISSUER` at a local-marker value and put **authentication in front of the whole site at the load balancer** (Cognito on the ALB, step 9). Every signed-in person then acts as the one seeded party in `PORTAL_DEV_SUBJECT`. That is a governed **pilot/demo**, not multi-user production — see §13. |
| F3 | **Redis is never used.** `REDIS_URL` is validated as present, but nothing connects to it. | `services/common/config.py` | ElastiCache is optional. Set `REDIS_URL` to any well-formed value, or provision a `cache.t4g.micro` if you want it ready for later. |
| F4 | **The `cortex` runtime is Snowflake Cortex Agents, not Amazon Bedrock.** The default `analytic` runtime makes no model call at all. | `services/agent_runtime/cortex.py` | **No Bedrock access is needed.** `snowflake-connector-python` is *not* in `pyproject.toml`; add it to the image only when you connect a real Snowflake account (build arg in step 2). |
| F5 | The first migration runs `CREATE EXTENSION vector` and `CREATE EXTENSION pg_trgm`. | `generated/ddl/0001_bootstrap.sql` | Use **RDS for PostgreSQL 16** (or Aurora PostgreSQL 16) — both ship `pgvector` and `pg_trgm`. The RDS master user (`rds_superuser`) is allowed to create both. |
| F6 | Two database URLs, on purpose. `npm run migrate` creates the `APP_DATABASE_URL` login and forces it to `NOSUPERUSER NOBYPASSRLS`. Every process validates that **both** variables are present. | `scripts/migrate.py`, `services/common/config.py` | Put both URLs in Secrets Manager. `DATABASE_URL` = RDS master user (schema owner); `APP_DATABASE_URL` = a separate login that migrate creates for you. **Never point both at the master user** — row-level security silently switches off. |
| F7 | `generated/` is committed and must never be regenerated at deploy time. | README rule, CI `gen-diff` | The image copies `generated/` as is. CI already proves it is current. |
| F8 | The portal is a normal `next build` / `next start` (no `output: 'standalone'`). It renders every page at request time and reads all configuration from the process environment. | `portal/next.config.ts` | One portal image works for every environment; config is injected by ECS. *Verified:* `npm run build --workspace portal` succeeds with no API reachable. |
| F9 | The browser never calls the API directly — server components and the `/api/events` route call `API_BASE_URL`. | `portal/lib/api.ts`, `portal/app/api/events/route.ts` | The API needs **no public listener**. Only the portal is behind the ALB. |
| F10 | `/api/events` is a long-lived stream; the ALB default idle timeout is 60 s. | portal route | Raise the ALB idle timeout (step 8). |
| F11 | `observe` and `mesh` report findings **through their exit code**. | `scripts/observe.py`, `scripts/mesh.py` | A failed scheduled job is a finding, not noise. Step 11 alarms on every non-zero exit. |

---

## 1. Target architecture

```
                    Internet
                       │  HTTPS 443
                ┌──────▼──────────────────────────┐
                │ Application Load Balancer        │  ACM certificate
                │  listener rule: authenticate-    │  Cognito user pool (F2)
                │  cognito → forward to portal     │  idle timeout 300 s (F10)
                └──────┬──────────────────────────┘
   VPC 10.0.0.0/16     │ 3000                public subnets (ALB, NAT)
  ─────────────────────┼──────────────────────────────────────────────
                ┌──────▼──────┐  http://api:8000   private subnets
                │ ECS: portal │ ───────────────┐   (Service Connect)
                └─────────────┘         ┌──────▼─────┐
                                        │ ECS: api   │
                ┌─────────────┐         └──────┬─────┘
                │ ECS: worker │                │ 5432
                └──────┬──────┘         ┌──────▼──────────────┐
  EventBridge  ┌───────┴──────┐  5432   │ RDS PostgreSQL 16   │
  Scheduler ──►│ ECS RunTask: │────────►│ pgvector · pg_trgm  │
               │ jobs         │         │ not publicly        │
               └──────────────┘         │ accessible          │
                                        └─────────────────────┘
  Secrets Manager (DB URLs, OIDC secret, Snowflake key) · ECR · CloudWatch Logs
```

| Component | AWS service | Image | Command |
|---|---|---|---|
| Portal (Next.js 15) | ECS Fargate service behind ALB | `marketplace-portal` | `npm run start --workspace portal` |
| API (FastAPI) | ECS Fargate service, Service Connect name `api` | `marketplace-backend` | `uvicorn services.api.main:app` |
| Worker | ECS Fargate service, no load balancer | `marketplace-backend` | `python -m services.worker.main` |
| Migrate / seed / harvest / score / mesh / observe / evaluate … | ECS RunTask (one-off and scheduled) | `marketplace-backend` | `python scripts/<job>.py` |
| Database | RDS for PostgreSQL 16 | — | — |
| Secrets | Secrets Manager | — | — |
| Sign-in | Cognito user pool on the ALB | — | — |

---

## 2. Containerise the application

These three files are committed at the repository root; they are reproduced here so the guide reads
end to end. The copies in the repository are authoritative.

### 2.1 `.dockerignore`

```
.git
**/node_modules
portal/.next
.venv
**/__pycache__
.env
.env.*
!.env.example
*.docx
docs/*.pdf
playwright-report
test-results
```

### 2.2 `Dockerfile.backend` — API, worker and every job

The code resolves files relative to the repository root (`generated/types/model_constants.py`,
`manifests/`, `seed/`), so the repository is copied into `/app` and installed *editable*, exactly as
`npm run bootstrap` does locally.

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY . .

# Set WITH_SNOWFLAKE=true only when harvesting a real Snowflake account or running
# AGENT_RUNTIME=cortex (finding F4). The default analytic runtime does not need it.
ARG WITH_SNOWFLAKE=false
RUN pip install --upgrade pip \
 && pip install -e . \
 && if [ "$WITH_SNOWFLAKE" = "true" ]; then pip install snowflake-connector-python; fi \
 && useradd --uid 10001 --create-home app \
 && chown -R app /app

USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "services.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
```

### 2.3 `Dockerfile.portal`

npm workspaces: the lockfile is at the root, so install from the root and build the `portal`
workspace. `generated/` is copied because `tsconfig.json` maps `@generated/*` to it.

```dockerfile
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY portal/package.json portal/package.json
RUN npm ci --no-audit --no-fund
COPY generated ./generated
COPY portal ./portal
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build --workspace portal

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app/package.json /app/package-lock.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/portal ./portal
COPY --from=build --chown=node:node /app/generated ./generated
USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--workspace", "portal"]
```

### 2.4 Smoke-test locally before touching AWS

```bash
docker compose up -d --wait                       # local Postgres + Redis
docker build -f Dockerfile.backend -t marketplace-backend .
docker build -f Dockerfile.portal  -t marketplace-portal  .

# Run a job and the API against the local database (host networking keeps the .env URLs valid).
docker run --rm --network host --env-file .env marketplace-backend python scripts/migrate.py
docker run --rm --network host --env-file .env marketplace-backend python scripts/seed.py
docker run --rm --network host --env-file .env marketplace-backend &
curl -s localhost:8000/api/v1/health            # {"status":"ok","tenant_id":"TEN-DEMO"}
docker run --rm --network host --env-file .env marketplace-portal
```

Open <http://localhost:3000>. If this does not work locally it will not work on ECS.

---

## 3. Prerequisites in the AWS account

```bash
export AWS_REGION=us-east-2
export AWS_PROFILE=default                  # the profile you signed in with
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export APP=marketplace
export ENV=pilot
echo "$ACCOUNT_ID / $AWS_REGION"
```

You need: AWS CLI v2, Docker, permissions to create VPC, RDS, ECS, ECR, ELB, IAM, Secrets Manager,
Cognito, ACM, EventBridge, CloudWatch — and **a domain name** you can add DNS records to (Route 53
or elsewhere). The ALB can only run Cognito sign-in on an HTTPS listener, and HTTPS needs a
certificate for a name you control.

---

## 4. Network

### 4.1 VPC (console wizard — fastest and least error-prone)

VPC console → **Create VPC** → **VPC and more**:

| Setting | Value |
|---|---|
| Name tag auto-generation | `marketplace-pilot` |
| IPv4 CIDR | `10.0.0.0/16` |
| Availability Zones | 2 |
| Public subnets | 2 |
| Private subnets | 2 |
| NAT gateways | **In 1 AZ** (pilot) · 1 per AZ (production) |
| VPC endpoints | S3 Gateway |

The NAT gateway lets private tasks pull images from ECR and reach Secrets Manager and CloudWatch.
(Production alternative: interface endpoints for `ecr.api`, `ecr.dkr`, `secretsmanager`, `logs`
and no NAT — see 05 §2.)

Record the IDs:

```bash
export VPC_ID=vpc-xxxxxxxx
export PUBLIC_SUBNETS=subnet-aaa,subnet-bbb
export PRIVATE_SUBNETS=subnet-ccc,subnet-ddd
```

### 4.2 Security groups

```bash
mk_sg() { aws ec2 create-security-group --vpc-id $VPC_ID --group-name "$1" \
            --description "$1" --query GroupId --output text; }
ALB_SG=$(mk_sg $APP-alb);    PORTAL_SG=$(mk_sg $APP-portal)
API_SG=$(mk_sg $APP-api);    WORKER_SG=$(mk_sg $APP-worker)   # worker + jobs
DB_SG=$(mk_sg $APP-db)

allow() { aws ec2 authorize-security-group-ingress --group-id "$1" --protocol tcp --port "$2" "${@:3}"; }
allow $ALB_SG    443  --cidr 0.0.0.0/0               # narrow to corporate CIDRs if you can
allow $PORTAL_SG 3000 --source-group $ALB_SG
allow $API_SG    8000 --source-group $PORTAL_SG
allow $API_SG    8000 --source-group $WORKER_SG
for SRC in $API_SG $WORKER_SG; do allow $DB_SG 5432 --source-group $SRC; done
```

`portal-sg` accepting traffic **only** from `alb-sg` is what makes ALB authentication meaningful —
nothing can reach the portal without passing the sign-in rule.

---

## 5. Database — RDS for PostgreSQL 16

```bash
aws rds create-db-subnet-group --db-subnet-group-name $APP-$ENV \
  --db-subnet-group-description "$APP $ENV" --subnet-ids ${PRIVATE_SUBNETS//,/ }

# Parameter group with the timeouts from 05 §3 (milliseconds).
aws rds create-db-parameter-group --db-parameter-group-name $APP-pg16 \
  --db-parameter-group-family postgres16 --description "$APP postgres 16"
aws rds modify-db-parameter-group --db-parameter-group-name $APP-pg16 --parameters \
  "ParameterName=statement_timeout,ParameterValue=30000,ApplyMethod=immediate" \
  "ParameterName=idle_in_transaction_session_timeout,ParameterValue=60000,ApplyMethod=immediate" \
  "ParameterName=lock_timeout,ParameterValue=10000,ApplyMethod=immediate"

# Alphanumeric passwords: they go inside a URL, so punctuation would need escaping.
OWNER_PW=$(aws secretsmanager get-random-password --exclude-punctuation --password-length 32 \
  --query RandomPassword --output text)
APP_PW=$(aws secretsmanager get-random-password --exclude-punctuation --password-length 32 \
  --query RandomPassword --output text)

aws rds create-db-instance \
  --db-instance-identifier $APP-$ENV \
  --engine postgres --engine-version 16 \
  --db-instance-class db.t4g.small \
  --allocated-storage 20 --storage-type gp3 --storage-encrypted \
  --db-name marketplace \
  --master-username marketplace --master-user-password "$OWNER_PW" \
  --db-subnet-group-name $APP-$ENV --vpc-security-group-ids $DB_SG \
  --db-parameter-group-name $APP-pg16 \
  --no-publicly-accessible --backup-retention-period 7 \
  --deletion-protection
aws rds wait db-instance-available --db-instance-identifier $APP-$ENV
DB_HOST=$(aws rds describe-db-instances --db-instance-identifier $APP-$ENV \
  --query 'DBInstances[0].Endpoint.Address' --output text)
```

The migrate task in step 7 creates `vector` and `pg_trgm` itself (F5); if the engine version lacks
either, that task fails on its first statement and says so in the log.

Production: `--multi-az`, `db.m7g.large` or Aurora Serverless v2, 14–35 day backups, a
customer-managed KMS key, and RDS Proxy before the API scales past ~4 tasks (05 §3).

You do **not** create `marketplace_app` by hand — `npm run migrate` creates it from
`APP_DATABASE_URL`, grants `app_role`, and re-asserts `NOSUPERUSER NOBYPASSRLS` on every run (F6).

---

## 6. Secrets, registry and images

### 6.1 One Secrets Manager secret for the sensitive values

```bash
SECRET_ARN=$(aws secretsmanager create-secret --name $APP/$ENV/app \
  --query ARN --output text --secret-string "$(cat <<JSON
{
  "DATABASE_URL":     "postgresql://marketplace:$OWNER_PW@$DB_HOST:5432/marketplace?sslmode=require",
  "APP_DATABASE_URL": "postgresql://marketplace_app:$APP_PW@$DB_HOST:5432/marketplace?sslmode=require",
  "OIDC_CLIENT_SECRET": "unused-until-oidc-is-implemented",
  "SNOWFLAKE_PRIVATE_KEY": ""
}
JSON
)")
unset OWNER_PW APP_PW
```

`sslmode=require` encrypts the connection; use `verify-full` with the RDS CA bundle where your
policy requires certificate verification.

### 6.2 ECR repositories and the first push

```bash
for R in backend portal; do
  aws ecr create-repository --repository-name $APP-$R \
    --image-scanning-configuration scanOnPush=true --image-tag-mutability IMMUTABLE
done
REG=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
aws ecr get-login-password | docker login --username AWS --password-stdin $REG

TAG=$(git rev-parse --short HEAD)
docker build --platform linux/amd64 -f Dockerfile.backend -t $REG/$APP-backend:$TAG .
docker build --platform linux/amd64 -f Dockerfile.portal  -t $REG/$APP-portal:$TAG  .
docker push $REG/$APP-backend:$TAG
docker push $REG/$APP-portal:$TAG
```

Build on `linux/amd64` (or set `runtimePlatform` to `ARM64` in the task definitions and build
`linux/arm64` for Graviton pricing).

---

## 7. ECS cluster, roles and the one-off database jobs

### 7.1 Cluster, log group, Service Connect namespace

```bash
aws ecs create-cluster --cluster-name $APP-$ENV \
  --service-connect-defaults namespace=$APP-$ENV \
  --settings name=containerInsights,value=enabled
aws logs create-log-group --log-group-name /ecs/$APP-$ENV
aws logs put-retention-policy --log-group-name /ecs/$APP-$ENV --retention-in-days 90
```

### 7.2 IAM roles

```bash
cat > /tmp/ecs-trust.json <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}
JSON
aws iam create-role --role-name $APP-$ENV-exec --assume-role-policy-document file:///tmp/ecs-trust.json
aws iam attach-role-policy --role-name $APP-$ENV-exec \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam put-role-policy --role-name $APP-$ENV-exec --policy-name read-app-secret \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",
   \"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"$SECRET_ARN\"}]}"

# Task role: the application itself calls no AWS API today (F4), so it is empty.
# ECS Exec (handy for debugging) needs the ssmmessages actions below.
aws iam create-role --role-name $APP-$ENV-task --assume-role-policy-document file:///tmp/ecs-trust.json
aws iam put-role-policy --role-name $APP-$ENV-task --policy-name ecs-exec --policy-document \
 '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ssmmessages:CreateControlChannel",
  "ssmmessages:CreateDataChannel","ssmmessages:OpenControlChannel","ssmmessages:OpenDataChannel"],
  "Resource":"*"}]}'
```

### 7.3 Shared environment

Every variable in `.env.example` is required; the processes refuse to boot without one. Non-secret
values go in the task definition, secrets come from step 6.1.

| Variable | Pilot value | Why |
|---|---|---|
| `PRODUCT_NAME` | your display name | brand token |
| `TENANT_ID` | `TEN-DEMO` (matches the seed) | RLS tenant |
| `REDIS_URL` | `redis://unused:6379/0` | present, never connected (F3) |
| `OIDC_ISSUER` | `https://oidc.local/realms/marketplace` | **must keep a local marker today** (F2) |
| `OIDC_CLIENT_ID` | `marketplace-portal` | |
| `SNOWFLAKE_ACCOUNT` / `_USER` / `_ROLE` | placeholders, or your real values | harvest uses the sandbox platform when no private key is set |
| `AGENT_RUNTIME` | `analytic` | no model call (F4) |
| `MODEL_PROVIDER` / `MODEL_ID` / `MODEL_MAX_TOKENS` | `anthropic` / `claude-sonnet-5` / `2000` | read, unused by `analytic` |
| `DEMO_TIER_SCHEMA` / `DEMO_TIER_SCALE` | `MARKETPLACE_DEMO` / `0.1` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | add an ADOT sidecar to make it real |
| `FEATURE_FLAG_SOURCE` | `env` | |
| `WORKER_POLL_SECONDS` | `5` | |
| `API_BASE_URL` | `http://api:8000/api/v1` | Service Connect alias (step 8) |
| `PORTAL_BASE_URL` | `https://marketplace.example.com` | your domain |
| `PORTAL_LOCALE` | `en` | |
| `PORTAL_DEV_SUBJECT` | `PTY-0061` | the identity every user acts as (F2) |

### 7.4 Task definition: `jobs` (also the template for api and worker)

Save as `taskdef-backend.json`, replacing `ACCOUNT_ID`, `TAG`, `SECRET_ARN` and the domain:

```json
{
  "family": "marketplace-jobs",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "512", "memory": "1024",
  "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
  "executionRoleArn": "arn:aws:iam::ACCOUNT_ID:role/marketplace-pilot-exec",
  "taskRoleArn": "arn:aws:iam::ACCOUNT_ID:role/marketplace-pilot-task",
  "containerDefinitions": [{
    "name": "app",
    "image": "ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/marketplace-backend:TAG",
    "essential": true,
    "command": ["python", "scripts/migrate.py"],
    "environment": [
      {"name": "PRODUCT_NAME", "value": "Enterprise Data & Agents Marketplace"},
      {"name": "TENANT_ID", "value": "TEN-DEMO"},
      {"name": "REDIS_URL", "value": "redis://unused:6379/0"},
      {"name": "OIDC_ISSUER", "value": "https://oidc.local/realms/marketplace"},
      {"name": "OIDC_CLIENT_ID", "value": "marketplace-portal"},
      {"name": "SNOWFLAKE_ACCOUNT", "value": "placeholder"},
      {"name": "SNOWFLAKE_USER", "value": "SVC_MARKETPLACE_HARVEST"},
      {"name": "SNOWFLAKE_ROLE", "value": "MKT_READONLY"},
      {"name": "AGENT_RUNTIME", "value": "analytic"},
      {"name": "MODEL_PROVIDER", "value": "anthropic"},
      {"name": "MODEL_ID", "value": "claude-sonnet-5"},
      {"name": "MODEL_MAX_TOKENS", "value": "2000"},
      {"name": "DEMO_TIER_SCHEMA", "value": "MARKETPLACE_DEMO"},
      {"name": "DEMO_TIER_SCALE", "value": "0.1"},
      {"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": "http://localhost:4318"},
      {"name": "FEATURE_FLAG_SOURCE", "value": "env"},
      {"name": "WORKER_POLL_SECONDS", "value": "5"},
      {"name": "API_BASE_URL", "value": "http://api:8000/api/v1"},
      {"name": "PORTAL_BASE_URL", "value": "https://marketplace.example.com"},
      {"name": "PORTAL_LOCALE", "value": "en"},
      {"name": "PORTAL_DEV_SUBJECT", "value": "PTY-0061"}
    ],
    "secrets": [
      {"name": "DATABASE_URL",          "valueFrom": "SECRET_ARN:DATABASE_URL::"},
      {"name": "APP_DATABASE_URL",      "valueFrom": "SECRET_ARN:APP_DATABASE_URL::"},
      {"name": "OIDC_CLIENT_SECRET",    "valueFrom": "SECRET_ARN:OIDC_CLIENT_SECRET::"},
      {"name": "SNOWFLAKE_PRIVATE_KEY", "valueFrom": "SECRET_ARN:SNOWFLAKE_PRIVATE_KEY::"}
    ],
    "logConfiguration": {"logDriver": "awslogs", "options": {
      "awslogs-group": "/ecs/marketplace-pilot", "awslogs-region": "us-east-2",
      "awslogs-stream-prefix": "jobs"}}
  }]
}
```

```bash
aws ecs register-task-definition --cli-input-json file://taskdef-backend.json
```

### 7.5 Run the first-deployment jobs, in order

```bash
run_job() {   # usage: run_job "python scripts/migrate.py && python scripts/seed.py"
  ARN=$(aws ecs run-task --cluster $APP-$ENV --launch-type FARGATE \
    --task-definition marketplace-jobs \
    --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNETS],securityGroups=[$WORKER_SG],assignPublicIp=DISABLED}" \
    --overrides "{\"containerOverrides\":[{\"name\":\"app\",\"command\":[\"sh\",\"-c\",\"$1\"]}]}" \
    --query 'tasks[0].taskArn' --output text)
  aws ecs wait tasks-stopped --cluster $APP-$ENV --tasks $ARN
  aws ecs describe-tasks --cluster $APP-$ENV --tasks $ARN \
    --query 'tasks[0].containers[0].[exitCode,reason]' --output text
}

# 1. Schema (owner role) + application login. Expect exit code 0.
run_job "python scripts/migrate.py"
# 2. Catalog: taxonomies, rubrics, KPIs, products, agents.
run_job "python scripts/seed.py"
# 3. Platform sandbox, harvest and score (what npm run dev does).
run_job "python scripts/seed_platform.py && python scripts/harvest.py && python scripts/score.py"
# 4. Demo tier the agents answer from, then the CI chain that publishes agents.
run_job "python scripts/seed_demo_tier.py && python scripts/demo_runner.py --verify && python scripts/evaluate.py && python scripts/publish_agents.py"
# 5. Meshes, divergence, signals and the value snapshot.
run_job "python scripts/mesh.py && python scripts/observe.py"
```

Read the output of each in CloudWatch (`/ecs/marketplace-pilot`, prefix `jobs`). Do not continue
past a non-zero exit — the CI pipeline runs exactly this sequence and treats every failure as real.

---

## 8. Services: API, worker, portal, load balancer

### 8.1 Task definitions

From `taskdef-backend.json` make two copies:

* **`marketplace-api`**: `family` → `marketplace-api`; `cpu`/`memory` → `1024`/`2048`; delete
  `command` (the image default runs uvicorn); stream prefix `api`; add
  ```json
  "portMappings": [{"name": "api", "containerPort": 8000, "protocol": "tcp", "appProtocol": "http"}],
  "healthCheck": {"command": ["CMD-SHELL",
    "python -c \"import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/health')\""],
    "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 30}
  ```
* **`marketplace-worker`**: `family` → `marketplace-worker`; `cpu`/`memory` → `256`/`512`;
  `command` → `["python", "-m", "services.worker.main"]`; stream prefix `worker`.

And **`taskdef-portal.json`**: same structure with image `marketplace-portal:TAG`, `cpu`/`memory`
`512`/`1024`, no `command`, stream prefix `portal`, `portMappings`
`[{"name":"portal","containerPort":3000,"protocol":"tcp"}]`. Its environment needs only
`PRODUCT_NAME`, `TENANT_ID`, `API_BASE_URL`, `OIDC_ISSUER`, `PORTAL_DEV_SUBJECT`, `PORTAL_LOCALE`
and no secrets (it never touches the database).

Register all three with `aws ecs register-task-definition --cli-input-json file://…`.

### 8.2 Certificate and load balancer

```bash
DOMAIN=marketplace.example.com
CERT_ARN=$(aws acm request-certificate --domain-name $DOMAIN --validation-method DNS \
  --query CertificateArn --output text)
aws acm describe-certificate --certificate-arn $CERT_ARN \
  --query 'Certificate.DomainValidationOptions[0].ResourceRecord'
# Add that CNAME at your DNS provider, then:
aws acm wait certificate-validated --certificate-arn $CERT_ARN

ALB_ARN=$(aws elbv2 create-load-balancer --name $APP-$ENV --type application \
  --scheme internet-facing --subnets ${PUBLIC_SUBNETS//,/ } --security-groups $ALB_SG \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)
# /api/events streams (F10): raise the idle timeout from 60 s.
aws elbv2 modify-load-balancer-attributes --load-balancer-arn $ALB_ARN \
  --attributes Key=idle_timeout.timeout_seconds,Value=300 \
               Key=routing.http.drop_invalid_header_fields.enabled,Value=true

TG_ARN=$(aws elbv2 create-target-group --name $APP-$ENV-portal --protocol HTTP --port 3000 \
  --vpc-id $VPC_ID --target-type ip --health-check-path / --matcher HttpCode=200-399 \
  --query 'TargetGroups[0].TargetGroupArn' --output text)
```

The HTTPS listener is created in step 9 together with the sign-in rule. Point your DNS name
(`CNAME` or Route 53 alias) at the ALB's `DNSName`.

### 8.3 Services

```bash
NET="awsvpcConfiguration={subnets=[$PRIVATE_SUBNETS],assignPublicIp=DISABLED"

aws ecs create-service --cluster $APP-$ENV --service-name api \
  --task-definition marketplace-api --desired-count 2 --launch-type FARGATE \
  --network-configuration "$NET,securityGroups=[$API_SG]}" \
  --enable-execute-command \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}" \
  --service-connect-configuration '{"enabled":true,"services":[{"portName":"api",
      "clientAliases":[{"port":8000,"dnsName":"api"}]}]}'

aws ecs create-service --cluster $APP-$ENV --service-name worker \
  --task-definition marketplace-worker --desired-count 1 --launch-type FARGATE \
  --network-configuration "$NET,securityGroups=[$WORKER_SG]}" \
  --enable-execute-command \
  --service-connect-configuration '{"enabled":true}'

aws ecs create-service --cluster $APP-$ENV --service-name portal \
  --task-definition marketplace-portal --desired-count 2 --launch-type FARGATE \
  --network-configuration "$NET,securityGroups=[$PORTAL_SG]}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=app,containerPort=3000" \
  --health-check-grace-period-seconds 60 \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}" \
  --service-connect-configuration '{"enabled":true}'

aws ecs wait services-stable --cluster $APP-$ENV --services api worker portal
```

`"enabled":true` without `services` makes the portal and worker Service Connect *clients*, which is
what lets `http://api:8000` resolve inside them.

---

## 9. Sign-in at the load balancer (Cognito)

Because of F2 this is the only thing standing between the internet and the application. Do not skip
it, and do not create an HTTP listener that forwards to the portal.

```bash
POOL_ID=$(aws cognito-idp create-user-pool --pool-name $APP-$ENV \
  --admin-create-user-config AllowAdminCreateUserOnly=true \
  --auto-verified-attributes email --username-attributes email \
  --query UserPool.Id --output text)
aws cognito-idp set-user-pool-mfa-config --user-pool-id $POOL_ID \
  --software-token-mfa-configuration Enabled=true --mfa-configuration OPTIONAL

aws cognito-idp create-user-pool-domain --user-pool-id $POOL_ID --domain $APP-$ENV-$ACCOUNT_ID

CLIENT_ID=$(aws cognito-idp create-user-pool-client --user-pool-id $POOL_ID \
  --client-name alb --generate-secret \
  --allowed-o-auth-flows code --allowed-o-auth-scopes openid email \
  --allowed-o-auth-flows-user-pool-client --supported-identity-providers COGNITO \
  --callback-urls "https://$DOMAIN/oauth2/idpresponse" \
  --query UserPoolClient.ClientId --output text)

POOL_ARN=arn:aws:cognito-idp:$AWS_REGION:$ACCOUNT_ID:userpool/$POOL_ID

aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTPS --port 443 \
  --certificates CertificateArn=$CERT_ARN --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 \
  --default-actions "[
    {\"Type\":\"authenticate-cognito\",\"Order\":1,\"AuthenticateCognitoConfig\":{
       \"UserPoolArn\":\"$POOL_ARN\",\"UserPoolClientId\":\"$CLIENT_ID\",
       \"UserPoolDomain\":\"$APP-$ENV-$ACCOUNT_ID\",\"OnUnauthenticatedRequest\":\"authenticate\",
       \"Scope\":\"openid email\"}},
    {\"Type\":\"forward\",\"Order\":2,\"TargetGroupArn\":\"$TG_ARN\"}]"

# Invite people (they receive a temporary password by email).
aws cognito-idp admin-create-user --user-pool-id $POOL_ID --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
```

To sign in with the corporate IdP instead of Cognito passwords, add it to the user pool as a SAML or
OIDC identity provider, or use the ALB `authenticate-oidc` action against the IdP directly (05 §5).

Optional but recommended: attach an AWS WAF web ACL with the `AWSManagedRulesCommonRuleSet` to the
ALB.

---

## 10. Verify the deployment

| Check | How | Expect |
|---|---|---|
| Services stable | `aws ecs describe-services --cluster $APP-$ENV --services api worker portal --query 'services[].[serviceName,runningCount,desiredCount]'` | running = desired |
| API health (from inside) | `aws ecs execute-command --cluster $APP-$ENV --task <api-task> --container app --interactive --command "python -c \"import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/v1/health').read())\""` | `{"status":"ok","tenant_id":"TEN-DEMO"}` |
| Sign-in gate | open `https://$DOMAIN` in a private window | redirected to the Cognito hosted page |
| Catalog | sign in | products, agents, quality bands and owners render on the landing page |
| Agent demo | open any agent → Demo | a curated question answers with citations |
| RLS not bypassed | `run_job "pip install --user -q pytest && python scripts/run_tests.py tests/security"` | pass |
| Reconciliation | queries in [`build-spec/04-data-loading.md` §8](build-spec/04-data-loading.md) via ECS Exec + `psql`, or a job | zero rows |
| Target health | `aws elbv2 describe-target-health --target-group-arn $TG_ARN` | `healthy` |

---

## 11. Scheduled jobs and alarms

### 11.1 EventBridge Scheduler → ECS RunTask

```bash
cat > /tmp/sched-trust.json <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"scheduler.amazonaws.com"},"Action":"sts:AssumeRole"}]}
JSON
aws iam create-role --role-name $APP-$ENV-scheduler --assume-role-policy-document file:///tmp/sched-trust.json
aws iam put-role-policy --role-name $APP-$ENV-scheduler --policy-name run-jobs --policy-document "{
 \"Version\":\"2012-10-17\",\"Statement\":[
  {\"Effect\":\"Allow\",\"Action\":\"ecs:RunTask\",
   \"Resource\":\"arn:aws:ecs:$AWS_REGION:$ACCOUNT_ID:task-definition/marketplace-jobs:*\"},
  {\"Effect\":\"Allow\",\"Action\":\"iam:PassRole\",\"Resource\":[
   \"arn:aws:iam::$ACCOUNT_ID:role/$APP-$ENV-exec\",\"arn:aws:iam::$ACCOUNT_ID:role/$APP-$ENV-task\"]}]}"

schedule() {  # usage: schedule <name> "<rate or cron expression>" "<shell command>"
  aws scheduler create-schedule --name $APP-$ENV-$1 --schedule-expression "$2" \
    --flexible-time-window Mode=OFF --target "{
      \"Arn\":\"arn:aws:ecs:$AWS_REGION:$ACCOUNT_ID:cluster/$APP-$ENV\",
      \"RoleArn\":\"arn:aws:iam::$ACCOUNT_ID:role/$APP-$ENV-scheduler\",
      \"EcsParameters\":{
        \"TaskDefinitionArn\":\"arn:aws:ecs:$AWS_REGION:$ACCOUNT_ID:task-definition/marketplace-jobs\",
        \"LaunchType\":\"FARGATE\",
        \"NetworkConfiguration\":{\"awsvpcConfiguration\":{
          \"Subnets\":[\"${PRIVATE_SUBNETS//,/\",\"}\"],\"SecurityGroups\":[\"$WORKER_SG\"],
          \"AssignPublicIp\":\"DISABLED\"}}},
      \"Input\":\"{\\\"containerOverrides\\\":[{\\\"name\\\":\\\"app\\\",\\\"command\\\":[\\\"sh\\\",\\\"-c\\\",\\\"$3\\\"]}]}\"}"
}

schedule harvest   "rate(1 hour)"           "python scripts/harvest.py"
schedule score     "cron(30 2 * * ? *)"     "python scripts/score.py"
schedule mesh      "cron(0 3 * * ? *)"      "python scripts/mesh.py"
schedule observe   "rate(5 minutes)"        "python scripts/observe.py"
schedule demo      "cron(0 4 * * ? *)"      "python scripts/demo_runner.py --nightly"
schedule drill     "cron(0 5 ? * SUN *)"    "python scripts/rollback_drill.py"
```

`evaluate` → `publish_agents` runs on agent change, from the deployment pipeline (step 12), not on a
timer. Cron expressions are UTC.

### 11.2 Alarm on every failed job (F11)

```bash
TOPIC_ARN=$(aws sns create-topic --name $APP-$ENV-alerts --query TopicArn --output text)
aws sns subscribe --topic-arn $TOPIC_ARN --protocol email --notification-endpoint ops@example.com

aws events put-rule --name $APP-$ENV-job-failed --event-pattern '{
  "source": ["aws.ecs"], "detail-type": ["ECS Task State Change"],
  "detail": {"lastStatus": ["STOPPED"], "group": ["family:marketplace-jobs"],
             "containers": {"exitCode": [{"anything-but": 0}]}}}'
aws events put-targets --rule $APP-$ENV-job-failed --targets "Id=sns,Arn=$TOPIC_ARN"
aws sns set-topic-attributes --topic-arn $TOPIC_ARN --attribute-name Policy --attribute-value "{
 \"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",
 \"Principal\":{\"Service\":\"events.amazonaws.com\"},\"Action\":\"sns:Publish\",\"Resource\":\"$TOPIC_ARN\"}]}"
```

Add CloudWatch alarms for the rest of 05 §9: ALB `HTTPCode_Target_5XX_Count`, ALB
`TargetResponseTime` p95 > 2 s, RDS `CPUUtilization` and `DatabaseConnections` > 80 %, and a
`harvest` staleness alarm (no successful run in 3 hours).

---

## 12. Continuous deployment from GitHub Actions

Use GitHub OIDC so no AWS key is stored in the repository.

1. IAM → Identity providers → add `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`).
2. Create role `marketplace-github-deploy` trusted for
   `repo:CloudKatasani/Enterprise-Data-Product-AI-Agent-Marketplace:ref:refs/heads/main`, allowed:
   ECR push to both repositories, `ecs:RegisterTaskDefinition`, `ecs:DescribeTaskDefinition`,
   `ecs:RunTask`, `ecs:DescribeTasks`, `ecs:UpdateService`, `ecs:DescribeServices`, and
   `iam:PassRole` on the exec and task roles.
3. Add a workflow that runs **after** the existing `CI` workflow succeeds on `main`, in the order
   05 §8 requires:

```
build + push both images (tag = commit SHA)
  → register new task definitions with that tag
  → run-task migrate (wait; fail the deploy on non-zero exit)
  → run-task evaluate && publish_agents
  → update-service api → wait stable
  → update-service worker → wait stable
  → update-service portal → wait stable
  → smoke: GET /api/v1/health via ECS Exec, GET https://$DOMAIN (expect 302 to Cognito)
```

`aws-actions/configure-aws-credentials`, `aws-actions/amazon-ecr-login`,
`aws-actions/amazon-ecs-render-task-definition` and `aws-actions/amazon-ecs-deploy-task-definition`
cover each step.

**Rollback** = update each service to the previous task definition revision. **Migrations never roll
back** — keep them backwards-compatible (05 §8).

---

## 13. Before calling it production

| Gap | Fix | Effort |
|---|---|---|
| Single shared identity (F2) | Implement option B from `build-spec/02-architecture.md` §5: Auth.js in the portal sending the IdP's bearer token; `services/api/auth.py` verifying it against the issuer's **JWKS** (RS256) instead of `OIDC_CLIENT_SECRET`; map `sub` to `party.external_subject`. Then set `OIDC_ISSUER` to the real issuer. Interim alternative: map the ALB's verified `x-amzn-oidc-identity` header to a party in the portal. | days |
| API holds the schema-owner URL | Every process validates `DATABASE_URL` (F6). Give the long-running API and worker a narrower value only once the config allows it; until then restrict who can read the secret. | small code change |
| Real warehouse | Snowflake over AWS PrivateLink, key-pair auth, private key in the secret, `WITH_SNOWFLAKE=true` image, `npm run test:kill` against the sandbox (05 §6). | days |
| Resilience | RDS Multi-AZ, NAT per AZ, API ≥ 2 tasks across AZs (already), RDS Proxy, service auto-scaling on CPU. | hours |
| Traces | ADOT collector sidecar; point `OTEL_EXPORTER_OTLP_ENDPOINT` at it. | hours |
| Infrastructure as code | Translate steps 4–11 into Terraform using the layout in 05 §7. | days |

---

## 14. Indicative monthly cost — pilot, us-east-2

Approximate on-demand list prices; check the AWS Pricing Calculator for your account.

| Item | Size | ~USD / month |
|---|---|---|
| Fargate | portal 2×(0.5 vCPU/1 GB), api 2×(1 vCPU/2 GB), worker 0.25 vCPU/0.5 GB | 110–130 |
| Fargate scheduled jobs | `observe` every 5 min dominates | 10–20 |
| RDS PostgreSQL | db.t4g.small, 20 GB gp3, single-AZ | 30–35 |
| NAT gateway | 1, light traffic | 35–45 |
| ALB | 1, low LCU | 20–25 |
| Secrets Manager, ECR, CloudWatch, Cognito (< 10k MAU free tier) | | 10–20 |
| **Total** | | **~215–275** |

Biggest levers: remove the NAT gateway with VPC interface endpoints (cheaper only beyond a few
endpoints), run the portal and API as 1 task each outside business hours, Graviton (`ARM64`) tasks
(~20 % less).

---

## 15. Tear down

```bash
for S in portal worker api; do aws ecs update-service --cluster $APP-$ENV --service $S --desired-count 0; done
for S in portal worker api; do aws ecs delete-service --cluster $APP-$ENV --service $S --force; done
for N in harvest score mesh observe demo drill; do aws scheduler delete-schedule --name $APP-$ENV-$N; done
aws elbv2 delete-load-balancer --load-balancer-arn $ALB_ARN
aws rds modify-db-instance --db-instance-identifier $APP-$ENV --no-deletion-protection --apply-immediately
aws rds delete-db-instance --db-instance-identifier $APP-$ENV --final-db-snapshot-identifier $APP-$ENV-final
aws ecs delete-cluster --cluster $APP-$ENV
# Then: target group, ECR repositories, secret, Cognito pool, NAT gateway / VPC (VPC console → Delete VPC).
```

The NAT gateway and RDS instance are what keep billing if you stop half-way.

---

## Appendix A — one-machine demo in 20 minutes

For a throwaway demonstration rather than a hosted service: one EC2 instance running exactly what a
developer runs.

1. Launch **Ubuntu 24.04, t3.large, 30 GB gp3**, no inbound rules, with an instance profile that has
   `AmazonSSMManagedInstanceCore`.
2. Connect with Session Manager and install Docker, Node 22, Python 3.12, git.
3. `git clone` the repository, `cp .env.example .env`, `npm install`, `npm run bootstrap`,
   `npm run dev`.
4. From your laptop:
   `aws ssm start-session --target <instance-id> --document-name AWS-StartPortForwardingSession --parameters portNumber=3000,localPortNumber=3000`
   and open <http://localhost:3000>.

No port is open to the internet, so the missing production sign-in (F2) does not matter here. Stop
the instance when you are done.
