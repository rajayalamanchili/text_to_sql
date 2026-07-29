#!/usr/bin/env python3
"""Fintech domain synthetic data seeder (T013, research.md §10).

Populates the `customers`/`accounts`/`transactions`/`claims` tables defined
in `schema.sql` with Faker-generated demographic/contact data and a
PaySim-style transaction pattern generator (transaction types, balances,
and a small fraud rate mirroring PaySim's `type`/`amount`/`oldbalanceOrg`/
`newbalanceOrig`/`isFraud` columns — research.md §10).

All data is synthetic; nothing here ever reads from or writes to a real
account or transaction data source (FR-012, Constitution Principle VII).
Connection target is resolved the same way the engine resolves it
(`FINTECH_DATABASE_URL`, see backend/src/config/domains.py) so this
script and the running engine always point at the same database.
"""

from __future__ import annotations

import argparse
import os
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg
from faker import Faker

SEED_DEFAULT = 20260729

SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"

TENANT_IDS = [f"tenant-{i:03d}" for i in range(1, 6)]
ACCOUNT_TYPES = ["checking", "savings", "credit"]
CLAIM_STATUSES = ["submitted", "under_review", "approved", "denied", "paid"]

# PaySim's canonical transaction types (research.md §10).
TRANSACTION_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]
FRAUD_RATE = 0.01  # PaySim's fraud rate is well under 1%; kept illustrative.

# Ambiguous column (Scenario 2): a small, fixed set of memo patterns —
# deliberately LOW cardinality (unlike healthcare's high-entropy free text)
# so the heuristic classifier sees repeated patterns, not unique narrative.
TRANSACTION_NOTES = [
    "Grocery purchase",
    "ATM withdrawal",
    "Online transfer",
    "Utility payment",
    "Restaurant charge",
    "Subscription renewal",
    "Salary deposit",
    "Loan payment",
    None,  # many real transactions carry no memo at all
]


@dataclass
class Customer:
    customer_id: int
    tenant_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    city: str
    state: str
    zip: str
    created_at: datetime


@dataclass
class Account:
    account_id: int
    customer_id: int
    account_type: str
    balance: float
    opened_date: date


@dataclass
class Transaction:
    transaction_id: int
    account_id: int
    transaction_type: str
    amount: float
    balance_before: float
    balance_after: float
    is_fraud: bool
    transaction_date: datetime
    notes: str | None


@dataclass
class Claim:
    claim_id: int
    customer_id: int
    tenant_id: str
    member_ssn: str
    claim_amount: float
    claim_date: date
    claim_status: str


def generate_customers(fake: Faker, count: int) -> list[Customer]:
    customers = []
    now = datetime.now(UTC)
    for customer_id in range(1, count + 1):
        created_days_ago = random.randint(30, 5 * 365)
        customers.append(
            Customer(
                customer_id=customer_id,
                tenant_id=random.choice(TENANT_IDS),
                first_name=fake.first_name(),
                last_name=fake.last_name(),
                email=fake.unique.email(),
                phone=fake.phone_number(),
                address=fake.street_address(),
                city=fake.city(),
                state=fake.state_abbr(),
                zip=fake.zipcode(),
                created_at=now - timedelta(days=created_days_ago),
            )
        )
    return customers


def generate_accounts(customers: list[Customer]) -> list[Account]:
    accounts = []
    account_id = 1
    for customer in customers:
        for _ in range(random.randint(1, 2)):
            opened_days_ago = random.randint(0, 4 * 365)
            accounts.append(
                Account(
                    account_id=account_id,
                    customer_id=customer.customer_id,
                    account_type=random.choice(ACCOUNT_TYPES),
                    balance=round(random.uniform(0, 25_000), 2),
                    opened_date=(datetime.now(UTC) - timedelta(days=opened_days_ago)).date(),
                )
            )
            account_id += 1
    return accounts


def generate_transactions(accounts: list[Account]) -> list[Transaction]:
    transactions = []
    transaction_id = 1
    now = datetime.now(UTC)
    for account in accounts:
        balance = account.balance
        for _ in range(random.randint(3, 12)):
            transaction_type = random.choice(TRANSACTION_TYPES)
            amount = round(random.uniform(5, 3_000), 2)
            balance_before = balance
            if transaction_type in ("CASH_IN",):
                balance_after = balance_before + amount
            else:
                balance_after = balance_before - amount
            balance = balance_after
            days_ago = random.randint(0, 2 * 365)
            transactions.append(
                Transaction(
                    transaction_id=transaction_id,
                    account_id=account.account_id,
                    transaction_type=transaction_type,
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    is_fraud=random.random() < FRAUD_RATE,
                    transaction_date=now - timedelta(days=days_ago),
                    notes=random.choice(TRANSACTION_NOTES),
                )
            )
            transaction_id += 1
    return transactions


def generate_claims(fake: Faker, customers: list[Customer], count: int) -> list[Claim]:
    claims = []
    for claim_id in range(1, count + 1):
        customer = random.choice(customers)
        claim_days_ago = random.randint(0, 3 * 365)
        claims.append(
            Claim(
                claim_id=claim_id,
                customer_id=customer.customer_id,
                tenant_id=customer.tenant_id,
                member_ssn=fake.ssn(),
                claim_amount=round(random.uniform(50, 10_000), 2),
                claim_date=(datetime.now(UTC) - timedelta(days=claim_days_ago)).date(),
                claim_status=random.choice(CLAIM_STATUSES),
            )
        )
    return claims


def database_url(override: str | None) -> str:
    url = override or os.environ.get("FINTECH_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "FINTECH_DATABASE_URL is not set (see backend/src/config/domains.py "
            "for the expected {DOMAIN}_DATABASE_URL convention)"
        )
    return url


def already_seeded(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM customers")
        (count,) = cur.fetchone()
    return count > 0


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_SQL_PATH.read_text())


def clear_data(conn: psycopg.Connection) -> None:
    conn.execute(
        "TRUNCATE TABLE claims, transactions, accounts, customers RESTART IDENTITY CASCADE"
    )
    conn.commit()


def insert_data(
    conn: psycopg.Connection,
    customers: list[Customer],
    accounts: list[Account],
    transactions: list[Transaction],
    claims: list[Claim],
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO customers (
                customer_id, tenant_id, first_name, last_name, email, phone,
                address, city, state, zip, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    c.customer_id,
                    c.tenant_id,
                    c.first_name,
                    c.last_name,
                    c.email,
                    c.phone,
                    c.address,
                    c.city,
                    c.state,
                    c.zip,
                    c.created_at,
                )
                for c in customers
            ],
        )
        cur.executemany(
            """
            INSERT INTO accounts (
                account_id, customer_id, account_type, balance, opened_date
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (a.account_id, a.customer_id, a.account_type, a.balance, a.opened_date)
                for a in accounts
            ],
        )
        cur.executemany(
            """
            INSERT INTO transactions (
                transaction_id, account_id, transaction_type, amount,
                balance_before, balance_after, is_fraud, transaction_date, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    t.transaction_id,
                    t.account_id,
                    t.transaction_type,
                    t.amount,
                    t.balance_before,
                    t.balance_after,
                    t.is_fraud,
                    t.transaction_date,
                    t.notes,
                )
                for t in transactions
            ],
        )
        cur.executemany(
            """
            INSERT INTO claims (
                claim_id, customer_id, tenant_id, member_ssn, claim_amount,
                claim_date, claim_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    c.claim_id,
                    c.customer_id,
                    c.tenant_id,
                    c.member_ssn,
                    c.claim_amount,
                    c.claim_date,
                    c.claim_status,
                )
                for c in claims
            ],
        )
        for table, id_column, count in (
            ("customers", "customer_id", len(customers)),
            ("accounts", "account_id", len(accounts)),
            ("transactions", "transaction_id", len(transactions)),
            ("claims", "claim_id", len(claims)),
        ):
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{id_column}'), %s)",
                (count,),
            )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="Overrides FINTECH_DATABASE_URL")
    parser.add_argument("--customers", type=int, default=150, help="Number of synthetic customers")
    parser.add_argument("--claims", type=int, default=100, help="Number of synthetic claims")
    parser.add_argument(
        "--seed", type=int, default=SEED_DEFAULT, help="RNG seed for reproducibility"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reseed even if the customers table already has rows",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    fake = Faker()
    Faker.seed(args.seed)

    with psycopg.connect(database_url(args.database_url)) as conn:
        apply_schema(conn)
        conn.commit()

        if already_seeded(conn):
            if not args.force:
                print("fintech: customers table already seeded, skipping (use --force to reseed)")
                return
            clear_data(conn)

        customers = generate_customers(fake, args.customers)
        accounts = generate_accounts(customers)
        transactions = generate_transactions(accounts)
        claims = generate_claims(fake, customers, args.claims)
        insert_data(conn, customers, accounts, transactions, claims)

    print(
        f"fintech: seeded {len(customers)} customers, {len(accounts)} accounts, "
        f"{len(transactions)} transactions, {len(claims)} claims"
    )


if __name__ == "__main__":
    main()
