# Hosting the marketplace on AWS — using the AWS Management Console

This is the **click-through** version of [`DEPLOY_AWS.md`](DEPLOY_AWS.md). It builds the same
estate — ECS Fargate, RDS for PostgreSQL 16, Service Connect, Secrets Manager, Cognito sign-in on an
Application Load Balancer, EventBridge Scheduler — but every step is done in the AWS Management
Console. The only text you type outside a console form is JSON you paste into console editors and,
optionally, two commands in **AWS CloudShell** (a browser terminal inside the console).

> Building a low-cost prototype? [`DEPLOY_AWS_SIMPLE.md`](DEPLOY_AWS_SIMPLE.md) runs the whole
> marketplace on one EC2 instance with a single install command, and needs no other AWS service.

Read [`DEPLOY_AWS.md` §0](DEPLOY_AWS.md#0-read-this-first--what-the-review-found) first. Its
findings F1–F11 explain *why* the steps below look the way they do. The four that matter most:

* **F2 — there is no per-user sign-in in the application yet.** Cognito on the load balancer is the
  only thing protecting the site, and every signed-in person acts as the seeded party
  `PORTAL_DEV_SUBJECT`. This is a governed pilot, not multi-user production.
  `OIDC_ISSUER` **must** keep the `oidc.local` value used below.
* **F6 — two database logins, on purpose.** `DATABASE_URL` is the RDS master user (schema owner).
  `APP_DATABASE_URL` is a second login that the migrate job creates for you. Never point both at the
  master user, or row-level security silently switches off.
* **F9 — only the portal is public.** The API has no load balancer; the portal reaches it at
  `http://api:8000` through ECS Service Connect.
* **F3/F4 — no Redis and no Bedrock are needed.** `REDIS_URL` only has to be present.

---

## Contents

1. [Before you start](#1-before-you-start)
2. [Network — VPC](#2-network--vpc)
3. [Security groups](#3-security-groups)
4. [Database — RDS for PostgreSQL 16](#4-database--rds-for-postgresql-16)
5. [Secrets Manager](#5-secrets-manager)
6. [ECR repositories](#6-ecr-repositories)
7. [Build and push the images](#7-build-and-push-the-images)
8. [IAM roles](#8-iam-roles)
9. [CloudWatch log group](#9-cloudwatch-log-group)
10. [ECS cluster](#10-ecs-cluster)
11. [ECS task definitions](#11-ecs-task-definitions)
12. [Run the first-deployment database jobs](#12-run-the-first-deployment-database-jobs)
13. [TLS certificate (ACM)](#13-tls-certificate-acm)
14. [Cognito user pool](#14-cognito-user-pool)
15. [Target group and Application Load Balancer](#15-target-group-and-application-load-balancer)
16. [ECS services: api, worker, portal](#16-ecs-services-api-worker-portal)
17. [DNS and first sign-in](#17-dns-and-first-sign-in)
18. [Verify the deployment](#18-verify-the-deployment)
19. [Scheduled jobs](#19-scheduled-jobs)
20. [Alerts](#20-alerts)
21. [Deploying a new version](#21-deploying-a-new-version)
22. [Troubleshooting](#22-troubleshooting)
23. [Cost and tear-down](#23-cost-and-tear-down)

---

## 1. Before you start

### 1.1 What you need

| Item | Notes |
|---|---|
| An AWS account and a console user with admin rights (or rights to VPC, EC2, RDS, ECS, ECR, ELB, IAM, Secrets Manager, Cognito, ACM, EventBridge, SNS, CloudWatch, CodeBuild) | |
| **A domain name you can add DNS records to** (Route 53 or any registrar) | The ALB can only run Cognito sign-in on HTTPS, and HTTPS needs a certificate for a name you control. Example used below: `marketplace.example.com`. |
| Access to the GitHub repository | CodeBuild clones it to build the images (step 7). |
| About 2–3 hours | Most of it is waiting for RDS, the certificate and the first jobs. |

### 1.2 Pick a region and stay in it

Top-right of the console → region selector → **US East (Ohio) `us-east-2`** (or your choice).
**Every** resource below must be created in the same region. When a step shows `us-east-2` in a
JSON snippet, replace it with your region.

### 1.3 Naming

Everything is prefixed `marketplace-pilot`. Keep the names exactly as written — the JSON snippets
refer to them.

### 1.4 Worksheet — fill this in as you go

Copy this table into a note. Later steps ask you to paste these values.

| Value | Where you get it | Your value |
|---|---|---|
| `ACCOUNT_ID` (12 digits) | top-right account menu | |
| `REGION` | step 1.2 | |
| `VPC_ID` | step 2 | |
| Public subnet IDs (2) | step 2 | |
| Private subnet IDs (2) | step 2 | |
| `OWNER_PW` | step 4.1 | (keep secret) |
| `APP_PW` | step 4.1 | (keep secret) |
| `DB_HOST` (RDS endpoint) | step 4.4 | |
| `SECRET_ARN` | step 5 | |
| `TAG` (image tag) | step 7 | |
| `DOMAIN` | your DNS name | |
| `CERT_ARN` | step 13 | |
| Cognito user pool ID / app client ID / domain | step 14 | |
| ALB DNS name | step 15 | |

---

## 2. Network — VPC

**VPC console → Your VPCs → Create VPC**

| Setting | Value |
|---|---|
| Resources to create | **VPC and more** |
| Name tag auto-generation | ✔ Auto-generate, `marketplace-pilot` |
| IPv4 CIDR block | `10.0.0.0/16` |
| IPv6 CIDR block | No IPv6 CIDR block |
| Tenancy | Default |
| Number of Availability Zones | **2** |
| Number of public subnets | **2** |
| Number of private subnets | **2** |
| NAT gateways | **In 1 AZ** (pilot) — *1 per AZ* for production |
| VPC endpoints | **S3 Gateway** |
| DNS options | ✔ Enable DNS hostnames, ✔ Enable DNS resolution |

Click **Create VPC** and wait for every line in the progress view to go green (the NAT gateway takes
a few minutes). Then **View VPC** and record in the worksheet:

* the VPC ID,
* the two subnet IDs whose names contain `subnet-public…`,
* the two subnet IDs whose names contain `subnet-private…`.

The NAT gateway is what lets tasks in the private subnets pull images from ECR and read Secrets
Manager. Nothing in this guide runs in a public subnet except the load balancer.

---

## 3. Security groups

**VPC console → Security groups → Create security group** — five times. For every one: VPC =
`marketplace-pilot-vpc`, **leave the default outbound rule (All traffic → 0.0.0.0/0)**.

Create them in this order (a rule can only reference a group that already exists):

| # | Name (and description) | Inbound rules |
|---|---|---|
| 1 | `marketplace-alb` | HTTPS, TCP 443, Source `0.0.0.0/0` *(narrow to your corporate CIDRs if you can)*. Optional: HTTP, TCP 80, `0.0.0.0/0` — only for the HTTP→HTTPS redirect in step 15.4 |
| 2 | `marketplace-portal` | Custom TCP **3000**, Source = security group `marketplace-alb` |
| 3 | `marketplace-worker` | *(none)* — used by the worker service and every one-off / scheduled job |
| 4 | `marketplace-api` | Custom TCP **8000**, Source = `marketplace-portal`; and a second rule Custom TCP **8000**, Source = `marketplace-worker` |
| 5 | `marketplace-db` | PostgreSQL TCP **5432**, Source = `marketplace-api`; and a second rule PostgreSQL TCP **5432**, Source = `marketplace-worker` |

To pick a security group as the source, start typing `sg-` or the name in the **Source** box and
choose it from the list.

> `marketplace-portal` accepting traffic **only** from `marketplace-alb` is what makes the sign-in
> at the load balancer meaningful: nothing reaches the portal without passing it.

---

## 4. Database — RDS for PostgreSQL 16

### 4.1 Make two passwords

The passwords go inside a connection URL, so use **letters and digits only** (no punctuation).
Easiest: open **CloudShell** (the `>_` icon in the console's top bar) and run this twice:

```bash
aws secretsmanager get-random-password --exclude-punctuation --password-length 32 \
  --query RandomPassword --output text
```

Record the first as `OWNER_PW` (RDS master user) and the second as `APP_PW` (application login).

### 4.2 Parameter group (database timeouts)

**RDS console → Parameter groups → Create parameter group**

| Setting | Value |
|---|---|
| Parameter group name | `marketplace-pg16` |
| Description | `marketplace postgres 16` |
| Engine type | PostgreSQL |
| Parameter group family | `postgres16` |
| Type | DB Parameter Group |

Create, open it → **Edit** → search and set (values are milliseconds):

| Parameter | Value |
|---|---|
| `statement_timeout` | `30000` |
| `idle_in_transaction_session_timeout` | `60000` |
| `lock_timeout` | `10000` |

**Save changes**.

### 4.3 Subnet group

**RDS console → Subnet groups → Create DB subnet group**

| Setting | Value |
|---|---|
| Name / Description | `marketplace-pilot` |
| VPC | `marketplace-pilot-vpc` |
| Availability Zones | the two AZs from step 2 |
| Subnets | **only the two private subnets** |

### 4.4 Create the database

**RDS console → Databases → Create database**

| Section | Setting | Value |
|---|---|---|
| Creation method | | **Standard create** |
| Engine options | Engine type | **PostgreSQL** |
| | Engine version | latest **PostgreSQL 16.x** (ships `pgvector` and `pg_trgm`, which migration `0001` creates — finding F5) |
| Templates | | **Dev/Test** for a pilot (*Production* for production) |
| Availability | | **Single-AZ DB instance** (pilot) — *Multi-AZ* for production |
| Settings | DB instance identifier | `marketplace-pilot` |
| | Master username | `marketplace` |
| | Credentials management | **Self managed** (you need the password inside the URL) |
| | Master password / Confirm | `OWNER_PW` |
| Instance configuration | | Burstable classes → **db.t4g.small** |
| Storage | | **gp3**, **20 GiB**; storage autoscaling on is fine |
| Connectivity | Compute resource | Don't connect to an EC2 compute resource |
| | VPC | `marketplace-pilot-vpc` |
| | DB subnet group | `marketplace-pilot` |
| | Public access | **No** |
| | VPC security group | **Choose existing** → `marketplace-db` (remove `default`) |
| | Database port | `5432` |
| Database authentication | | Password authentication |
| Monitoring | | defaults (Performance Insights on is fine) |
| **Additional configuration** *(expand it — easy to miss)* | **Initial database name** | **`marketplace`** |
| | DB parameter group | `marketplace-pg16` |
| | Backup retention | 7 days |
| | Encryption | ✔ Enable encryption |
| | Deletion protection | ✔ Enable |

**Create database**. It takes 10–20 minutes. When the status is **Available**, open it and copy
**Connectivity & security → Endpoint** into the worksheet as `DB_HOST`
(looks like `marketplace-pilot.xxxxxxxx.us-east-2.rds.amazonaws.com`).

Do **not** create the `marketplace_app` login yourself. The migrate job (step 12) creates it from
`APP_DATABASE_URL`, grants it `app_role` and forces `NOSUPERUSER NOBYPASSRLS`.

---

## 5. Secrets Manager

**Secrets Manager console → Store a new secret**

1. Secret type: **Other type of secret**.
2. Key/value pairs → switch to the **Plaintext** tab, delete what is there and paste (substitute
   `OWNER_PW`, `APP_PW` and `DB_HOST`):

   ```json
   {
     "DATABASE_URL": "postgresql://marketplace:OWNER_PW@DB_HOST:5432/marketplace?sslmode=require",
     "APP_DATABASE_URL": "postgresql://marketplace_app:APP_PW@DB_HOST:5432/marketplace?sslmode=require",
     "OIDC_CLIENT_SECRET": "unused-until-oidc-is-implemented",
     "SNOWFLAKE_PRIVATE_KEY": ""
   }
   ```

   `sslmode=require` is required: RDS for PostgreSQL 16 rejects unencrypted connections by default.
3. Encryption key: `aws/secretsmanager`. **Next**.
4. Secret name: **`marketplace/pilot/app`**. **Next** → no rotation → **Next** → **Store**.
5. Open the secret and copy its **Secret ARN** into the worksheet as `SECRET_ARN`
   (it ends in a random 6-character suffix, e.g. `…:secret:marketplace/pilot/app-AbC123`).

---

## 6. ECR repositories

**ECR console → Private registry → Repositories → Create repository** — twice:

| Repository name | Tag immutability | Scan on push |
|---|---|---|
| `marketplace-backend` | Immutable | ✔ (under *Image scanning settings*, or set a registry-level basic scan) |
| `marketplace-portal` | Immutable | ✔ |

The backend image runs the API, the worker **and** every job (one image, different commands).

---

## 7. Build and push the images

The repository root contains `Dockerfile.backend`, `Dockerfile.portal` and `.dockerignore`. Pick
**one** option.

### Option A — AWS CodeBuild (console only, recommended)

**7A.1 Connect GitHub (once).** CodeBuild console → **Settings → Connections → Create connection**
→ GitHub → name `github` → **Connect to GitHub** → authorise and install the AWS Connector app on
the `CloudKatasani` account for the repository → **Connect**. Status must read **Available**.

**7A.2 Create the build project.** CodeBuild console → **Build projects → Create build project**

| Section | Setting | Value |
|---|---|---|
| Project configuration | Project name | `marketplace-images` |
| Source | Source provider | **GitHub** |
| | Credential | the `github` connection (*Default source credential* or *Custom*) |
| | Repository | `CloudKatasani/Enterprise-Data-Product-AI-Agent-Marketplace` |
| | Source version | `main` |
| Environment | Provisioning model | On-demand |
| | Environment image | Managed image |
| | Compute | **EC2** |
| | Operating system | Amazon Linux |
| | Runtime | Standard, latest `aws/codebuild/amazonlinux-x86_64-standard:5.0` (or newer) |
| | **Privileged** | ✔ **Enable this flag if you want to build Docker images** — required |
| | Service role | New service role (note its name, e.g. `codebuild-marketplace-images-service-role`) |
| | Additional configuration → Compute | **7 GB memory, 4 vCPUs** (the Next.js build needs the memory) |
| | Additional configuration → Environment variables | `AWS_ACCOUNT_ID` = your account ID |
| Buildspec | Build specifications | **Insert build commands → Switch to editor**, paste the YAML below |
| Logs | CloudWatch logs | ✔ |

```yaml
version: 0.2
phases:
  pre_build:
    commands:
      - REG=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com
      - aws ecr get-login-password | docker login --username AWS --password-stdin $REG
      - TAG=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c1-7)
      - echo "Image tag will be $TAG"
  build:
    commands:
      - docker build --platform linux/amd64 -f Dockerfile.backend -t $REG/marketplace-backend:$TAG .
      - docker build --platform linux/amd64 -f Dockerfile.portal  -t $REG/marketplace-portal:$TAG  .
  post_build:
    commands:
      - docker push $REG/marketplace-backend:$TAG
      - docker push $REG/marketplace-portal:$TAG
      - echo "PUSHED TAG=$TAG"
```

**Create build project**.

**7A.3 Let CodeBuild push to ECR.** IAM console → **Roles** → the CodeBuild service role →
**Add permissions → Attach policies** → `AmazonEC2ContainerRegistryPowerUser` → **Add permissions**.

**7A.4 Build.** Back in the project → **Start build**. When it succeeds (8–15 min), open the build
log and find the line `PUSHED TAG=…`. Record that 7-character value as `TAG`. Both repositories in
ECR now show an image with that tag.

### Option B — Docker on your own machine

With Docker and AWS CLI v2 installed and signed in to the account:

```bash
REG=<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
aws ecr get-login-password --region <REGION> | docker login --username AWS --password-stdin $REG
TAG=$(git rev-parse --short HEAD)
docker build --platform linux/amd64 -f Dockerfile.backend -t $REG/marketplace-backend:$TAG .
docker build --platform linux/amd64 -f Dockerfile.portal  -t $REG/marketplace-portal:$TAG  .
docker push $REG/marketplace-backend:$TAG && docker push $REG/marketplace-portal:$TAG
echo $TAG
```

The ECR console's **View push commands** button on each repository shows the same login command.

---

## 8. IAM roles

### 8.1 Task execution role — lets ECS pull images, write logs and read the secret

**IAM console → Roles → Create role**

1. Trusted entity: **AWS service** → Service or use case **Elastic Container Service** → use case
   **Elastic Container Service Task** → **Next**.
2. Attach **`AmazonECSTaskExecutionRolePolicy`** → **Next**.
3. Role name **`marketplace-pilot-exec`** → **Create role**.
4. Open the role → **Add permissions → Create inline policy → JSON**, paste (substitute
   `SECRET_ARN`), **Next**, name `read-app-secret`, **Create policy**:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "secretsmanager:GetSecretValue",
       "Resource": "SECRET_ARN"
     }]
   }
   ```

### 8.2 Task role — what the running application may call

The application calls no AWS API today (finding F4). The only permissions are for **ECS Exec**,
which lets you open a shell in a running task for debugging.

1. **Create role** → AWS service → Elastic Container Service → **Elastic Container Service Task**
   → **Next** → attach nothing → **Next**.
2. Role name **`marketplace-pilot-task`** → **Create role**.
3. Open it → **Add permissions → Create inline policy → JSON** → name `ecs-exec`:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": [
         "ssmmessages:CreateControlChannel",
         "ssmmessages:CreateDataChannel",
         "ssmmessages:OpenControlChannel",
         "ssmmessages:OpenDataChannel"
       ],
       "Resource": "*"
     }]
   }
   ```

---

## 9. CloudWatch log group

**CloudWatch console → Logs → Log groups → Create log group**

| Setting | Value |
|---|---|
| Log group name | **`/ecs/marketplace-pilot`** |
| Retention | 3 months (90 days) |

All containers log here, separated by stream prefix (`jobs`, `api`, `worker`, `portal`).

---

## 10. ECS cluster

**ECS console → Clusters → Create cluster**

| Setting | Value |
|---|---|
| Cluster name | **`marketplace-pilot`** |
| Service Connect defaults → Default namespace | **`marketplace-pilot`** (creates a Cloud Map namespace; this is what makes `http://api:8000` resolvable) |
| Infrastructure | **AWS Fargate (serverless)** only |
| Monitoring | ✔ Container Insights (with enhanced observability, or standard) |

**Create**.

---

## 11. ECS task definitions

**ECS console → Task definitions → Create new task definition → Create new task definition with
JSON**. Delete the sample, paste one of the JSON documents below, **Create**. Repeat for all four.

In every document, replace:

* `ACCOUNT_ID` → your 12-digit account ID (appears several times),
* `us-east-2` → your region if different,
* `TAG` → the image tag from step 7,
* `SECRET_ARN` → the full secret ARN from step 5 (backend definitions only),
* `marketplace.example.com` → your domain.

> Use your editor's find-and-replace on the pasted text, then read it once before clicking
> **Create**. A wrong ARN fails only when a task starts.

### 11.1 `marketplace-jobs` — migrations, seeding and every one-off job

```json
{
  "family": "marketplace-jobs",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "512",
  "memory": "1024",
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
      {"name": "DATABASE_URL", "valueFrom": "SECRET_ARN:DATABASE_URL::"},
      {"name": "APP_DATABASE_URL", "valueFrom": "SECRET_ARN:APP_DATABASE_URL::"},
      {"name": "OIDC_CLIENT_SECRET", "valueFrom": "SECRET_ARN:OIDC_CLIENT_SECRET::"},
      {"name": "SNOWFLAKE_PRIVATE_KEY", "valueFrom": "SECRET_ARN:SNOWFLAKE_PRIVATE_KEY::"}
    ],
    "logConfiguration": {"logDriver": "awslogs", "options": {
      "awslogs-group": "/ecs/marketplace-pilot",
      "awslogs-region": "us-east-2",
      "awslogs-stream-prefix": "jobs"}}
  }]
}
```

Every variable in `.env.example` is required — the processes refuse to boot without one — which is
why placeholders such as `REDIS_URL` and the Snowflake values are present even though they are not
used (findings F3, F4). Change `PRODUCT_NAME` to your display name if you like; keep
`OIDC_ISSUER` as is (finding F2).

### 11.2 `marketplace-api`

Paste the **11.1 document again** and make exactly these changes before **Create**:

| Field | Change to |
|---|---|
| `"family"` | `"marketplace-api"` |
| `"cpu"` / `"memory"` | `"1024"` / `"2048"` |
| `"command": [...]` | **delete the whole line** (the image's default command runs uvicorn on port 8000) |
| `"awslogs-stream-prefix"` | `"api"` |

…and add these two properties inside the container object, e.g. right after `"essential": true,`:

```json
    "portMappings": [
      {"name": "api", "containerPort": 8000, "protocol": "tcp", "appProtocol": "http"}
    ],
    "healthCheck": {
      "command": ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/health')\""],
      "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 30
    },
```

The port mapping **name `api`** is what Service Connect publishes in step 16.

### 11.3 `marketplace-worker`

Paste 11.1 again and change:

| Field | Change to |
|---|---|
| `"family"` | `"marketplace-worker"` |
| `"cpu"` / `"memory"` | `"256"` / `"512"` |
| `"command"` | `["python", "-m", "services.worker.main"]` |
| `"awslogs-stream-prefix"` | `"worker"` |

### 11.4 `marketplace-portal`

The portal never touches the database, so it gets no secrets and only the variables it reads:

```json
{
  "family": "marketplace-portal",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "512",
  "memory": "1024",
  "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
  "executionRoleArn": "arn:aws:iam::ACCOUNT_ID:role/marketplace-pilot-exec",
  "taskRoleArn": "arn:aws:iam::ACCOUNT_ID:role/marketplace-pilot-task",
  "containerDefinitions": [{
    "name": "app",
    "image": "ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/marketplace-portal:TAG",
    "essential": true,
    "portMappings": [
      {"name": "portal", "containerPort": 3000, "protocol": "tcp", "appProtocol": "http"}
    ],
    "environment": [
      {"name": "PRODUCT_NAME", "value": "Enterprise Data & Agents Marketplace"},
      {"name": "TENANT_ID", "value": "TEN-DEMO"},
      {"name": "API_BASE_URL", "value": "http://api:8000/api/v1"},
      {"name": "OIDC_ISSUER", "value": "https://oidc.local/realms/marketplace"},
      {"name": "PORTAL_DEV_SUBJECT", "value": "PTY-0061"},
      {"name": "PORTAL_LOCALE", "value": "en"}
    ],
    "logConfiguration": {"logDriver": "awslogs", "options": {
      "awslogs-group": "/ecs/marketplace-pilot",
      "awslogs-region": "us-east-2",
      "awslogs-stream-prefix": "portal"}}
  }]
}
```

You now have four task definitions: `marketplace-jobs`, `marketplace-api`, `marketplace-worker`,
`marketplace-portal`, each at revision 1.

---

## 12. Run the first-deployment database jobs

These five runs create the schema, the application login and the seed catalog — the same sequence
`npm run dev` and CI run. Run them **one at a time, in order**, and do not continue past a failure.

**For each job:** ECS console → **Clusters → `marketplace-pilot` → Tasks tab → Run new task**

| Section | Setting | Value |
|---|---|---|
| Compute configuration | Compute options | **Launch type** → **FARGATE**, platform version LATEST |
| Deployment configuration | Application type | **Task** |
| | Task definition family / revision | `marketplace-jobs` / latest |
| | Desired tasks | 1 |
| Networking | VPC | `marketplace-pilot-vpc` |
| | Subnets | **the two private subnets only** (remove the public ones) |
| | Security group | **Use an existing security group** → `marketplace-worker` only (remove `default`) |
| | Public IP | **Off** |
| Container overrides | `app` → **Command override** | the value from the table below |

Click **Create**. Open the task; wait until **Last status = STOPPED** (refresh). Then check the
container's **Exit code** on the task page — it must be **0**. Read the output in the task's
**Logs** tab (or CloudWatch → `/ecs/marketplace-pilot`, streams `jobs/app/…`).

The command override field takes **comma-separated** values. Paste each exactly:

| # | What it does | Command override |
|---|---|---|
| 1 | Schema (as owner) + creates the `marketplace_app` login | `sh,-c,python scripts/migrate.py` |
| 2 | Catalog: taxonomies, rubrics, KPIs, products, agents | `sh,-c,python scripts/seed.py` |
| 3 | Platform sandbox, harvest, quality scoring | `sh,-c,python scripts/seed_platform.py && python scripts/harvest.py && python scripts/score.py` |
| 4 | Demo tier the agents answer from, evaluation, agent publication | `sh,-c,python scripts/seed_demo_tier.py && python scripts/demo_runner.py --verify && python scripts/evaluate.py && python scripts/publish_agents.py` |
| 5 | Meshes, divergence, signals and the value snapshot | `sh,-c,python scripts/mesh.py && python scripts/observe.py` |

> **If job 1 fails**, the cause is almost always networking or the secret — see
> [Troubleshooting](#22-troubleshooting). Fix it and re-run job 1; migrations are forward-only and
> safe to repeat.
>
> `mesh` and `observe` report findings **through their exit code** (finding F11). A non-zero exit
> from job 5 on a fresh seed should be read in the log, not ignored.

---

## 13. TLS certificate (ACM)

**ACM console (same region) → Request certificate → Request a public certificate**

| Setting | Value |
|---|---|
| Fully qualified domain name | your `DOMAIN`, e.g. `marketplace.example.com` |
| Validation method | **DNS validation** |
| Key algorithm | RSA 2048 |

**Request**, open the certificate:

* **Route 53 hosts the domain:** click **Create records in Route 53 → Create records**.
* **Another DNS provider:** add the shown **CNAME name → CNAME value** record there.

Wait for **Status = Issued** (minutes to ~30 min). Record the certificate ARN as `CERT_ARN`.

---

## 14. Cognito user pool

Because of finding F2 this is the only thing between the internet and the application.

**Cognito console → User pools → Create user pool**

| Setting | Value |
|---|---|
| Application type | **Traditional web application** |
| Name your application | `marketplace-alb` |
| Options for sign-in identifiers | ✔ **Email** |
| Self-registration | ☐ **leave unticked** — only people you invite can sign in |
| Required attributes for sign-up | `email` |
| Return URL | `https://marketplace.example.com/oauth2/idpresponse` (your domain + `/oauth2/idpresponse`, exactly) |

**Create user directory**. The wizard creates the user pool, an app client **with a client
secret**, and a Cognito domain. Then:

1. **User pool → Overview** → rename the pool to `marketplace-pilot` (optional) and note the
   **User pool ID**.
2. **Applications → App clients → `marketplace-alb` → Login pages → Edit**: confirm
   * Allowed callback URLs = `https://<DOMAIN>/oauth2/idpresponse`
   * OAuth 2.0 grant types = **Authorization code grant**
   * OpenID Connect scopes = **OpenID** and **Email** (others may stay)
   * Identity providers = **Cognito user pool**

   **Save changes**.
3. **Branding → Domain**: note the Cognito domain (e.g. `https://us-east-2xxxxxx.auth.us-east-2.amazoncognito.com`).
4. Recommended: **Authentication → Sign-in → Multi-factor authentication → Edit** → *Optional MFA*
   with **Authenticator apps**.

Do not create users yet — that is step 17.

To sign in with a corporate IdP (Entra ID, Okta, Google Workspace) instead of Cognito passwords,
add it under **Authentication → Social and external providers** as a SAML or OIDC provider and
enable it on the app client.

---

## 15. Target group and Application Load Balancer

### 15.1 Target group for the portal

**EC2 console → Load Balancing → Target Groups → Create target group**

| Setting | Value |
|---|---|
| Target type | **IP addresses** (Fargate tasks register by IP) |
| Name | `marketplace-pilot-portal` |
| Protocol / Port | HTTP / **3000** |
| IP address type | IPv4 |
| VPC | `marketplace-pilot-vpc` |
| Protocol version | HTTP1 |
| Health check path | `/` |
| Advanced health check → Success codes | `200-399` |

**Next** → do **not** register any targets (ECS does that) → **Create target group**.

### 15.2 The load balancer

**EC2 console → Load Balancers → Create load balancer → Application Load Balancer → Create**

| Section | Setting | Value |
|---|---|---|
| Basic | Name | `marketplace-pilot` |
| | Scheme | **Internet-facing** |
| | IP address type | IPv4 |
| Network mapping | VPC | `marketplace-pilot-vpc` |
| | Mappings | both AZs → **the public subnet** in each |
| Security groups | | `marketplace-alb` only (remove `default`) |
| Listeners and routing | Listener | Protocol **HTTPS**, port **443** |
| | Default action | Forward to `marketplace-pilot-portal` |
| Secure listener settings | Security policy | `ELBSecurityPolicy-TLS13-1-2-2021-06` (or the console's recommended TLS 1.3 policy) |
| | Default SSL/TLS certificate | From ACM → your certificate |

**Create load balancer**. The target group is still empty, so nothing is reachable yet — you add
the sign-in step before any portal task exists.

Record the ALB's **DNS name** (e.g. `marketplace-pilot-123456.us-east-2.elb.amazonaws.com`).

### 15.3 Load balancer attributes

Load balancer → **Attributes → Edit**:

| Attribute | Value | Why |
|---|---|---|
| Connection idle timeout | **300** seconds | `/api/events` is a long-lived stream (finding F10) |
| Drop invalid header fields | **On** | |

**Save changes**.

### 15.4 Put Cognito sign-in in front of everything

Load balancer → **Listeners and rules** → select **HTTPS:443** → **Manage rules → Edit rules**
(or select the **Default** rule → **Actions → Edit rule**):

1. Tick **Authenticate users** (pre-routing action) / *Add action → Authenticate*.
2. Identity provider: **Amazon Cognito**.
3. User pool: the pool from step 14; App client: `marketplace-alb`; User pool domain: the domain
   from step 14.
4. Advanced/authentication request settings: **Action on unauthenticated request = Authenticate
   (client reattempt)**; Scope = `openid email`; session timeout as you like (default 7 days).
5. Routing action: **Forward to target group → `marketplace-pilot-portal`**.
6. **Save changes**.

The listener's default rule must now show **Authenticate → Forward**. Do **not** add any rule or
HTTP listener that forwards to the portal without authentication.

Optional — redirect plain HTTP: **Add listener** → HTTP:80 → **Redirect to URL** → HTTPS, port
443, status 301 (needs the optional port-80 inbound rule on `marketplace-alb`).

Optional but recommended — **AWS WAF**: Load balancer → **Integrations → AWS WAF** → create a web
ACL with the managed rule group *Core rule set* (`AWSManagedRulesCommonRuleSet`).

---

## 16. ECS services: api, worker, portal

Create them **in this order** — the portal and worker resolve `api` only after the api service
has registered it in Service Connect.

**ECS console → Clusters → `marketplace-pilot` → Services tab → Create**. Common settings for all
three:

| Section | Setting | Value |
|---|---|---|
| Environment / Compute | Compute options | **Launch type** → FARGATE, LATEST |
| Deployment configuration | Application type | **Service** |
| | Deployment options → Deployment failure detection | ✔ Use the Amazon ECS deployment circuit breaker, ✔ Rollback on failure |
| Networking | VPC | `marketplace-pilot-vpc` |
| | Subnets | **the two private subnets only** |
| | Public IP | **Off** |
| Troubleshooting configuration | | ✔ **Turn on ECS Exec** (useful for step 18) |

### 16.1 `api`

| Setting | Value |
|---|---|
| Task definition | `marketplace-api`, latest revision |
| Service name | **`api`** |
| Desired tasks | 2 |
| Security group | existing → `marketplace-api` only |
| **Service Connect** | ✔ Turn on Service Connect → **Client and server** |
| | Namespace: `marketplace-pilot` |
| | **Add port mappings and applications**: Port alias `api` · Discovery = `api` · DNS = **`api`** · Port = **`8000`** |
| | Log collection: optional (turn on with the `/ecs/marketplace-pilot` group to log proxy traffic) |
| Load balancing | **None** (the API is not public — finding F9) |

**Create**. Wait until the service shows **2/2 tasks running** and the deployment is **Completed**.
The health status of each task (Tasks tab) should become **Healthy** within ~1 minute.

### 16.2 `worker`

| Setting | Value |
|---|---|
| Task definition | `marketplace-worker`, latest |
| Service name | **`worker`** |
| Desired tasks | 1 |
| Security group | `marketplace-worker` only |
| Service Connect | ✔ Turn on → **Client side only**, namespace `marketplace-pilot` |
| Load balancing | None |

### 16.3 `portal`

| Setting | Value |
|---|---|
| Task definition | `marketplace-portal`, latest |
| Service name | **`portal`** |
| Desired tasks | 2 |
| Security group | `marketplace-portal` only |
| Service Connect | ✔ Turn on → **Client side only**, namespace `marketplace-pilot` |
| **Load balancing** | ✔ Use load balancing → **Application Load Balancer** → **Use an existing load balancer** → `marketplace-pilot` |
| | Container to load balance: `app 3000:3000` |
| | Listener: **Use an existing listener** → `443:HTTPS` |
| | Target group: **Use an existing target group** → `marketplace-pilot-portal` |
| | Health check grace period: **60** seconds |

> If the console offers to add a *listener rule* while attaching the existing listener, decline —
> the default rule from step 15.4 already authenticates and forwards. A new rule without the
> authenticate action would bypass sign-in.

**Create**, then wait for **2/2 running** and, in EC2 → Target groups → `marketplace-pilot-portal`
→ **Targets**, two **healthy** IP targets.

---

## 17. DNS and first sign-in

### 17.1 Point your domain at the load balancer

* **Route 53:** Hosted zone → **Create record** → record name `marketplace` (or blank for the apex)
  → type **A** → ✔ **Alias** → *Alias to Application and Classic Load Balancer* → region →
  `marketplace-pilot` → **Create records**.
* **Other DNS providers:** create a **CNAME** from `marketplace.example.com` to the ALB DNS name
  from step 15.2.

### 17.2 Invite users

**Cognito → your user pool → User management → Users → Create user**

| Setting | Value |
|---|---|
| Invitation message | **Send an email invitation** |
| Email address | the person's email |
| ✔ Mark email address as verified | |
| Temporary password | **Generate a password** |

They receive a temporary password and set their own at first sign-in. Remember (F2): every person
you invite sees the marketplace as the same seeded party, `PTY-0061`.

---

## 18. Verify the deployment

| Check | How (console) | Expect |
|---|---|---|
| Services stable | ECS → cluster → Services | api 2/2, worker 1/1, portal 2/2; no tasks cycling |
| Targets healthy | EC2 → Target groups → `marketplace-pilot-portal` → Targets | 2 × healthy |
| Sign-in gate | open `https://<DOMAIN>` in a private window | redirected to the Cognito sign-in page |
| Catalog | sign in | products, agents, quality bands and owners on the landing page |
| Agent demo | open any agent → Demo | a curated question answers with citations |
| Live events | leave a page open > 2 min | no `504` in the browser console (idle timeout from 15.3) |
| API health (from inside) | CloudShell: see below | `{"status":"ok","tenant_id":"TEN-DEMO"}` |
| RLS not bypassed | Run a task like step 12 with override `sh,-c,pip install --user -q pytest && python scripts/run_tests.py tests/security` | exit code 0 |
| Logs clean | CloudWatch → `/ecs/marketplace-pilot` → streams `api/…`, `portal/…`, `worker/…` | no repeating tracebacks |

API health through ECS Exec, from **CloudShell** (copy an api task ID from the cluster's Tasks tab):

```bash
aws ecs execute-command --cluster marketplace-pilot --task <api-task-id> --container app \
  --interactive --command "python -c \"import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/v1/health').read())\""
```

(CloudShell may ask to install the Session Manager plugin the first time; follow its prompt.)

---

## 19. Scheduled jobs

The marketplace keeps itself current with recurring jobs. EventBridge Scheduler's console target
for ECS has no command-override box, so each schedule gets **its own small task definition** whose
command is the job.

### 19.1 One task definition per scheduled job

For each row: **Task definitions → Create new task definition with JSON**, paste the 11.1
(`marketplace-jobs`) document and change only `"family"`, `"command"` and
`"awslogs-stream-prefix"`:

| `family` | `command` | stream prefix |
|---|---|---|
| `marketplace-job-harvest` | `["python", "scripts/harvest.py"]` | `harvest` |
| `marketplace-job-score` | `["python", "scripts/score.py"]` | `score` |
| `marketplace-job-mesh` | `["python", "scripts/mesh.py"]` | `mesh` |
| `marketplace-job-observe` | `["python", "scripts/observe.py"]` | `observe` |
| `marketplace-job-demo` | `["python", "scripts/demo_runner.py", "--nightly"]` | `demo` |
| `marketplace-job-drill` | `["python", "scripts/rollback_drill.py"]` | `drill` |

### 19.2 Role for the scheduler

**IAM → Roles → Create role → Custom trust policy**, paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "scheduler.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
```

**Next** → attach nothing → name **`marketplace-pilot-scheduler`** → **Create role**. Then add an
inline policy `run-jobs` (substitute `ACCOUNT_ID` and region):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ecs:RunTask",
      "Resource": "arn:aws:ecs:us-east-2:ACCOUNT_ID:task-definition/marketplace-job-*"
    },
    {
      "Effect": "Allow",
      "Action": "ecs:TagResource",
      "Resource": "arn:aws:ecs:us-east-2:ACCOUNT_ID:task/marketplace-pilot/*"
    },
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::ACCOUNT_ID:role/marketplace-pilot-exec",
        "arn:aws:iam::ACCOUNT_ID:role/marketplace-pilot-task"
      ]
    }
  ]
}
```

### 19.3 The schedules

**Amazon EventBridge console → Scheduler → Schedules → Create schedule** — once per row:

| Schedule name | Pattern (UTC) | Task definition |
|---|---|---|
| `marketplace-pilot-harvest` | Rate-based: `1 hours` | `marketplace-job-harvest` |
| `marketplace-pilot-score` | Cron-based: `30 2 * * ? *` | `marketplace-job-score` |
| `marketplace-pilot-mesh` | Cron-based: `0 3 * * ? *` | `marketplace-job-mesh` |
| `marketplace-pilot-observe` | Rate-based: `5 minutes` | `marketplace-job-observe` |
| `marketplace-pilot-demo` | Cron-based: `0 4 * * ? *` | `marketplace-job-demo` |
| `marketplace-pilot-drill` | Cron-based: `0 5 ? * SUN *` | `marketplace-job-drill` |

For each:

1. **Specify schedule detail:** name from the table; Occurrence **Recurring schedule**; schedule
   type **Rate-based** or **Cron-based** as in the table; time zone **UTC**; Flexible time window
   **Off**. **Next**.
2. **Select target:** **Templated targets → Amazon ECS RunTask**.
   * ECS cluster `marketplace-pilot`; ECS task = the task definition from the table; revision
     *latest*; Task count 1.
   * Compute options: **Launch type FARGATE**, platform LATEST.
   * Subnets: the two **private** subnet IDs (comma-separated); Security groups:
     the `marketplace-worker` group ID; Auto-assign public IP **Off**.
   **Next**.
3. **Settings:** Action after completion **NONE**; Retry policy: retries **0** (the next run is the
   retry); Permissions → **Use existing role** → `marketplace-pilot-scheduler`. **Next → Create
   schedule**.

`evaluate` → `publish_agents` is **not** on a timer — it runs whenever agents change, as part of a
release (step 21).

---

## 20. Alerts

### 20.1 SNS topic

**SNS console → Topics → Create topic** → Standard → name `marketplace-pilot-alerts` → **Create**.
Then **Create subscription** → Protocol **Email** → your ops address → confirm the email you receive.

### 20.2 Alarm on every failed job (finding F11)

**EventBridge console → Rules → Create rule** (default event bus)

1. Name `marketplace-pilot-job-failed`, rule type **Rule with an event pattern**. **Next**.
2. Event source **AWS events**; Creation method **Custom pattern (JSON editor)**, paste:

   ```json
   {
     "source": ["aws.ecs"],
     "detail-type": ["ECS Task State Change"],
     "detail": {
       "lastStatus": ["STOPPED"],
       "group": [{"prefix": "family:marketplace-job"}],
       "containers": {"exitCode": [{"anything-but": 0}]}
     }
   }
   ```

   The prefix matches both the one-off `marketplace-jobs` and every scheduled `marketplace-job-*`.
3. Target: **AWS service → SNS topic → `marketplace-pilot-alerts`**. **Next → Create rule**.
4. Check **SNS → the topic → Access policy** contains a statement allowing
   `events.amazonaws.com` to `sns:Publish`; if not, **Edit** and add:

   ```json
   {
     "Effect": "Allow",
     "Principal": {"Service": "events.amazonaws.com"},
     "Action": "sns:Publish",
     "Resource": "arn:aws:sns:us-east-2:ACCOUNT_ID:marketplace-pilot-alerts"
   }
   ```

### 20.3 CloudWatch alarms

**CloudWatch → Alarms → Create alarm → Select metric**, each with action *notify
`marketplace-pilot-alerts`*:

| Metric | Condition |
|---|---|
| ApplicationELB → per-LB → `HTTPCode_Target_5XX_Count` (`marketplace-pilot`) | Sum ≥ 10 over 5 min |
| ApplicationELB → per-LB → `TargetResponseTime` | p95 > 2 s over 5 min |
| RDS → per-instance → `CPUUtilization` (`marketplace-pilot`) | Average > 80 % for 15 min |
| RDS → per-instance → `FreeStorageSpace` | < 2 GB |
| ECS → ClusterName, ServiceName → `CPUUtilization` (`api`) | Average > 80 % for 15 min |
| ApplicationELB → per-target-group → `HealthyHostCount` (`marketplace-pilot-portal`) | < 1 for 2 min |

---

## 21. Deploying a new version

When `main` has new commits and CI is green:

1. **Build** — CodeBuild → `marketplace-images` → **Start build**; note the new `TAG`.
2. **New task definition revisions** — for `marketplace-jobs`, `marketplace-api`,
   `marketplace-worker`, `marketplace-portal` and the six `marketplace-job-*`: select it → **Create
   new revision** → in the container, change the **Image URI** to the new tag → **Create**.
   (Or *Create new revision with JSON* and edit the tag.)
3. **Migrate first** — run a task as in step 12 with `marketplace-jobs` (new revision) and override
   `sh,-c,python scripts/migrate.py`. Exit code must be 0.
4. **If agents changed** — run override
   `sh,-c,python scripts/evaluate.py && python scripts/publish_agents.py`.
5. **Roll the services** — in this order **api → worker → portal**: Services → select →
   **Update service** → revision = latest → **Update**; wait for the deployment to complete before
   the next one.
6. **Schedules** use the latest revision automatically if you selected *latest*; otherwise edit each
   schedule's target revision.

**Rollback** = *Update service* back to the previous revision. **Migrations never roll back** —
keep them backwards-compatible.

To automate all of this from GitHub Actions without stored AWS keys, see
[`DEPLOY_AWS.md` §12](DEPLOY_AWS.md#12-continuous-deployment-from-github-actions).

---

## 22. Troubleshooting

Where to look first: **ECS → cluster → Tasks → (filter: Stopped) → task → *Stopped reason*** and
its **Logs** tab.

| Symptom | Likely cause | Fix |
|---|---|---|
| Task stops with `ResourceInitializationError: unable to pull secrets or registry auth` | No route to Secrets Manager / ECR, or the exec role cannot read the secret | Task is in the **private** subnets and the NAT gateway exists (step 2); `read-app-secret` policy on `marketplace-pilot-exec` names the exact secret ARN (step 8.1) |
| `CannotPullContainerError … not found` | Wrong `TAG` or account/region in the image URI | Compare the URI with the ECR repository's image list |
| `CannotStartContainerError` / exits at once with `KeyError` or "missing required" | A variable is missing from the task definition | All 21 environment entries + 4 secrets (backend), 6 entries (portal) |
| Migrate: `could not connect` / timeout | `marketplace-db` does not allow `marketplace-worker` on 5432, or the job ran with the wrong security group | Step 3 rules; step 12 security group |
| Migrate: `no pg_hba.conf entry … no encryption` | `?sslmode=require` missing from a URL | Edit the secret (step 5), re-run |
| Migrate: `password authentication failed for user "marketplace"` | `OWNER_PW` in the secret differs from RDS, or contains punctuation | RDS → Modify → new master password (letters/digits), update the secret |
| Migrate: `database "marketplace" does not exist` | *Initial database name* was left blank in step 4.4 | Connect via ECS Exec and `CREATE DATABASE marketplace`, or recreate the instance |
| Migrate: `extension "vector" is not available` | Engine version is not PostgreSQL 16 | Use RDS for PostgreSQL 16.x |
| Portal tasks running but targets **unhealthy** | Portal cannot reach the API, so `/` errors | Portal service has Service Connect **client** on; api service shows **Service Connect: api**; `marketplace-api` allows 8000 from `marketplace-portal`; check `portal/…` logs |
| `getaddrinfo ENOTFOUND api` in portal or worker logs | Service created before api registered, or Service Connect off | Update service → **Force new deployment** after api is running |
| Browser: `redirect_mismatch` from Cognito | Callback URL differs from `https://<DOMAIN>/oauth2/idpresponse` | App client → Login pages → fix the URL (scheme, host, path, no trailing slash) |
| Browser: `500` right after sign-in | App client has no secret, or OAuth code grant / `openid` scope not enabled | Recreate the app client as *Traditional web application* (has a secret); step 14.2 |
| Browser: `503` | No healthy targets | See the unhealthy-target row |
| Live updates stop after ~60 s (`504`) | ALB idle timeout still 60 s | Step 15.3 |
| CodeBuild: `Cannot connect to the Docker daemon` | **Privileged** flag not set | Edit project → Environment → ✔ Privileged |
| CodeBuild: `toomanyrequests` pulling `python`/`node` | Docker Hub anonymous rate limit | Add a pre_build command `sed -i 's#^FROM \(python\|node\):#FROM public.ecr.aws/docker/library/\1:#' Dockerfile.backend Dockerfile.portal`, or authenticate to Docker Hub |
| CodeBuild: portal build killed / `JavaScript heap out of memory` | Compute too small | 7 GB / 4 vCPU (step 7A.2) |
| CodeBuild: `denied: … not authorized to perform: ecr:…` | Service role lacks ECR permissions | Step 7A.3 |
| Scheduled job never runs | Scheduler role cannot `RunTask`/`PassRole`, or wrong subnets | Step 19.2; EventBridge Scheduler → schedule → *Monitoring*; CloudTrail `RunTask` errors |

---

## 23. Cost and tear-down

### 23.1 Indicative monthly cost (pilot, us-east-2)

About **USD 215–275 / month**: Fargate services ~110–130, scheduled jobs ~10–20, RDS db.t4g.small
~30–35, NAT gateway ~35–45, ALB ~20–25, the rest ~10–20. Breakdown and levers:
[`DEPLOY_AWS.md` §14](DEPLOY_AWS.md#14-indicative-monthly-cost--pilot-us-east-2). Check the
**AWS Pricing Calculator** for your region.

### 23.2 Tear-down (console, in this order)

1. **ECS → cluster → Services**: for `portal`, `worker`, `api` → **Delete service** (✔ Force delete).
2. **EventBridge Scheduler → Schedules**: delete the six `marketplace-pilot-*` schedules;
   **EventBridge → Rules**: delete `marketplace-pilot-job-failed`.
3. **EC2 → Load Balancers**: delete `marketplace-pilot`; **Target Groups**: delete
   `marketplace-pilot-portal`.
4. **RDS → Databases → `marketplace-pilot` → Modify** → untick *Deletion protection* → apply
   immediately; then **Actions → Delete** (keep a final snapshot if you want the data).
5. **ECS → Clusters → `marketplace-pilot` → Delete cluster**; **Task definitions** → deregister
   (optional); **Cloud Map → Namespaces** → delete `marketplace-pilot` if it remains.
6. **ECR**: delete both repositories. **CodeBuild**: delete `marketplace-images`.
7. **Secrets Manager**: delete `marketplace/pilot/app`. **Cognito**: delete the user pool (delete
   its domain first if asked). **ACM**: delete the certificate. **SNS**: delete the topic.
   **CloudWatch**: delete the log group and alarms.
8. **VPC → NAT gateways**: delete; **Elastic IPs**: release the NAT's address; then **Your VPCs →
   `marketplace-pilot-vpc` → Actions → Delete VPC** (removes subnets, route tables, security groups,
   endpoints).
9. **IAM → Roles**: delete `marketplace-pilot-exec`, `-task`, `-scheduler` and the CodeBuild role.
10. **DNS**: remove the record pointing at the ALB and the ACM validation CNAME.

The **NAT gateway** and the **RDS instance** are what keep billing if you stop half-way.

---

## What this deployment is — and is not

It is a governed, single-identity **pilot**: private network, encrypted database, secrets out of the
images, sign-in at the edge, scheduled freshness jobs, alerting on failed jobs. Before calling it
production, close the gaps in [`DEPLOY_AWS.md` §13](DEPLOY_AWS.md#13-before-calling-it-production) —
first among them per-user identity in the application (F2), then Multi-AZ, RDS Proxy, tracing and
infrastructure as code.

For a throwaway demo on a single EC2 instance with no public port, see
[`DEPLOY_AWS.md` Appendix A](DEPLOY_AWS.md#appendix-a--one-machine-demo-in-20-minutes).
