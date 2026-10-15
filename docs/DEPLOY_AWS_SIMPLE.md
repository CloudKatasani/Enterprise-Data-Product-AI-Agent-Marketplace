# Hosting the marketplace on AWS — the low-cost prototype (one EC2 server)

**One EC2 instance. One command.** The marketplace runs on the server exactly as it runs on a
laptop — with Docker — so there is no RDS, ECS, ECR, load balancer, Cognito or Secrets Manager to
set up or pay for. S3 is optional, for off-server backups.

About 30–40 minutes, most of it waiting. About **USD 15–35 a month** running 24×7, and much less
if you stop the server when nobody is using it.

| You need | You do **not** need |
|---|---|
| An AWS account and a web browser | A domain name (a free `<ip>.sslip.io` address with real HTTPS works out of the box) |
| | Docker, the AWS CLI or anything on your own computer |
| | Any AWS service other than EC2 (and, optionally, S3) |

Everything the server runs is in the repository under [`deploy/single-host/`](../deploy/single-host/).

> This is a prototype set-up: one server, one shared sign-in password. For a resilient production
> deployment see [`DEPLOY_AWS_CONSOLE.md`](DEPLOY_AWS_CONSOLE.md).

---

## What runs on the server

```
 Browser ──HTTPS (443)──► EC2 instance · Ubuntu 24.04 · Docker Compose
                          ┌────────────────────────────────────────────────┐
                          │ caddy     free HTTPS certificate + password     │
                          │   └─► portal   (Next.js)                         │
                          │         └─► api   (FastAPI) ◄── worker           │
                          │               └─► postgres 16 + pgvector         │
                          │ cron: harvest · score · mesh · observe · demo    │
                          │       · nightly database backup ──► S3 (optional)│
                          └────────────────────────────────────────────────┘
```

Only ports 80 and 443 (and SSH, restricted to you) are open. The database, API and portal are not
reachable from the internet.

---

## Step 1 — Launch the EC2 instance

AWS console → **EC2** → check the **region** (top right) → **Launch instance**.

| Setting | Value |
|---|---|
| Name | `marketplace` |
| Application and OS image | **Ubuntu** → **Ubuntu Server 24.04 LTS (HVM), SSD Volume Type**, architecture **64-bit (x86)** |
| Instance type | **t3a.medium** (2 vCPU, 4 GB) — recommended. See [choosing a size](#choosing-an-instance-size) for cheaper options |
| Key pair | **Create new key pair** → name `marketplace`, RSA, `.pem` → it downloads. (Only needed if you SSH from your own computer.) |
| Network settings → **Edit** | VPC: default · Subnet: no preference · **Auto-assign public IP: Enable** |
| Firewall (security groups) | **Create security group**, name `marketplace`, with three rules: |
| | • **SSH**, TCP 22, Source **My IP** *(see the note below)* |
| | • **HTTP**, TCP 80, Source **Anywhere** (0.0.0.0/0) — needed to issue the free certificate |
| | • **HTTPS**, TCP 443, Source **Anywhere** (0.0.0.0/0) |
| Configure storage | **30 GiB**, **gp3** |
| Advanced details → IAM instance profile | leave empty — unless you want S3 backups ([step 6](#step-6--optional-backups-to-s3)) |

**Launch instance**. Wait until **Instance state = Running** and **Status check = 2/2 checks passed**
(1–3 minutes). Note the **Public IPv4 address**.

> **SSH and the browser terminal.** *EC2 Instance Connect* (the in-browser terminal used in step 2)
> connects from AWS's own address range, not from *My IP*. Either use your own SSH client
> (`ssh -i marketplace.pem ubuntu@<public-ip>`), or temporarily change the SSH rule source to
> **Anywhere** while you work and set it back to **My IP** afterwards. Password log-in is disabled
> on Ubuntu images; only your key works.

## Step 2 — Connect to it

Either:

* **In the browser:** select the instance → **Connect** → **EC2 Instance Connect** → **Connect**; or
* **From your computer:** `ssh -i marketplace.pem ubuntu@<public-ip>`
  (on macOS/Linux run `chmod 400 marketplace.pem` first).

## Step 3 — Install (one command)

Paste into the terminal:

```bash
sudo apt-get update -y && sudo apt-get install -y git
sudo git clone https://github.com/CloudKatasani/Enterprise-Data-Product-AI-Agent-Marketplace.git /opt/marketplace
sudo /opt/marketplace/deploy/single-host/install.sh
```

> If the repository is private, clone with a GitHub personal access token:
> `https://<token>@github.com/CloudKatasani/…`.

The installer, in order:

1. adds a 4 GB swap file (so the build fits in memory),
2. installs Docker,
3. writes `deploy/single-host/.env` — random database passwords and a random sign-in password,
4. **builds the application images on the server** (5–15 minutes the first time; no registry),
5. starts PostgreSQL, creates the schema and the application login, seeds the catalog, demo data
   and agents — the same sequence `npm run dev` and CI run,
6. starts the API, worker, portal and Caddy (HTTPS + password),
7. schedules the recurring jobs and a nightly database backup in `/etc/cron.d/marketplace`.

It ends by printing:

```
URL:      https://3-140-25-17.sslip.io
User:     admin
Password: 9f2c4e…
```

These are saved in `/root/marketplace-credentials.txt` (`sudo cat /root/marketplace-credentials.txt`).

## Step 4 — Open it

Open the URL in your browser. The first visit can take ~30 seconds while the free Let's Encrypt
certificate is issued. Enter the user name and password; the marketplace landing page appears with
the seeded data products, agents and quality scores. Open any agent → **Demo** to see a curated
question answered with citations.

Everyone who signs in acts as the same seeded user (`PTY-0061`) — the application does not have
per-user sign-in yet ([`DEPLOY_AWS.md`](DEPLOY_AWS.md) finding F2), so share the password only with
people who should see the prototype.

**The prototype is hosted.** Everything below is optional.

---

## Step 5 — Save money: stop it when nobody is using it

EC2 bills the instance **only while it is running**. The disk (~USD 2.40/month for 30 GB) is billed
always.

* **Stop:** EC2 → instance → **Instance state → Stop instance**. Data is kept.
* **Start:** **Instance state → Start instance**. Everything starts by itself in 1–2 minutes.

Without an Elastic IP the server gets a **new public IP after every start**. That is handled for
you: at boot the server moves its `sslip.io` address to the new IP. Find the new address in
`/root/marketplace-credentials.txt`, or take the new *Public IPv4 address* from the console and
replace the dots with dashes: `3.15.7.22` → `https://3-15-7-22.sslip.io`.

If you want an address that never changes, either use your own domain (below) and update its DNS
record after a start, or allocate an **Elastic IP** (EC2 → Elastic IPs → Allocate → Associate) —
about USD 3.60/month, the same as the automatic public IP it replaces.

> Never choose **Terminate** unless you want to delete the server and its data.

## Step 6 — Optional: backups to S3

Every night at 01:15 UTC the database is dumped to `/var/backups/marketplace/` on the server (7
days kept). To keep a copy off the server too:

1. **S3 → Create bucket** → name e.g. `marketplace-backups-<your-account-id>`, same region, keep
   **Block all public access** on → **Create bucket**.
   Then bucket → **Management → Create lifecycle rule** → *Expire current versions of objects*
   after **30 days**, so backups do not grow forever.
2. **IAM → Roles → Create role** → AWS service → **EC2** → Next → (no managed policy) → name
   `marketplace-ec2` → **Create role**. Open it → **Add permissions → Create inline policy → JSON**:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "s3:PutObject",
       "Resource": "arn:aws:s3:::marketplace-backups-<your-account-id>/backups/*"
     }]
   }
   ```

   Name it `write-backups`. (IAM itself is free; this role only lets the server write backups.)
3. **EC2 → instance → Actions → Security → Modify IAM role** → `marketplace-ec2` → **Update IAM
   role**.
4. On the server:

   ```bash
   cd /opt/marketplace/deploy/single-host
   sudo snap install aws-cli --classic
   sudo sed -i 's#^BACKUP_S3_BUCKET=.*#BACKUP_S3_BUCKET=marketplace-backups-<your-account-id>#' .env
   grep -q '^BACKUP_S3_BUCKET=' .env || echo 'BACKUP_S3_BUCKET=marketplace-backups-<your-account-id>' | sudo tee -a .env
   sudo ./backup.sh     # test it: the file should appear in the bucket under backups/
   ```

   (Or pass `BACKUP_S3_BUCKET=…` to the installer on a fresh install.)

S3 cost for this is cents per month.

**Restore** a backup (from the server folder or downloaded from S3):

```bash
cd /opt/marketplace/deploy/single-host
gunzip -c marketplace-YYYY-MM-DD.sql.gz | sudo docker compose exec -T postgres psql -U marketplace marketplace
```

---

## Optional settings at install time

Put them before the install command, e.g.
`sudo ADMIN_USER=demo ADMIN_PASSWORD='S3cret-pass' /opt/marketplace/deploy/single-host/install.sh`

| Variable | Default | Meaning |
|---|---|---|
| `SITE_ADDRESS` | `<public-ip>.sslip.io` | Your own host name, e.g. `marketplace.example.com` — create its DNS **A record → public IP first** |
| `ADMIN_USER` | `admin` | Sign-in user name |
| `ADMIN_PASSWORD` | random | Sign-in password |
| `PRODUCT_NAME` | `Enterprise Data & Agents Marketplace` | Display name in the portal |
| `BACKUP_S3_BUCKET` | empty | Also copy nightly backups to this bucket (step 6) |

## Use your own domain later

1. At your DNS provider create an **A record** `marketplace.example.com → <public IP>`.
2. On the server:

   ```bash
   cd /opt/marketplace/deploy/single-host
   sudo sed -i 's#^SITE_ADDRESS=.*#SITE_ADDRESS=marketplace.example.com#; s#^PORTAL_BASE_URL=.*#PORTAL_BASE_URL=https://marketplace.example.com#' .env
   sudo docker compose up -d --force-recreate caddy portal
   ```

## Change the sign-in password

```bash
cd /opt/marketplace/deploy/single-host
HASH=$(sudo docker compose exec -T caddy caddy hash-password --plaintext 'NEW-PASSWORD')
sudo sed -i "s#^BASIC_AUTH_HASH=.*#BASIC_AUTH_HASH='$HASH'#" .env
sudo docker compose up -d --force-recreate caddy
```

---

## Day-to-day commands

Run from `/opt/marketplace/deploy/single-host`:

| Task | Command |
|---|---|
| Status | `sudo docker compose ps` |
| Logs | `sudo docker compose logs -f --tail 100` (or `… logs -f api`) |
| Recurring-job log | `tail -f /var/log/marketplace-jobs.log` |
| Run a job now | `sudo ./run-job.sh python scripts/harvest.py` |
| Restart everything | `sudo docker compose restart` |
| **Deploy the latest code** | `sudo ./update.sh` — pull, build, migrate, republish agents, restart (a few seconds of downtime) |
| Back up now | `sudo ./backup.sh` |
| Disk space | `df -h /` and `sudo docker system df` |

**Recurring jobs (UTC):** `observe` every 5 min, `harvest` hourly, `score` 02:30, `mesh` 03:00,
`demo_runner --nightly` 04:00, `rollback_drill` Sundays 05:00, backup 01:15. They only run while
the instance is running. `mesh` and `observe` report findings through a non-zero exit code — that
is information to read in the log, not a fault.

---

## Choosing an instance size

Prices are approximate on-demand rates in us-east-1/us-east-2; check the EC2 pricing page for your
region.

| Type | vCPU / RAM | ~USD / month 24×7 | Notes |
|---|---|---|---|
| t3a.small | 2 / 2 GB | ~14 | Cheapest that works. The first build is slow (it leans on swap); fine for 1–3 users |
| **t3a.medium** | 2 / 4 GB | **~27** | **Recommended** — comfortable build and runtime |
| t4g.medium | 2 / 4 GB (ARM/Graviton) | ~24 | Cheaper. Choose the **64-bit (Arm)** Ubuntu image. All base images are multi-architecture, but the guide's default is x86 |
| t3.medium | 2 / 4 GB | ~30 | If `t3a` is not offered in your region |

Plus, always: 30 GB gp3 disk **~2.40**, public IPv4 address **~3.60** (only while running, unless
it is an Elastic IP).

| Usage pattern (t3a.medium) | ~USD / month |
|---|---|
| Running 24×7 | ~33 |
| Business hours only (≈ 50 h/week) | ~12 |
| Stopped (disk only) | ~2.40 |

New AWS accounts may have free-tier or credit coverage that brings this lower.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Browser: connection refused / times out | Security group must allow **80 and 443** from Anywhere; instance must be **Running**; `sudo docker compose ps` should show `caddy` up |
| Browser: certificate warning on first visit | Wait a minute and reload. Still failing → `sudo docker compose logs caddy`. Ports 80/443 must be open and the name must match the *current* public IP (after a stop/start see step 5). `sslip.io` is a free shared service — if Let's Encrypt rate-limits it, use your own domain |
| EC2 Instance Connect: "failed to connect" | SSH rule source is *My IP*; see the note in step 1, or use your own SSH client |
| Install stopped during "Building images" with `Killed` | Out of memory — use t3a.medium, or re-run (safe; Docker caches finished layers) |
| `429 Too Many Requests` pulling images | Docker Hub anonymous limit; wait an hour or `sudo docker login` with a free Docker Hub account, then re-run the installer |
| Installer stopped at a seeding step | Read the error just above it, fix, and re-run the installer. Seeding counts as done only after every step succeeded |
| Error page after signing in | `sudo docker compose logs api portal --tail 200`; `api` should be `healthy` in `sudo docker compose ps` |
| Disk full | `sudo docker system prune -f` (removes old images), or EC2 → Volumes → Modify → larger size, then `sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/nvme0n1p1` |
| S3 backup: `AccessDenied` / `Unable to locate credentials` | IAM role attached to the instance (step 6.3) and the bucket name in the policy matches `.env` |

---

## Removing everything

1. EC2 → instance → **Instance state → Terminate** (deletes the server and its disk).
2. EC2 → **Elastic IPs** → release it, if you allocated one.
3. EC2 → **Security groups** → delete `marketplace`; **Key pairs** → delete `marketplace`.
4. If you used S3: empty and delete the bucket; IAM → delete the `marketplace-ec2` role.

---

## Compared with the full AWS deployment

| | This guide | [`DEPLOY_AWS_CONSOLE.md`](DEPLOY_AWS_CONSOLE.md) |
|---|---|---|
| AWS services | EC2 (+ optional S3) | ~12 (VPC, RDS, ECS, ECR, ALB, Cognito, ACM, …) |
| Set-up time | ~30–40 min | 2–3 h |
| Cost | ~USD 12–35/month | ~USD 215–275/month |
| Database | PostgreSQL in a container on the server, nightly dump (+ S3) | RDS, managed backups, Multi-AZ option |
| Sign-in | one shared password | Cognito accounts / corporate SSO |
| Availability | one server | several tasks across two AZs |

Moving up later is straightforward: both use the same Dockerfiles and environment variables, and
a `pg_dump` from this server restores into RDS.
