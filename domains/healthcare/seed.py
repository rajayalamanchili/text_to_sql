#!/usr/bin/env python3
"""Healthcare domain synthetic data seeder (T012, research.md §10).

Populates the `patients`/`encounters`/`conditions` tables defined in
`schema.sql` with data in Synthea's characteristic shape — realistic
demographics, ICD-10-style diagnosis codes, free-text clinical narrative —
without invoking the (Java-based) Synthea tool itself. See tech-stack.md's
"Healthcare synthetic data" row (amended 2026-07-29) for why: this
environment has no JVM, and a Python-native generator reuses the `Faker`
dependency already locked in for the fintech domain's seed script.

All data is synthetic; nothing here ever reads from or writes to a real
patient data source (FR-012, Constitution Principle VII). Connection
target is resolved the same way the engine resolves it
(`HEALTHCARE_DATABASE_URL`, see backend/src/config/domains.py) so this
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

MARITAL_STATUSES = ["S", "M", "D", "W", None]
ENCOUNTER_CLASSES = ["ambulatory", "emergency", "wellness", "inpatient", "urgentcare"]
ENCOUNTER_REASONS = [
    "routine checkup",
    "follow-up visit",
    "acute illness",
    "annual physical",
    "injury evaluation",
    "medication review",
]

# (ICD-10-style code, description) — matches the "diagnosis|icd|cpt" heuristic
# dictionary term (research.md §1) so `diagnosis_code`/`condition_code`
# classify as `sensitive_category`.
DIAGNOSIS_CODES = [
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("I10", "Essential (primary) hypertension"),
    ("J45.909", "Unspecified asthma, uncomplicated"),
    ("M54.5", "Low back pain"),
    ("F41.1", "Generalized anxiety disorder"),
    ("K21.9", "Gastro-esophageal reflux disease without esophagitis"),
    ("N39.0", "Urinary tract infection, site not specified"),
    ("J06.9", "Acute upper respiratory infection, unspecified"),
    ("E78.5", "Hyperlipidemia, unspecified"),
    ("M25.561", "Pain in right knee"),
    ("F32.9", "Major depressive disorder, single episode, unspecified"),
    ("R51.9", "Headache, unspecified"),
    ("I25.10", "Atherosclerotic heart disease of native coronary artery"),
    ("E66.9", "Obesity, unspecified"),
    ("J02.9", "Acute pharyngitis, unspecified"),
]

# Clinical-narrative sentence fragments, recombined per patient so
# `patient_notes` is genuine free text — large max length, low pattern
# repetition, no dictionary-term match — exercising the adversarial-column
# default (research.md §2, Scenario 3) rather than the diagnosis/notes
# keyword paths.
NOTE_OPENERS = [
    "Pt reports {symptom} for the past {duration}.",
    "Presents today with {symptom}, onset {duration} ago.",
    "Follow-up: {symptom} improving since last visit.",
    "Denies {symptom}; visit prompted by {reason}.",
]
NOTE_SYMPTOMS = [
    "intermittent chest discomfort",
    "lower back pain radiating to the left leg",
    "shortness of breath on exertion",
    "persistent cough",
    "fatigue and difficulty sleeping",
    "joint stiffness in the morning",
    "recurring headaches",
    "mild dizziness",
]
NOTE_DURATIONS = ["2 days", "1 week", "3 weeks", "several months", "6 hours"]
NOTE_CLOSERS = [
    "Discussed treatment options; pt agreeable to plan. Referred to {specialist} for further eval.",
    "Vitals stable. Advised lifestyle modification and scheduled follow-up in {duration}.",
    "Medication adjusted; pt counseled on side effects and adherence.",
    "No acute distress noted on exam. Will monitor and reassess at next visit.",
]
NOTE_SPECIALISTS = ["cardiology", "orthopedics", "neurology", "endocrinology", "pulmonology"]


@dataclass
class Patient:
    patient_id: int
    ssn: str
    first_name: str
    last_name: str
    birth_date: date
    gender: str
    marital_status: str | None
    address: str
    city: str
    state: str
    zip: str
    diagnosis_code: str | None
    notes: str


@dataclass
class Encounter:
    encounter_id: int
    patient_id: int
    encounter_date: datetime
    encounter_class: str
    provider_name: str
    reason_description: str


@dataclass
class Condition:
    patient_id: int
    encounter_id: int
    condition_code: str
    condition_description: str
    onset_date: date


def build_patient_notes(fake: Faker) -> str:
    symptom = random.choice(NOTE_SYMPTOMS)
    duration = random.choice(NOTE_DURATIONS)
    reason = random.choice(ENCOUNTER_REASONS)
    opener = random.choice(NOTE_OPENERS).format(symptom=symptom, duration=duration, reason=reason)
    closer = random.choice(NOTE_CLOSERS).format(
        specialist=random.choice(NOTE_SPECIALISTS), duration=random.choice(NOTE_DURATIONS)
    )
    return f"{opener} {closer} {fake.sentence(nb_words=10)}"


def generate_patients(fake: Faker, count: int) -> list[Patient]:
    patients = []
    for patient_id in range(1, count + 1):
        has_diagnosis = random.random() < 0.85
        code, _ = random.choice(DIAGNOSIS_CODES) if has_diagnosis else (None, None)
        patients.append(
            Patient(
                patient_id=patient_id,
                ssn=fake.unique.ssn(),
                first_name=fake.first_name(),
                last_name=fake.last_name(),
                birth_date=fake.date_of_birth(minimum_age=0, maximum_age=95),
                gender=random.choice(["M", "F"]),
                marital_status=random.choice(MARITAL_STATUSES),
                address=fake.street_address(),
                city=fake.city(),
                state=fake.state_abbr(),
                zip=fake.zipcode(),
                diagnosis_code=code,
                notes=build_patient_notes(fake),
            )
        )
    return patients


def generate_encounters(fake: Faker, patients: list[Patient]) -> list[Encounter]:
    encounters = []
    encounter_id = 1
    now = datetime.now(UTC)
    for patient in patients:
        for _ in range(random.randint(1, 4)):
            days_ago = random.randint(0, 5 * 365)
            encounters.append(
                Encounter(
                    encounter_id=encounter_id,
                    patient_id=patient.patient_id,
                    encounter_date=now - timedelta(days=days_ago),
                    encounter_class=random.choice(ENCOUNTER_CLASSES),
                    provider_name=f"Dr. {fake.last_name()}",
                    reason_description=random.choice(ENCOUNTER_REASONS),
                )
            )
            encounter_id += 1
    return encounters


def generate_conditions(encounters: list[Encounter]) -> list[Condition]:
    conditions = []
    for encounter in encounters:
        for _ in range(random.choices([0, 1, 2], weights=[0.4, 0.45, 0.15])[0]):
            code, description = random.choice(DIAGNOSIS_CODES)
            onset_date = encounter.encounter_date.date() - timedelta(days=random.randint(0, 30))
            conditions.append(
                Condition(
                    patient_id=encounter.patient_id,
                    encounter_id=encounter.encounter_id,
                    condition_code=code,
                    condition_description=description,
                    onset_date=onset_date,
                )
            )
    return conditions


def database_url(override: str | None) -> str:
    url = override or os.environ.get("HEALTHCARE_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "HEALTHCARE_DATABASE_URL is not set (see backend/src/config/domains.py "
            "for the expected {DOMAIN}_DATABASE_URL convention)"
        )
    return url


def already_seeded(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM patients")
        (count,) = cur.fetchone()
    return count > 0


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_SQL_PATH.read_text())


def clear_data(conn: psycopg.Connection) -> None:
    conn.execute("TRUNCATE TABLE conditions, encounters, patients RESTART IDENTITY CASCADE")
    conn.commit()


def insert_data(
    conn: psycopg.Connection,
    patients: list[Patient],
    encounters: list[Encounter],
    conditions: list[Condition],
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO patients (
                patient_id, patient_ssn, first_name, last_name, birth_date,
                gender, marital_status, address, city,
                state, zip, diagnosis_code, patient_notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    p.patient_id,
                    p.ssn,
                    p.first_name,
                    p.last_name,
                    p.birth_date,
                    p.gender,
                    p.marital_status,
                    p.address,
                    p.city,
                    p.state,
                    p.zip,
                    p.diagnosis_code,
                    p.notes,
                )
                for p in patients
            ],
        )
        cur.executemany(
            """
            INSERT INTO encounters (
                encounter_id, patient_id, encounter_date, encounter_class,
                provider_name, reason_description
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    e.encounter_id,
                    e.patient_id,
                    e.encounter_date,
                    e.encounter_class,
                    e.provider_name,
                    e.reason_description,
                )
                for e in encounters
            ],
        )
        cur.executemany(
            """
            INSERT INTO conditions (
                patient_id, encounter_id, condition_code,
                condition_description, onset_date
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (
                    c.patient_id,
                    c.encounter_id,
                    c.condition_code,
                    c.condition_description,
                    c.onset_date,
                )
                for c in conditions
            ],
        )
        # Keep the BIGSERIAL sequences ahead of our explicit ids so any
        # later manual insert doesn't collide with seeded rows.
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('patients', 'patient_id'), %s)",
            (len(patients),),
        )
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('encounters', 'encounter_id'), %s)",
            (len(encounters),),
        )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="Overrides HEALTHCARE_DATABASE_URL")
    parser.add_argument("--patients", type=int, default=300, help="Number of synthetic patients")
    parser.add_argument(
        "--seed", type=int, default=SEED_DEFAULT, help="RNG seed for reproducibility"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reseed even if the patients table already has rows",
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
                print("healthcare: patients table already seeded, skipping (use --force to reseed)")
                return
            clear_data(conn)

        patients = generate_patients(fake, args.patients)
        encounters = generate_encounters(fake, patients)
        conditions = generate_conditions(encounters)
        insert_data(conn, patients, encounters, conditions)

    print(
        f"healthcare: seeded {len(patients)} patients, "
        f"{len(encounters)} encounters, {len(conditions)} conditions"
    )


if __name__ == "__main__":
    main()
