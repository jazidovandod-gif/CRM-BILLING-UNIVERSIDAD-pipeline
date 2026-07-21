"""Auditoría independiente y reproducible de los 18 CSV del proyecto.

El script no modifica los datos de origen. Produce un JSON con:

- perfil estructural y validación contra ``manifest.json``;
- PK, FK y cardinalidades;
- reglas semánticas de University, Billing y CRM;
- reconciliaciones financieras a precisión de centavos;
- cruces entre dominios;
- señales cuantitativas de generación aleatoria/independiente.

Uso:
    python src/comprehensive_data_audit.py
    python src/comprehensive_data_audit.py --output docs/analisis-datos-resultados.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifest.json"
DEFAULT_AS_OF = "2026-07-21"

TABLE_CONFIG: dict[tuple[str, str], dict[str, list[str]]] = {
    ("university", "semesters"): {
        "pk": ["semester_id"],
        "dates": ["start_date", "end_date"],
        "numeric": ["year", "half"],
    },
    ("university", "professors"): {
        "pk": ["professor_id"],
        "dates": ["hired_at"],
        "numeric": [],
    },
    ("university", "students"): {
        "pk": ["student_id"],
        "dates": ["birth_date", "enrolled_at"],
        "numeric": [],
    },
    ("university", "courses"): {
        "pk": ["course_id"],
        "dates": [],
        "numeric": ["credits"],
    },
    ("university", "enrollments"): {
        "pk": ["enrollment_id"],
        "dates": ["enrolled_at"],
        "numeric": [],
    },
    ("university", "grades"): {
        "pk": ["grade_id"],
        "dates": ["graded_at"],
        "numeric": ["score", "weight"],
    },
    ("billing", "customers"): {
        "pk": ["customer_id"],
        "dates": ["created_at"],
        "numeric": [],
    },
    ("billing", "products"): {
        "pk": ["product_id"],
        "dates": [],
        "numeric": ["monthly_price"],
    },
    ("billing", "subscriptions"): {
        "pk": ["subscription_id"],
        "dates": ["start_date", "end_date"],
        "numeric": [],
    },
    ("billing", "invoices"): {
        "pk": ["invoice_id"],
        "dates": ["issued_at", "due_at"],
        "numeric": ["total"],
    },
    ("billing", "invoice_items"): {
        "pk": ["invoice_item_id"],
        "dates": [],
        "numeric": ["quantity", "unit_price", "line_total"],
    },
    ("billing", "payments"): {
        "pk": ["payment_id"],
        "dates": ["paid_at"],
        "numeric": ["amount"],
    },
    ("crm", "accounts"): {
        "pk": ["account_id"],
        "dates": ["created_at"],
        "numeric": ["annual_revenue", "employees"],
    },
    ("crm", "contacts"): {
        "pk": ["contact_id"],
        "dates": ["created_at"],
        "numeric": [],
    },
    ("crm", "leads"): {
        "pk": ["lead_id"],
        "dates": ["created_at"],
        "numeric": ["score"],
    },
    ("crm", "opportunities"): {
        "pk": ["opportunity_id"],
        "dates": ["close_date", "created_at"],
        "numeric": ["amount"],
    },
    ("crm", "opportunity_contacts"): {
        "pk": ["opportunity_id", "contact_id"],
        "dates": [],
        "numeric": [],
    },
    ("crm", "activities"): {
        "pk": ["activity_id"],
        "dates": ["occurred_at"],
        "numeric": [],
    },
}

FK_CONFIG = [
    ("university", "courses", "professor_id", "university", "professors", "professor_id"),
    ("university", "enrollments", "student_id", "university", "students", "student_id"),
    ("university", "enrollments", "course_id", "university", "courses", "course_id"),
    ("university", "enrollments", "semester_id", "university", "semesters", "semester_id"),
    ("university", "grades", "enrollment_id", "university", "enrollments", "enrollment_id"),
    ("billing", "subscriptions", "customer_id", "billing", "customers", "customer_id"),
    ("billing", "subscriptions", "product_id", "billing", "products", "product_id"),
    ("billing", "invoices", "customer_id", "billing", "customers", "customer_id"),
    ("billing", "invoice_items", "invoice_id", "billing", "invoices", "invoice_id"),
    ("billing", "invoice_items", "product_id", "billing", "products", "product_id"),
    ("billing", "payments", "invoice_id", "billing", "invoices", "invoice_id"),
    ("crm", "contacts", "account_id", "crm", "accounts", "account_id"),
    ("crm", "opportunities", "account_id", "crm", "accounts", "account_id"),
    (
        "crm",
        "opportunity_contacts",
        "opportunity_id",
        "crm",
        "opportunities",
        "opportunity_id",
    ),
    ("crm", "opportunity_contacts", "contact_id", "crm", "contacts", "contact_id"),
    ("crm", "activities", "contact_id", "crm", "contacts", "contact_id"),
    (
        "crm",
        "activities",
        "opportunity_id",
        "crm",
        "opportunities",
        "opportunity_id",
    ),
    (
        "billing",
        "customers",
        "external_ref",
        "university",
        "students",
        "student_id",
    ),
]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def as_number(value: Any, digits: int = 4) -> int | float | None:
    """Convierte escalares NumPy/Pandas a tipos JSON estables."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if not math.isfinite(float(value)):
            return None
        return round(float(value), digits)
    return value


def pct(numerator: int | float, denominator: int | float, digits: int = 2) -> float:
    return round(float(numerator) / float(denominator) * 100, digits) if denominator else 0.0


def timestamp_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def to_cents(series: pd.Series) -> pd.Series:
    """Convierte importes con dos decimales a enteros, evitando comparar floats."""
    return (pd.to_numeric(series, errors="coerce") * 100).round().astype("Int64")


def safe_corr(left: pd.Series, right: pd.Series, method: str = "pearson") -> float | None:
    frame = pd.concat([left, right], axis=1).dropna()
    if len(frame) < 2 or frame.iloc[:, 0].nunique() < 2 or frame.iloc[:, 1].nunique() < 2:
        return None
    return as_number(frame.iloc[:, 0].corr(frame.iloc[:, 1], method=method), 4)


def cramers_v(left: pd.Series, right: pd.Series) -> float | None:
    """Cramér V sin depender de scipy."""
    observed = pd.crosstab(left, right)
    if observed.empty:
        return None
    matrix = observed.to_numpy(dtype=float)
    total = matrix.sum()
    expected = np.outer(matrix.sum(axis=1), matrix.sum(axis=0)) / total
    chi2 = np.divide(
        (matrix - expected) ** 2,
        expected,
        out=np.zeros_like(matrix),
        where=expected != 0,
    ).sum()
    denominator = total * min(matrix.shape[0] - 1, matrix.shape[1] - 1)
    return as_number(math.sqrt(chi2 / denominator), 4) if denominator > 0 else None


def load_data() -> tuple[dict[tuple[str, str], pd.DataFrame], dict[str, dict[str, int]]]:
    data: dict[tuple[str, str], pd.DataFrame] = {}
    parse_issues: dict[str, dict[str, int]] = {}

    for (domain, table), config in TABLE_CONFIG.items():
        path = RAW / domain / f"{table}.csv"
        frame = pd.read_csv(path)
        issues: dict[str, int] = {}

        for column in config["dates"]:
            original_non_null = frame[column].notna()
            parsed = pd.to_datetime(frame[column], errors="coerce")
            issues[f"invalid_date:{column}"] = int((original_non_null & parsed.isna()).sum())
            frame[column] = parsed

        for column in config["numeric"]:
            original_non_null = frame[column].notna()
            parsed = pd.to_numeric(frame[column], errors="coerce")
            issues[f"invalid_numeric:{column}"] = int((original_non_null & parsed.isna()).sum())
            frame[column] = parsed

        data[(domain, table)] = frame
        parse_issues[f"{domain}.{table}"] = issues

    return data, parse_issues


def manifest_expectations() -> dict[str, dict[str, Any]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected: dict[str, dict[str, Any]] = {}
    for domain, tables in manifest["domains"].items():
        for table, spec in tables.items():
            expected[f"{domain}.{table}"] = {
                "rows": int(spec["rows"]),
                "columns": list(spec["cols"]),
            }
    return expected


def profile_tables(
    data: dict[tuple[str, str], pd.DataFrame],
    parse_issues: dict[str, dict[str, int]],
) -> dict[str, Any]:
    expected = manifest_expectations()
    tables: dict[str, Any] = {}

    for key, frame in data.items():
        domain, table = key
        name = f"{domain}.{table}"
        config = TABLE_CONFIG[key]
        pk = config["pk"]
        nulls = {column: int(count) for column, count in frame.isna().sum().items() if count}
        duplicated_pk_mask = frame.duplicated(pk, keep=False)
        whitespace_cells = 0
        invalid_emails: dict[str, int] = {}
        normalized_email_duplicates: dict[str, int] = {}

        for column in frame.columns:
            if not (
                pd.api.types.is_object_dtype(frame[column].dtype)
                or pd.api.types.is_string_dtype(frame[column].dtype)
            ):
                continue
            non_null = frame[column].dropna().astype(str)
            whitespace_cells += int((non_null != non_null.str.strip()).sum())
            if "email" in column:
                normalized = non_null.str.strip().str.lower()
                invalid_emails[column] = int((~normalized.str.match(EMAIL_RE)).sum())
                normalized_email_duplicates[column] = int(
                    normalized.duplicated(keep=False).sum()
                )

        numeric_summary: dict[str, dict[str, Any]] = {}
        for column in config["numeric"]:
            values = frame[column].dropna()
            numeric_summary[column] = {
                "min": as_number(values.min()),
                "median": as_number(values.median()),
                "p95": as_number(values.quantile(0.95)),
                "max": as_number(values.max()),
            }

        date_ranges: dict[str, dict[str, str | None]] = {}
        for column in config["dates"]:
            date_ranges[column] = {
                "min": timestamp_text(frame[column].min()),
                "max": timestamp_text(frame[column].max()),
            }

        small_categories: dict[str, dict[str, int]] = {}
        for column in frame.columns:
            unique = frame[column].nunique(dropna=True)
            if 1 < unique <= 20 and column not in config["dates"]:
                small_categories[column] = {
                    str(value): int(count)
                    for value, count in frame[column]
                    .value_counts(dropna=False)
                    .items()
                }

        tables[name] = {
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "row_count_matches_manifest": len(frame) == expected[name]["rows"],
            "schema_matches_manifest": list(frame.columns) == expected[name]["columns"],
            "missing_cells": int(frame.isna().sum().sum()),
            "nulls_by_column": nulls,
            "exact_duplicate_rows": int(frame.duplicated().sum()),
            "primary_key": pk,
            "rows_in_duplicated_primary_keys": int(duplicated_pk_mask.sum()),
            "whitespace_cells": whitespace_cells,
            "invalid_emails": invalid_emails,
            "rows_in_normalized_duplicate_emails": normalized_email_duplicates,
            "parse_issues": parse_issues[name],
            "numeric_summary": numeric_summary,
            "date_ranges": date_ranges,
            "small_categories": small_categories,
        }

    return tables


def fk_metrics(
    child: pd.DataFrame,
    child_key: str,
    parent: pd.DataFrame,
    parent_key: str,
    label: str,
) -> dict[str, Any]:
    values = child[child_key].dropna()
    parent_values = parent[parent_key]
    valid_mask = values.isin(set(parent_values))
    valid = values[valid_mask]
    counts = valid.value_counts()
    parent_count = len(parent)
    child_count = len(values)
    observed_unused = parent_count - valid.nunique()
    expected_unused = (
        parent_count * ((parent_count - 1) / parent_count) ** child_count
        if parent_count
        else 0
    )

    return {
        "relation": label,
        "child_rows": int(len(child)),
        "non_null_fk": int(child_count),
        "null_fk": int(child[child_key].isna().sum()),
        "orphans": int((~valid_mask).sum()),
        "parent_rows": int(parent_count),
        "referenced_parents": int(valid.nunique()),
        "unreferenced_parents": int(observed_unused),
        "parent_coverage_pct": pct(valid.nunique(), parent_count),
        "avg_children_per_referenced_parent": as_number(counts.mean(), 2),
        "median_children": as_number(counts.median(), 2),
        "p95_children": as_number(counts.quantile(0.95), 2),
        "max_children": int(counts.max()) if not counts.empty else 0,
        "uniform_random_occupancy_baseline": {
            "expected_unreferenced_parents": as_number(expected_unused, 2),
            "observed_minus_expected": as_number(observed_unused - expected_unused, 2),
        },
    }


def relationship_audit(data: dict[tuple[str, str], pd.DataFrame]) -> list[dict[str, Any]]:
    results = []
    for (
        child_domain,
        child_table,
        child_key,
        parent_domain,
        parent_table,
        parent_key,
    ) in FK_CONFIG:
        label = (
            f"{child_domain}.{child_table}.{child_key} -> "
            f"{parent_domain}.{parent_table}.{parent_key}"
        )
        results.append(
            fk_metrics(
                data[(child_domain, child_table)],
                child_key,
                data[(parent_domain, parent_table)],
                parent_key,
                label,
            )
        )
    return results


def university_audit(
    data: dict[tuple[str, str], pd.DataFrame],
    as_of: pd.Timestamp,
) -> dict[str, Any]:
    semesters = data[("university", "semesters")]
    professors = data[("university", "professors")]
    students = data[("university", "students")]
    courses = data[("university", "courses")]
    enrollments = data[("university", "enrollments")]
    grades = data[("university", "grades")]

    semester_order = semesters.sort_values("start_date")
    semester_code_expected = (
        semesters["year"].astype(int).astype(str)
        + "-"
        + semesters["half"].astype(int).astype(str)
    )
    semester_overlaps = int(
        (
            semester_order["start_date"].iloc[1:].reset_index(drop=True)
            <= semester_order["end_date"].iloc[:-1].reset_index(drop=True)
        ).sum()
    )

    course_professor = courses.merge(
        professors[["professor_id", "department", "hired_at"]],
        on="professor_id",
        suffixes=("_course", "_professor"),
    )
    enrollment_semester = enrollments.merge(
        semesters[["semester_id", "start_date", "end_date"]], on="semester_id"
    )
    enrollment_student = enrollments.merge(
        students[["student_id", "enrolled_at"]],
        on="student_id",
        suffixes=("_enrollment", "_student"),
    )
    enrollment_student_semester = (
        enrollments.merge(
            students[["student_id", "enrolled_at"]].rename(
                columns={"enrolled_at": "student_registered_at"}
            ),
            on="student_id",
        ).merge(
            semesters[["semester_id", "end_date"]],
            on="semester_id",
        )
    )
    enrollment_professor = (
        enrollments.merge(courses[["course_id", "professor_id"]], on="course_id")
        .merge(professors[["professor_id", "hired_at"]], on="professor_id")
    )
    grade_context = (
        grades.merge(
            enrollments[
                [
                    "enrollment_id",
                    "student_id",
                    "semester_id",
                    "enrolled_at",
                    "status",
                ]
            ],
            on="enrollment_id",
            suffixes=("_grade", "_enrollment"),
        )
        .merge(semesters[["semester_id", "start_date", "end_date"]], on="semester_id")
        .merge(
            students[["student_id", "enrolled_at"]],
            on="student_id",
            suffixes=("", "_student"),
        )
    )

    grades_by_enrollment = grades.groupby("enrollment_id").agg(
        grade_count=("grade_id", "size"),
        weight_sum=("weight", "sum"),
        weighted_points=("score", lambda values: 0.0),
    )
    weighted_points = (grades["score"] * grades["weight"]).groupby(
        grades["enrollment_id"]
    ).sum()
    grades_by_enrollment["weighted_points"] = weighted_points
    grades_by_enrollment["normalized_score"] = (
        grades_by_enrollment["weighted_points"] / grades_by_enrollment["weight_sum"]
    )

    enrollment_quality = enrollments.set_index("enrollment_id").join(
        grades_by_enrollment
    )
    enrollment_quality["has_grades"] = enrollment_quality["grade_count"].notna()
    final_enrollment_ids = set(
        grades.loc[grades["assessment"] == "final", "enrollment_id"]
    )
    enrollment_quality["has_final_assessment"] = enrollment_quality.index.isin(
        final_enrollment_ids
    )

    grade_coverage_by_status: dict[str, Any] = {}
    normalized_score_by_status: dict[str, Any] = {}
    for status, group in enrollment_quality.groupby("status"):
        grade_coverage_by_status[str(status)] = {
            "enrollments": int(len(group)),
            "with_grades": int(group["has_grades"].sum()),
            "without_grades": int((~group["has_grades"]).sum()),
            "with_final_assessment": int(group["has_final_assessment"].sum()),
        }
        scored = group["normalized_score"].dropna()
        normalized_score_by_status[str(status)] = {
            "count": int(len(scored)),
            "mean": as_number(scored.mean(), 2),
            "median": as_number(scored.median(), 2),
        }

    weight_sum = grades.groupby("enrollment_id")["weight"].sum()
    duplicate_assessments = grades.groupby(["enrollment_id", "assessment"]).size()
    logical_enrollments = enrollments.groupby(
        ["student_id", "course_id", "semester_id"]
    )
    logical_sizes = logical_enrollments.size()
    duplicate_keys = logical_sizes[logical_sizes > 1].index
    duplicate_rows = (
        enrollments.set_index(["student_id", "course_id", "semester_id"])
        .loc[duplicate_keys]
        .reset_index()
    )
    ages = (students["enrolled_at"] - students["birth_date"]).dt.days / 365.2425

    student_semester_load = enrollments.groupby(
        ["student_id", "semester_id"]
    ).size()

    return {
        "semesters": {
            "invalid_date_ranges": int(
                (semesters["end_date"] < semesters["start_date"]).sum()
            ),
            "overlapping_semester_pairs": semester_overlaps,
            "code_year_half_mismatches": int(
                (semesters["code"] != semester_code_expected).sum()
            ),
        },
        "students": {
            "age_at_registration_min": as_number(ages.min(), 2),
            "age_at_registration_median": as_number(ages.median(), 2),
            "age_below_15": int((ages < 15).sum()),
            "age_below_18": int((ages < 18).sum()),
            "birth_on_or_after_registration": int((ages <= 0).sum()),
        },
        "course_professor": {
            "same_department": int(
                (
                    course_professor["department_course"]
                    == course_professor["department_professor"]
                ).sum()
            ),
            "different_department": int(
                (
                    course_professor["department_course"]
                    != course_professor["department_professor"]
                ).sum()
            ),
            "total_courses": int(len(course_professor)),
            "expected_same_department_if_independent_pct": as_number(
                sum(
                    courses["department"].value_counts(normalize=True).get(dept, 0)
                    * professors["department"]
                    .value_counts(normalize=True)
                    .get(dept, 0)
                    for dept in set(courses["department"])
                    | set(professors["department"])
                )
                * 100,
                2,
            ),
        },
        "enrollments": {
            "inside_referenced_semester": int(
                (
                    (enrollment_semester["enrolled_at"] >= enrollment_semester["start_date"])
                    & (enrollment_semester["enrolled_at"] <= enrollment_semester["end_date"])
                ).sum()
            ),
            "before_referenced_semester": int(
                (
                    enrollment_semester["enrolled_at"]
                    < enrollment_semester["start_date"]
                ).sum()
            ),
            "after_referenced_semester": int(
                (
                    enrollment_semester["enrolled_at"]
                    > enrollment_semester["end_date"]
                ).sum()
            ),
            "active_in_semester_ended_before_as_of": int(
                (
                    (enrollment_semester["status"] == "active")
                    & (enrollment_semester["end_date"] < as_of)
                ).sum()
            ),
            "before_student_registration": int(
                (
                    enrollment_student["enrolled_at_enrollment"]
                    < enrollment_student["enrolled_at_student"]
                ).sum()
            ),
            "student_registered_after_semester_end": int(
                (
                    enrollment_student_semester["student_registered_at"]
                    > enrollment_student_semester["end_date"]
                ).sum()
            ),
            "before_professor_hire": int(
                (
                    enrollment_professor["enrolled_at"]
                    < enrollment_professor["hired_at"]
                ).sum()
            ),
            "logical_duplicate_groups": int((logical_sizes > 1).sum()),
            "rows_in_logical_duplicate_groups": int(
                logical_sizes[logical_sizes > 1].sum()
            ),
            "duplicate_groups_with_conflicting_status": int(
                duplicate_rows.groupby(
                    ["student_id", "course_id", "semester_id"]
                )["status"]
                .nunique()
                .gt(1)
                .sum()
            ),
            "max_courses_per_student_semester": int(student_semester_load.max()),
            "student_semester_groups_over_8_courses": int(
                (student_semester_load > 8).sum()
            ),
            "status_distribution": {
                str(value): int(count)
                for value, count in enrollments["status"].value_counts().items()
            },
        },
        "grades": {
            "score_outside_0_100": int(
                ((grades["score"] < 0) | (grades["score"] > 100)).sum()
            ),
            "weight_outside_0_1": int(
                ((grades["weight"] < 0) | (grades["weight"] > 1)).sum()
            ),
            "before_enrollment": int(
                (
                    grade_context["graded_at"]
                    < grade_context["enrolled_at"]
                ).sum()
            ),
            "before_student_registration": int(
                (
                    grade_context["graded_at"]
                    < grade_context["enrolled_at_student"]
                ).sum()
            ),
            "inside_referenced_semester": int(
                (
                    (grade_context["graded_at"] >= grade_context["start_date"])
                    & (grade_context["graded_at"] <= grade_context["end_date"])
                ).sum()
            ),
            "before_referenced_semester": int(
                (grade_context["graded_at"] < grade_context["start_date"]).sum()
            ),
            "after_referenced_semester": int(
                (grade_context["graded_at"] > grade_context["end_date"]).sum()
            ),
            "enrollments_with_grades": int(grades["enrollment_id"].nunique()),
            "enrollments_without_grades": int(
                len(enrollments) - grades["enrollment_id"].nunique()
            ),
            "weight_sum_exactly_one_at_cent_precision": int(
                ((weight_sum * 100).round().astype(int) == 100).sum()
            ),
            "weight_sum_within_0_01": int(((weight_sum - 1).abs() <= 0.01).sum()),
            "weight_groups_total": int(len(weight_sum)),
            "duplicate_assessment_groups": int((duplicate_assessments > 1).sum()),
            "rows_in_duplicate_assessment_groups": int(
                duplicate_assessments[duplicate_assessments > 1].sum()
            ),
            "coverage_by_enrollment_status": grade_coverage_by_status,
            "normalized_score_by_enrollment_status": normalized_score_by_status,
            "status_vs_normalized_score_cramers_v_binned_deciles": cramers_v(
                enrollment_quality["status"],
                pd.qcut(
                    enrollment_quality["normalized_score"],
                    q=10,
                    duplicates="drop",
                ),
            ),
        },
    }


def subscription_overlap_metrics(subscriptions: pd.DataFrame) -> dict[str, int]:
    repeated_groups = 0
    overlapping_groups = 0
    overlapping_rows: set[str] = set()

    for _, group in subscriptions.groupby(["customer_id", "product_id"]):
        if len(group) < 2:
            continue
        repeated_groups += 1
        records = list(
            group[
                ["subscription_id", "start_date", "end_date"]
            ].itertuples(index=False, name=None)
        )
        group_overlaps = False
        for left, right in combinations(records, 2):
            left_id, left_start, left_end = left
            right_id, right_start, right_end = right
            if left_start <= right_end and right_start <= left_end:
                group_overlaps = True
                overlapping_rows.update([str(left_id), str(right_id)])
        overlapping_groups += int(group_overlaps)

    return {
        "customer_product_groups_with_multiple_subscriptions": repeated_groups,
        "customer_product_groups_with_overlapping_intervals": overlapping_groups,
        "subscription_rows_in_overlaps": len(overlapping_rows),
    }


def billing_audit(
    data: dict[tuple[str, str], pd.DataFrame],
    as_of: pd.Timestamp,
) -> dict[str, Any]:
    customers = data[("billing", "customers")]
    products = data[("billing", "products")]
    subscriptions = data[("billing", "subscriptions")]
    invoices = data[("billing", "invoices")]
    items = data[("billing", "invoice_items")]
    payments = data[("billing", "payments")]

    subscription_customer = subscriptions.merge(
        customers[["customer_id", "created_at"]], on="customer_id"
    )
    subscription_product = subscriptions.merge(
        products[["product_id", "active", "monthly_price", "category"]],
        on="product_id",
    )
    invoice_customer = invoices.merge(
        customers[["customer_id", "created_at", "country", "segment"]],
        on="customer_id",
    )

    invoice_total_cents = invoices.set_index("invoice_id")["total"].pipe(to_cents)
    line_total_cents = (
        items.assign(_cents=to_cents(items["line_total"]))
        .groupby("invoice_id")["_cents"]
        .sum()
    )
    payment_total_cents = (
        payments.assign(_cents=to_cents(payments["amount"]))
        .groupby("invoice_id")["_cents"]
        .sum()
    )
    invoice_finance = (
        invoices.set_index("invoice_id")[["status", "currency", "customer_id"]]
        .assign(invoice_total_cents=invoice_total_cents)
        .join(line_total_cents.rename("line_sum_cents"))
        .join(payment_total_cents.rename("payment_sum_cents"))
    )

    with_lines = invoice_finance.dropna(subset=["line_sum_cents"]).copy()
    line_delta = with_lines["line_sum_cents"] - with_lines["invoice_total_cents"]
    with_payments = invoice_finance.dropna(subset=["payment_sum_cents"]).copy()
    payment_delta = (
        with_payments["payment_sum_cents"] - with_payments["invoice_total_cents"]
    )

    payment_context = payments.merge(
        invoices[
            [
                "invoice_id",
                "issued_at",
                "due_at",
                "status",
                "currency",
                "customer_id",
            ]
        ],
        on="invoice_id",
    )
    payment_customer_context = payment_context.merge(
        customers[["customer_id", "created_at"]],
        on="customer_id",
    )
    item_product = items.merge(
        products[["product_id", "monthly_price", "category"]], on="product_id"
    )
    item_product["unit_price_cents"] = to_cents(item_product["unit_price"])
    item_product["monthly_price_cents"] = to_cents(item_product["monthly_price"])
    item_product["relative_price_error"] = (
        item_product["unit_price"] - item_product["monthly_price"]
    ).abs() / item_product["monthly_price"]

    item_context = items.merge(
        invoices[["invoice_id", "customer_id", "issued_at"]], on="invoice_id"
    )
    subscribed_pairs = set(
        zip(subscriptions["customer_id"], subscriptions["product_id"])
    )
    item_context["has_customer_product_subscription"] = [
        pair in subscribed_pairs
        for pair in zip(item_context["customer_id"], item_context["product_id"])
    ]
    interval_candidates = item_context.merge(
        subscriptions[
            ["customer_id", "product_id", "start_date", "end_date"]
        ],
        on=["customer_id", "product_id"],
        how="inner",
    )
    interval_candidates["inside_subscription_interval"] = (
        (interval_candidates["issued_at"] >= interval_candidates["start_date"])
        & (interval_candidates["issued_at"] <= interval_candidates["end_date"])
    )
    interval_item_ids = set(
        interval_candidates.loc[
            interval_candidates["inside_subscription_interval"], "invoice_item_id"
        ]
    )

    country_currency = {
        "CL": "CLP",
        "PE": "PEN",
        "AR": "ARS",
        "MX": "MXN",
        "BR": "BRL",
        "ES": "EUR",
        "CO": "COP",
        "US": "USD",
    }
    expected_currency = invoice_customer["country"].map(country_currency)
    currency_aligned = invoice_customer["currency"] == expected_currency
    country_distribution = invoice_customer["country"].value_counts(normalize=True)
    currency_distribution = invoice_customer["currency"].value_counts(normalize=True)
    expected_currency_alignment = sum(
        country_distribution.get(country, 0)
        * currency_distribution.get(currency, 0)
        for country, currency in country_currency.items()
    )

    payment_ratio = payment_context["amount"] / payment_context.merge(
        invoices[["invoice_id", "total"]],
        on="invoice_id",
        suffixes=("", "_invoice"),
    )["total"]
    payment_delay_days = (
        payment_context["paid_at"] - payment_context["issued_at"]
    ).dt.days

    status_payment = (
        invoice_finance.assign(has_payment=invoice_finance["payment_sum_cents"].notna())
        .groupby(["status", "has_payment"])
        .size()
        .unstack(fill_value=0)
    )
    status_payment_rows: dict[str, Any] = {}
    for status, row in status_payment.iterrows():
        status_payment_rows[str(status)] = {
            "without_payment": int(row.get(False, 0)),
            "with_payment": int(row.get(True, 0)),
        }

    by_currency: dict[str, Any] = {}
    finance_amounts = invoice_finance.copy()
    for currency, group in finance_amounts.groupby("currency"):
        by_currency[str(currency)] = {
            "invoices": int(len(group)),
            "reported_total": as_number(group["invoice_total_cents"].sum() / 100, 2),
            "line_sum_present": as_number(
                group["line_sum_cents"].dropna().sum() / 100, 2
            ),
            "payment_sum_present": as_number(
                group["payment_sum_cents"].dropna().sum() / 100, 2
            ),
            "invoices_with_lines": int(group["line_sum_cents"].notna().sum()),
            "invoices_with_payments": int(group["payment_sum_cents"].notna().sum()),
        }

    category_prices: dict[str, Any] = {}
    for category, group in products.groupby("category"):
        category_prices[str(category)] = {
            "products": int(len(group)),
            "median_monthly_price": as_number(group["monthly_price"].median(), 2),
            "min_monthly_price": as_number(group["monthly_price"].min(), 2),
            "max_monthly_price": as_number(group["monthly_price"].max(), 2),
        }

    payment_currency_summary: dict[str, Any] = {}
    for currency, group in payment_context.groupby("currency"):
        payment_currency_summary[str(currency)] = {
            "payments": int(len(group)),
            "median_nominal_amount": as_number(group["amount"].median(), 2),
        }

    due_days = (invoices["due_at"] - invoices["issued_at"]).dt.days
    overlap = subscription_overlap_metrics(subscriptions)

    return {
        "products": {
            "nonpositive_monthly_price": int((products["monthly_price"] <= 0).sum()),
            "category_vs_price_decile_cramers_v": cramers_v(
                products["category"],
                pd.qcut(products["monthly_price"], q=10, duplicates="drop"),
            ),
            "category_price_summary": category_prices,
        },
        "subscriptions": {
            "end_before_start": int(
                (subscriptions["end_date"] < subscriptions["start_date"]).sum()
            ),
            "before_customer_created": int(
                (
                    subscription_customer["start_date"]
                    < subscription_customer["created_at"]
                ).sum()
            ),
            "active_total": int((subscriptions["status"] == "active").sum()),
            "active_with_end_date": int(
                (
                    (subscriptions["status"] == "active")
                    & subscriptions["end_date"].notna()
                ).sum()
            ),
            "active_expired_as_of": int(
                (
                    (subscriptions["status"] == "active")
                    & (subscriptions["end_date"] < as_of)
                ).sum()
            ),
            "active_on_inactive_product": int(
                (
                    (subscription_product["status"] == "active")
                    & (~subscription_product["active"])
                ).sum()
            ),
            **overlap,
        },
        "invoices": {
            "before_customer_created": int(
                (invoice_customer["issued_at"] < invoice_customer["created_at"]).sum()
            ),
            "due_before_issued": int((due_days < 0).sum()),
            "pending_past_due_as_of": int(
                (
                    (invoices["status"] == "pending")
                    & (invoices["due_at"] < as_of)
                ).sum()
            ),
            "pending_total": int((invoices["status"] == "pending").sum()),
            "due_days_unique": sorted(int(value) for value in due_days.unique()),
            "without_items": int(invoice_finance["line_sum_cents"].isna().sum()),
            "with_items": int(len(with_lines)),
            "line_sum_equal_header_at_cent_precision": int((line_delta == 0).sum()),
            "line_sum_greater_than_header": int((line_delta > 0).sum()),
            "line_sum_less_than_header": int((line_delta < 0).sum()),
            "header_line_pearson_correlation": safe_corr(
                with_lines["invoice_total_cents"].astype(float),
                with_lines["line_sum_cents"].astype(float),
            ),
            "customer_country_currency_alignment": int(currency_aligned.sum()),
            "customer_country_currency_alignment_pct": pct(
                int(currency_aligned.sum()), len(invoice_customer)
            ),
            "expected_country_currency_alignment_if_independent_pct": as_number(
                expected_currency_alignment * 100, 2
            ),
            "status_vs_payment_presence": status_payment_rows,
        },
        "invoice_items": {
            "line_total_not_quantity_times_unit_price_at_cent_precision": int(
                (
                    to_cents(items["line_total"])
                    != to_cents(items["quantity"] * items["unit_price"])
                ).sum()
            ),
            "unit_price_equal_product_monthly_price_at_cent_precision": int(
                (
                    item_product["unit_price_cents"]
                    == item_product["monthly_price_cents"]
                ).sum()
            ),
            "unit_price_within_one_pct_of_product_monthly_price": int(
                (item_product["relative_price_error"] <= 0.01).sum()
            ),
            "median_relative_price_error_pct": as_number(
                item_product["relative_price_error"].median() * 100,
                2,
            ),
            "unit_price_product_price_pearson_correlation": safe_corr(
                item_product["unit_price"], item_product["monthly_price"]
            ),
            "customer_product_has_any_subscription": int(
                item_context["has_customer_product_subscription"].sum()
            ),
            "invoice_date_inside_matching_subscription_interval": int(
                len(interval_item_ids)
            ),
            "total_items": int(len(items)),
        },
        "payments": {
            "nonpositive_amount": int((payments["amount"] <= 0).sum()),
            "before_invoice_issued": int(
                (
                    payment_context["paid_at"] < payment_context["issued_at"]
                ).sum()
            ),
            "before_customer_created": int(
                (
                    payment_customer_context["paid_at"]
                    < payment_customer_context["created_at"]
                ).sum()
            ),
            "after_invoice_due": int(
                (payment_context["paid_at"] > payment_context["due_at"]).sum()
            ),
            "on_non_usd_invoices": int(
                (payment_context["currency"] != "USD").sum()
            ),
            "nominal_amount_by_invoice_currency": payment_currency_summary,
            "payment_delay_days": {
                "min": as_number(payment_delay_days.min()),
                "median": as_number(payment_delay_days.median()),
                "p95": as_number(payment_delay_days.quantile(0.95)),
                "max": as_number(payment_delay_days.max()),
            },
            "individual_amount_as_share_of_invoice_total": {
                "min": as_number(payment_ratio.min(), 4),
                "median": as_number(payment_ratio.median(), 4),
                "p95": as_number(payment_ratio.quantile(0.95), 4),
                "max": as_number(payment_ratio.max(), 4),
                "individual_amount_invoice_total_pearson_correlation": safe_corr(
                    payment_context["amount"],
                    payment_context.merge(
                        invoices[["invoice_id", "total"]],
                        on="invoice_id",
                        suffixes=("", "_invoice"),
                    )["total"],
                ),
            },
            "invoices_with_payments": int(len(with_payments)),
            "sum_equal_header_at_cent_precision": int((payment_delta == 0).sum()),
            "sum_greater_than_header_at_cent_precision": int((payment_delta > 0).sum()),
            "sum_less_than_header_at_cent_precision": int((payment_delta < 0).sum()),
            "sum_within_plus_minus_one_cent": int((payment_delta.abs() <= 1).sum()),
            "sum_greater_than_header_beyond_one_cent": int((payment_delta > 1).sum()),
            "sum_less_than_header_beyond_one_cent": int((payment_delta < -1).sum()),
            "header_payment_pearson_correlation": safe_corr(
                with_payments["invoice_total_cents"].astype(float),
                with_payments["payment_sum_cents"].astype(float),
            ),
            "individual_payment_greater_than_invoice_total": int(
                (
                    to_cents(payment_context["amount"])
                    > to_cents(
                        payment_context.merge(
                            invoices[["invoice_id", "total"]],
                            on="invoice_id",
                            suffixes=("", "_invoice"),
                        )["total"]
                    )
                ).sum()
            ),
        },
        "financial_summary_by_invoice_currency": by_currency,
    }


def crm_audit(
    data: dict[tuple[str, str], pd.DataFrame],
    as_of: pd.Timestamp,
) -> dict[str, Any]:
    accounts = data[("crm", "accounts")]
    contacts = data[("crm", "contacts")]
    leads = data[("crm", "leads")]
    opportunities = data[("crm", "opportunities")]
    opportunity_contacts = data[("crm", "opportunity_contacts")]
    activities = data[("crm", "activities")]

    contact_account = contacts.merge(
        accounts[["account_id", "created_at"]],
        on="account_id",
        suffixes=("_contact", "_account"),
    )
    opportunity_account = opportunities.merge(
        accounts[["account_id", "created_at", "annual_revenue"]],
        on="account_id",
        suffixes=("_opportunity", "_account"),
    )
    bridge_accounts = (
        opportunity_contacts.merge(
            opportunities[["opportunity_id", "account_id"]],
            on="opportunity_id",
        ).merge(
            contacts[["contact_id", "account_id"]],
            on="contact_id",
            suffixes=("_opportunity", "_contact"),
        )
    )

    both = activities.dropna(subset=["contact_id", "opportunity_id"]).copy()
    both_accounts = (
        both.merge(
            contacts[["contact_id", "account_id"]],
            on="contact_id",
        ).merge(
            opportunities[["opportunity_id", "account_id"]],
            on="opportunity_id",
            suffixes=("_contact", "_opportunity"),
        )
    )
    bridge_pairs = pd.MultiIndex.from_frame(
        opportunity_contacts[["opportunity_id", "contact_id"]]
    )
    activity_pairs = pd.MultiIndex.from_frame(
        both[["opportunity_id", "contact_id"]]
    )
    both_pair_in_bridge = activity_pairs.isin(bridge_pairs)

    activity_contact = activities.dropna(subset=["contact_id"]).merge(
        contacts[["contact_id", "created_at"]], on="contact_id"
    )
    activity_opportunity = activities.dropna(subset=["opportunity_id"]).merge(
        opportunities[["opportunity_id", "created_at", "close_date"]],
        on="opportunity_id",
    )

    scope = pd.Series("unlinked", index=activities.index)
    scope.loc[activities["contact_id"].notna() & activities["opportunity_id"].isna()] = (
        "contact_only"
    )
    scope.loc[activities["contact_id"].isna() & activities["opportunity_id"].notna()] = (
        "opportunity_only"
    )
    scope.loc[activities["contact_id"].notna() & activities["opportunity_id"].notna()] = (
        "both"
    )

    stage_summary: dict[str, Any] = {}
    for stage, group in opportunities.groupby("stage"):
        stage_summary[str(stage)] = {
            "opportunities": int(len(group)),
            "amount_sum": as_number(group["amount"].sum(), 2),
            "amount_median": as_number(group["amount"].median(), 2),
            "close_before_created": int(
                (group["close_date"] < group["created_at"]).sum()
            ),
        }

    score_by_status: dict[str, Any] = {}
    for status, group in leads.groupby("status"):
        score_by_status[str(status)] = {
            "leads": int(len(group)),
            "score_mean": as_number(group["score"].mean(), 2),
            "score_median": as_number(group["score"].median(), 2),
        }
    leads_score_decile = pd.qcut(leads["score"], q=10, duplicates="drop")
    low_score = leads["score"] < 50
    high_score = ~low_score

    open_stages = {"prospect", "qualification", "proposal", "negotiation"}
    terminal_stages = {"won", "lost"}
    account_name_country = accounts.groupby(["name", "country"]).size()

    opportunity_account_distribution = opportunities["account_id"].value_counts(
        normalize=True
    )
    contact_account_distribution = contacts["account_id"].value_counts(normalize=True)
    common_accounts = set(opportunity_account_distribution.index) | set(
        contact_account_distribution.index
    )
    expected_account_match_probability = sum(
        opportunity_account_distribution.get(account_id, 0)
        * contact_account_distribution.get(account_id, 0)
        for account_id in common_accounts
    )

    return {
        "accounts": {
            "unique_names": int(accounts["name"].nunique()),
            "rows_with_duplicated_name": int(
                accounts["name"].duplicated(keep=False).sum()
            ),
            "duplicate_name_country_groups": int(
                (account_name_country > 1).sum()
            ),
            "rows_in_duplicate_name_country_groups": int(
                account_name_country[account_name_country > 1].sum()
            ),
            "nonpositive_employees": int((accounts["employees"] <= 0).sum()),
            "nonpositive_annual_revenue": int(
                (accounts["annual_revenue"] <= 0).sum()
            ),
            "annual_revenue_employees_pearson_correlation": safe_corr(
                accounts["annual_revenue"], accounts["employees"]
            ),
            "annual_revenue_employees_spearman_correlation": safe_corr(
                accounts["annual_revenue"], accounts["employees"], method="spearman"
            ),
        },
        "contacts": {
            "created_before_account": int(
                (
                    contact_account["created_at_contact"]
                    < contact_account["created_at_account"]
                ).sum()
            ),
            "rows_in_duplicated_email": int(
                contacts["email"].str.lower().duplicated(keep=False).sum()
            ),
            "rows_in_duplicated_phone": int(
                contacts["phone"].duplicated(keep=False).sum()
            ),
        },
        "leads": {
            "status_score_summary": score_by_status,
            "status_vs_score_decile_cramers_v": cramers_v(
                leads["status"], leads_score_decile
            ),
            "converted": int((leads["status"] == "converted").sum()),
            "conversion_by_score_band": {
                "score_below_50": {
                    "leads": int(low_score.sum()),
                    "converted": int(
                        (low_score & (leads["status"] == "converted")).sum()
                    ),
                },
                "score_50_or_more": {
                    "leads": int(high_score.sum()),
                    "converted": int(
                        (high_score & (leads["status"] == "converted")).sum()
                    ),
                },
            },
            "converted_in_top_score_decile": int(
                (
                    (leads["status"] == "converted")
                    & (leads["score"] >= leads["score"].quantile(0.9))
                ).sum()
            ),
        },
        "opportunities": {
            "created_before_account": int(
                (
                    opportunity_account["created_at_opportunity"]
                    < opportunity_account["created_at_account"]
                ).sum()
            ),
            "close_before_created": int(
                (opportunities["close_date"] < opportunities["created_at"]).sum()
            ),
            "open_stage_with_close_date_on_or_before_as_of": int(
                (
                    opportunities["stage"].isin(open_stages)
                    & (opportunities["close_date"] <= as_of)
                ).sum()
            ),
            "terminal_stage_with_future_close_date": int(
                (
                    opportunities["stage"].isin(terminal_stages)
                    & (opportunities["close_date"] > as_of)
                ).sum()
            ),
            "amount_greater_than_account_annual_revenue": int(
                (
                    opportunity_account["amount"]
                    > opportunity_account["annual_revenue"]
                ).sum()
            ),
            "won_amount_greater_than_account_annual_revenue": int(
                (
                    (opportunity_account["stage"] == "won")
                    & (
                        opportunity_account["amount"]
                        > opportunity_account["annual_revenue"]
                    )
                ).sum()
            ),
            "amount_account_revenue_pearson_correlation": safe_corr(
                opportunity_account["amount"],
                opportunity_account["annual_revenue"],
            ),
            "amount_account_revenue_spearman_correlation": safe_corr(
                opportunity_account["amount"],
                opportunity_account["annual_revenue"],
                method="spearman",
            ),
            "stage_summary": stage_summary,
            "stage_vs_amount_decile_cramers_v": cramers_v(
                opportunities["stage"],
                pd.qcut(opportunities["amount"], q=10, duplicates="drop"),
            ),
        },
        "opportunity_contacts": {
            "total_pairs": int(len(opportunity_contacts)),
            "duplicate_pairs": int(
                opportunity_contacts.duplicated(
                    ["opportunity_id", "contact_id"]
                ).sum()
            ),
            "same_account": int(
                (
                    bridge_accounts["account_id_opportunity"]
                    == bridge_accounts["account_id_contact"]
                ).sum()
            ),
            "expected_same_account_if_independent": as_number(
                len(opportunity_contacts) * expected_account_match_probability, 2
            ),
        },
        "activities": {
            "scope": {
                str(value): int(count) for value, count in scope.value_counts().items()
            },
            "both_fk_pair_exists_in_opportunity_contacts": int(
                both_pair_in_bridge.sum()
            ),
            "both_fk_total": int(len(both)),
            "both_fk_same_account": int(
                (
                    both_accounts["account_id_contact"]
                    == both_accounts["account_id_opportunity"]
                ).sum()
            ),
            "before_contact_created": int(
                (
                    activity_contact["occurred_at"]
                    < activity_contact["created_at"]
                ).sum()
            ),
            "before_opportunity_created": int(
                (
                    activity_opportunity["occurred_at"]
                    < activity_opportunity["created_at"]
                ).sum()
            ),
            "after_opportunity_close": int(
                (
                    activity_opportunity["occurred_at"]
                    > activity_opportunity["close_date"]
                ).sum()
            ),
            "type_vs_scope_cramers_v": cramers_v(activities["type"], scope),
        },
    }


def cross_domain_audit(
    data: dict[tuple[str, str], pd.DataFrame],
    university: dict[str, Any],
) -> dict[str, Any]:
    students = data[("university", "students")]
    grades = data[("university", "grades")]
    enrollments = data[("university", "enrollments")]
    customers = data[("billing", "customers")]
    subscriptions = data[("billing", "subscriptions")]
    invoices = data[("billing", "invoices")]
    payments = data[("billing", "payments")]
    professors = data[("university", "professors")]
    contacts = data[("crm", "contacts")]
    leads = data[("crm", "leads")]

    linked = customers.dropna(subset=["external_ref"]).merge(
        students,
        left_on="external_ref",
        right_on="student_id",
        suffixes=("_customer", "_student"),
    )
    same_email = (
        linked["email_customer"].str.strip().str.lower()
        == linked["email_student"].str.strip().str.lower()
    )
    same_name = (
        linked["first_name_customer"].str.strip().str.lower()
        == linked["first_name_student"].str.strip().str.lower()
    ) & (
        linked["last_name_customer"].str.strip().str.lower()
        == linked["last_name_student"].str.strip().str.lower()
    )
    same_country = linked["country_customer"] == linked["country_student"]
    expected_country_match_probability = sum(
        linked["country_customer"].value_counts(normalize=True).get(country, 0)
        * linked["country_student"].value_counts(normalize=True).get(country, 0)
        for country in set(linked["country_customer"]) | set(linked["country_student"])
    )

    email_frames = {
        "students": students["email"].str.strip().str.lower(),
        "professors": professors["email"].str.strip().str.lower(),
        "customers": customers["email"].str.strip().str.lower(),
        "contacts": contacts["email"].str.strip().str.lower(),
        "leads": leads["email"].str.strip().str.lower(),
    }
    email_overlaps: dict[str, int] = {}
    for left, right in combinations(email_frames, 2):
        email_overlaps[f"{left}<->{right}"] = len(
            set(email_frames[left].dropna()) & set(email_frames[right].dropna())
        )

    grade_points = (grades["score"] * grades["weight"]).groupby(
        grades["enrollment_id"]
    ).sum()
    grade_weights = grades.groupby("enrollment_id")["weight"].sum()
    enrollment_score = (grade_points / grade_weights).rename("normalized_score")
    student_scores = (
        enrollments[["enrollment_id", "student_id"]]
        .set_index("enrollment_id")
        .join(enrollment_score)
        .groupby("student_id")["normalized_score"]
        .mean()
    )
    invoice_counts = invoices.groupby("customer_id").size().rename("invoice_count")
    subscription_counts = (
        subscriptions.groupby("customer_id").size().rename("subscription_count")
    )
    linked_metrics = (
        linked[["customer_id", "student_id"]]
        .set_index("student_id")
        .join(student_scores)
        .reset_index()
        .set_index("customer_id")
        .join(invoice_counts)
        .join(subscription_counts)
        .fillna({"invoice_count": 0, "subscription_count": 0})
    )
    invoice_customers_with_payments = set(
        invoices.loc[
            invoices["invoice_id"].isin(payments["invoice_id"]),
            "customer_id",
        ]
    )
    linked_subscriptions = subscriptions.merge(
        linked[["customer_id", "enrolled_at"]],
        on="customer_id",
    )
    linked_invoices = invoices.merge(
        linked[["customer_id", "enrolled_at"]],
        on="customer_id",
    )
    linked_payments = (
        payments.merge(
            invoices[["invoice_id", "customer_id"]],
            on="invoice_id",
        ).merge(
            linked[["customer_id", "enrolled_at"]],
            on="customer_id",
        )
    )

    linked_customer_numeric_id = pd.to_numeric(
        linked["customer_id"].str.extract(r"(\d+)$", expand=False), errors="coerce"
    )
    linked_student_numeric_id = pd.to_numeric(
        linked["student_id"].str.extract(r"(\d+)$", expand=False), errors="coerce"
    )
    student_date_number = (
        linked["enrolled_at"].astype("int64") // 86_400_000_000_000
    )
    customer_date_number = (
        linked["created_at"].astype("int64") // 86_400_000_000_000
    )

    converted_emails = set(
        leads.loc[leads["status"] == "converted", "email"].str.lower()
    )
    known_emails = set(
        pd.concat([students["email"], customers["email"], contacts["email"]])
        .str.lower()
        .dropna()
    )

    customer_counts = (
        customers.assign(linked=customers["external_ref"].notna())
        .groupby("linked")
        .size()
    )
    linked_vs_unlinked: dict[str, Any] = {}
    customer_behavior = (
        customers[["customer_id", "external_ref"]]
        .set_index("customer_id")
        .join(invoice_counts)
        .join(subscription_counts)
        .fillna({"invoice_count": 0, "subscription_count": 0})
    )
    customer_behavior["linked"] = customer_behavior["external_ref"].notna()
    for flag, group in customer_behavior.groupby("linked"):
        label = "student_reference" if flag else "no_student_reference"
        linked_vs_unlinked[label] = {
            "customers": int(customer_counts.loc[flag]),
            "mean_invoice_count": as_number(group["invoice_count"].mean(), 3),
            "mean_subscription_count": as_number(
                group["subscription_count"].mean(), 3
            ),
            "customers_without_invoice": int((group["invoice_count"] == 0).sum()),
            "customers_without_subscription": int(
                (group["subscription_count"] == 0).sum()
            ),
            "customers_with_payment": int(
                group.index.isin(invoice_customers_with_payments).sum()
            ),
        }

    return {
        "student_customer_link": {
            "linked_pairs": int(len(linked)),
            "unique_student_references": int(customers["external_ref"].dropna().nunique()),
            "duplicate_student_references": int(
                customers["external_ref"].dropna().duplicated().sum()
            ),
            "same_email": int(same_email.sum()),
            "same_full_name": int(same_name.sum()),
            "same_country": int(same_country.sum()),
            "same_country_pct": pct(int(same_country.sum()), len(linked)),
            "expected_same_country_if_random_pairing": as_number(
                len(linked) * expected_country_match_probability, 2
            ),
            "customer_created_before_student_registration": int(
                (linked["created_at"] < linked["enrolled_at"]).sum()
            ),
            "customer_created_after_student_registration": int(
                (linked["created_at"] > linked["enrolled_at"]).sum()
            ),
            "customer_student_date_pearson_correlation": safe_corr(
                customer_date_number, student_date_number
            ),
            "customer_student_numeric_id_spearman_correlation": safe_corr(
                linked_customer_numeric_id,
                linked_student_numeric_id,
                method="spearman",
            ),
            "customer_student_numeric_id_exact_match": int(
                (linked_customer_numeric_id == linked_student_numeric_id).sum()
            ),
            "subscriptions_before_student_registration": int(
                (
                    linked_subscriptions["start_date"]
                    < linked_subscriptions["enrolled_at"]
                ).sum()
            ),
            "linked_subscriptions_total": int(len(linked_subscriptions)),
            "invoices_before_student_registration": int(
                (
                    linked_invoices["issued_at"]
                    < linked_invoices["enrolled_at"]
                ).sum()
            ),
            "linked_invoices_total": int(len(linked_invoices)),
            "payments_before_student_registration": int(
                (
                    linked_payments["paid_at"]
                    < linked_payments["enrolled_at"]
                ).sum()
            ),
            "linked_payments_total": int(len(linked_payments)),
        },
        "behavioral_cross_domain_correlations": {
            "student_score_vs_invoice_count_spearman": safe_corr(
                linked_metrics["normalized_score"],
                linked_metrics["invoice_count"],
                method="spearman",
            ),
            "student_score_vs_subscription_count_spearman": safe_corr(
                linked_metrics["normalized_score"],
                linked_metrics["subscription_count"],
                method="spearman",
            ),
            "note": (
                "Son diagnósticos de independencia, no KPIs publicables: "
                "los atributos de identidad no se alinean."
            ),
        },
        "linked_vs_unlinked_customer_behavior": linked_vs_unlinked,
        "exact_email_overlaps": email_overlaps,
        "converted_leads": int((leads["status"] == "converted").sum()),
        "converted_lead_overlap_with_known_people": int(
            len(converted_emails & known_emails)
        ),
        "university_reference": {
            "grade_weight_groups_total": university["grades"]["weight_groups_total"]
        },
    }


def generator_evidence(
    data: dict[tuple[str, str], pd.DataFrame],
    relationships: list[dict[str, Any]],
    university: dict[str, Any],
    crm: dict[str, Any],
    cross_domain: dict[str, Any],
) -> dict[str, Any]:
    activities = data[("crm", "activities")]
    null_contact_rate = activities["contact_id"].isna().mean()
    null_opportunity_rate = activities["opportunity_id"].isna().mean()
    expected_both_null = len(activities) * null_contact_rate * null_opportunity_rate
    observed_both_null = int(
        (activities["contact_id"].isna() & activities["opportunity_id"].isna()).sum()
    )

    occupancy_relations = {
        row["relation"]: {
            "observed_unreferenced_parents": row["unreferenced_parents"],
            **row["uniform_random_occupancy_baseline"],
        }
        for row in relationships
        if row["relation"]
        in {
            "university.grades.enrollment_id -> university.enrollments.enrollment_id",
            "billing.subscriptions.customer_id -> billing.customers.customer_id",
            "billing.invoices.customer_id -> billing.customers.customer_id",
            "billing.invoice_items.invoice_id -> billing.invoices.invoice_id",
            "crm.contacts.account_id -> crm.accounts.account_id",
            "crm.opportunities.account_id -> crm.accounts.account_id",
        }
    }

    return {
        "interpretation": (
            "Los resultados son consistentes con asignaciones aleatorias uniformes e "
            "independientes. Es evidencia estadística, no prueba del código generador."
        ),
        "parent_occupancy_observed_vs_uniform_baseline": occupancy_relations,
        "activity_fk_missingness": {
            "null_contact_pct": as_number(null_contact_rate * 100, 3),
            "null_opportunity_pct": as_number(null_opportunity_rate * 100, 3),
            "observed_both_null": observed_both_null,
            "expected_both_null_if_independent": as_number(expected_both_null, 2),
            "difference": as_number(observed_both_null - expected_both_null, 2),
        },
        "department_match": {
            "observed_pct": pct(
                university["course_professor"]["same_department"],
                university["course_professor"]["total_courses"],
            ),
            "expected_if_independent_pct": university["course_professor"][
                "expected_same_department_if_independent_pct"
            ],
        },
        "crm_account_match": {
            "opportunity_contact_observed": crm["opportunity_contacts"]["same_account"],
            "opportunity_contact_expected_if_independent": crm[
                "opportunity_contacts"
            ]["expected_same_account_if_independent"],
        },
        "student_customer_country_match": {
            "observed": cross_domain["student_customer_link"]["same_country"],
            "expected_if_random_pairing": cross_domain["student_customer_link"][
                "expected_same_country_if_random_pairing"
            ],
        },
    }


def build_result(as_of: str) -> dict[str, Any]:
    data, parse_issues = load_data()
    profiles = profile_tables(data, parse_issues)
    relationships = relationship_audit(data)
    as_of_timestamp = pd.Timestamp(as_of)
    university = university_audit(data, as_of_timestamp)
    billing = billing_audit(data, as_of_timestamp)
    crm = crm_audit(data, as_of_timestamp)
    cross_domain = cross_domain_audit(data, university)

    structural = {
        "tables": len(data),
        "rows": int(sum(len(frame) for frame in data.values())),
        "columns": int(sum(len(frame.columns) for frame in data.values())),
        "tables_matching_manifest_row_count": int(
            sum(profile["row_count_matches_manifest"] for profile in profiles.values())
        ),
        "tables_matching_manifest_schema": int(
            sum(profile["schema_matches_manifest"] for profile in profiles.values())
        ),
        "missing_cells": int(
            sum(profile["missing_cells"] for profile in profiles.values())
        ),
        "exact_duplicate_rows": int(
            sum(profile["exact_duplicate_rows"] for profile in profiles.values())
        ),
        "rows_in_duplicated_primary_keys": int(
            sum(
                profile["rows_in_duplicated_primary_keys"]
                for profile in profiles.values()
            )
        ),
        "invalid_date_or_numeric_values": int(
            sum(
                sum(profile["parse_issues"].values())
                for profile in profiles.values()
            )
        ),
        "foreign_key_relationships_checked": len(relationships),
        "foreign_key_orphans": int(sum(row["orphans"] for row in relationships)),
    }

    return {
        "metadata": {
            "source": "data/raw",
            "as_of": as_of_timestamp.date().isoformat(),
            "method": "Auditoría independiente con pandas; importes comparados en centavos.",
        },
        "structural_summary": structural,
        "table_profiles": profiles,
        "relationships": relationships,
        "semantic_checks": {
            "university": university,
            "billing": billing,
            "crm": crm,
            "cross_domain": cross_domain,
        },
        "generator_evidence": generator_evidence(
            data, relationships, university, crm, cross_domain
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        default=DEFAULT_AS_OF,
        help=f"Fecha de corte ISO para estados vigentes (default: {DEFAULT_AS_OF}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Ruta opcional donde guardar el JSON; también imprime un resumen.",
    )
    args = parser.parse_args()

    result = build_result(args.as_of)
    payload = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(output),
                    "structural_summary": result["structural_summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(payload)


if __name__ == "__main__":
    main()
