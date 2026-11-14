# Maricel Pharmacy Management System

Internal pharmacy operations system built with Flask, SQLAlchemy, MySQL, HTML, CSS and vanilla JavaScript. It is a staff-only back office and point of sale: there is no public shop, customer registration or online ordering.

## Features

| Area | What it does |
|------|--------------|
| **Dashboard** | Role-aware. Owners see today's and month-to-date sales, gross profit, net income, inventory value, a 14-day sales chart, top products, stock alerts and recent activity. Cashiers see their own sales, quick actions, and stock and expiry alerts. |
| **Point of Sale** | Product grid with search and category filters; cart with quantity controls; senior citizen / PWD and custom discounts; optional sales tax; cash (with change), GCash, Maya and card payments; printable receipts. Stock is deducted **first-expiry-first-out** and expired batches are never sold. |
| **Sales history** | Filter by date range, status, payment method and cashier. Owners can void a sale, which restores its stock. Cashiers see only their own sales. |
| **Customers** | Records, notes (senior/PWD IDs, maintenance medicines), purchase history and lifetime spend. |
| **Products & categories** | Catalog with generic names, SKUs, selling units, shelf prices, reorder levels and Rx flags. |
| **Stock & batches** | Sellable, expired and on-hand quantities; batch expiry tracking; direct stock-in; adjustments (damage, expiry disposal, count correction); full movement history. |
| **Suppliers & purchases** | Purchase orders with line items. Receive a delivery now or later; receiving creates batches and updates stock and shelf prices. |
| **Expenses** | Monthly expense log by category with a spending breakdown. |
| **Reports** | Profit and loss (gross sales, discounts, cost of goods, gross profit, expenses, net income), daily sales chart, top products, payment methods, sales by staff, CSV export. |
| **Employees** | Staff records, login accounts (Owner / Cashier), activation and password resets. |
| **Audit logs & settings** | Trail of sign-ins, sales, stock and admin actions; pharmacy profile, receipt text, tax and discount rates, stock and expiry thresholds. |

Roles: **OWNER** has full access. **CASHIER** can use the dashboard, POS, their own sales history, customers and a read-only stock lookup.

The interface is responsive. The sidebar becomes an off-canvas menu on tablets and phones, tables become cards on phones, modals open as bottom sheets, and the POS stacks with a floating cart bar.

## Requirements

- Python 3.11 or newer
- MySQL 8.0 or compatible (SQLite also works for local testing)

## Local setup (Windows PowerShell)

```powershell
cd C:\Maricel-System
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env`: set a unique random `SECRET_KEY` and the MySQL `DATABASE_URL`. Create the database and a least-privilege account first:

```sql
CREATE DATABASE maricel_pharmacy_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'maricel_app'@'127.0.0.1' IDENTIFIED BY 'use-a-unique-secret';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP
  ON maricel_pharmacy_db.* TO 'maricel_app'@'127.0.0.1';
```

Apply the migrations and seed roles, then **either** load the demo data **or** create your own owner:

```powershell
python -m flask --app run.py db upgrade
python -m flask --app run.py seed-roles

# Option A: demo data (about 50 products, 2 months of sales, purchases, expenses, staff)
$env:DEMO_OWNER_PASSWORD = "choose-a-12+-char-password"
$env:DEMO_CASHIER_PASSWORD = "choose-another-12+-char-password"
python -m flask --app run.py seed-demo          # add --reset to rebuild it later

# Option B: a clean system
python -m flask --app run.py create-owner
python -m flask --app run.py create-employee    # creates a cashier

python -m flask --app run.py run
```

Open `http://127.0.0.1:5000`. Demo accounts are `owner`, `cashier` and `cashier2`. If the demo password variables are not set, `seed-demo` generates random passwords and prints them once.

## Deploying to Railway

The repository includes `start.sh`. On every deploy, `start.sh` runs `db upgrade` and `seed-roles`, loads demo data when `SEED_DEMO_DATA=true` (skipped if products already exist), and starts Gunicorn.

1. Create a Railway project from this GitHub repository and add a **MySQL** database service.
2. Set these variables on the web service:

   | Variable | Value |
   |----------|-------|
   | `DATABASE_URL` | `${{MySQL.MYSQL_URL}}` (Railway's `mysql://` URL is converted to PyMySQL automatically) |
   | `SECRET_KEY` | a long random string |
   | `SESSION_COOKIE_SECURE` | `true` |
   | `TRUST_PROXY` | `true` |
   | `BUSINESS_TIMEZONE` | `Asia/Manila` |
   | `SEED_DEMO_DATA` | `true` for a demo, `false` for a clean install |
   | `DEMO_OWNER_PASSWORD`, `DEMO_CASHIER_PASSWORD` | 12+ character passwords for the demo accounts |

3. In the service's **Settings → Deploy**, set the start command to `sh start.sh`, the health check path to `/health` (timeout 300 s, because the first deploy loads the demo data before the server starts), and the restart policy to *On failure*.
4. Generate a public domain under the service's **Networking** settings.

## Database and migrations

The schema covers roles, permissions, users, employees, categories, products, customers, suppliers, inventory, medicine batches, purchases and line items, sales and line items, payments, expenses, inventory logs, audit logs and system settings. Amounts use fixed decimals and timestamps are stored in UTC and shown in `BUSINESS_TIMEZONE`.

Create future revisions with `python -m flask --app run.py db migrate -m "Describe change"` and apply them with `db upgrade`. For quick local experiments, `init-db` creates tables directly; do not mix it with `db upgrade` on the same database.

## Security notes

- Werkzeug password hashes, Flask-Login sessions, CSRF protection on every form, safe redirects, and role/permission checks on every route.
- Deactivated users are signed out on their next request.
- Every change is written to the audit log in the same transaction as the change itself.
- Keep `.env` and database credentials out of version control. Use `SESSION_COOKIE_SECURE=true` over HTTPS.

## Tests

```powershell
python -m pytest
```

The suite covers authentication and permissions, FEFO stock deduction, overselling and short-cash rejection, discounts, voids, cashier data isolation, purchase receiving, stock adjustments, CRUD flows, employee account lifecycle, settings, reports, CSV export and the demo seeder.
