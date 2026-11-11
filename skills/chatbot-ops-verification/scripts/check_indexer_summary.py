"""Read one local indexer summary; no app imports, network, credentials or writes."""
import argparse
import json
from pathlib import Path


COUNTS = (
    "discovered", "updated", "skipped", "deleted", "failed_pages",
    "failed_categories", "failed_deletions", "translations_pending",
    "translations_attempted", "translations_completed", "translations_failed",
    "translations_deferred", "cache_marker_failures",
)
FLAGS = ("cache_refresh_failed", "cleanup_failed", "setup_failed")
ERROR_COUNTS = (
    "failed_pages", "failed_categories", "failed_deletions",
    "translations_failed", "cache_marker_failures",
)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def parse_summary(text):
    marker = "[Indexer Summary]"
    lines = [line.split(marker, 1)[1].strip()
             for line in text.splitlines() if marker in line]
    if len(lines) > 1:
        raise ValueError("multiple_summaries")
    try:
        return json.loads(lines[0] if lines else text.lstrip("\ufeff"),
                          object_pairs_hook=unique_object)
    except (ValueError, TypeError) as error:
        # Never echo parser errors that could contain raw log/secret values.
        raise ValueError("invalid_summary_json") from error


def assess(summary):
    result = {
        "summary_verdict": "unverified",
        "run_identity_verified": False,
        "translation_quality_verified": False,
        "notes": [],
    }
    if not isinstance(summary, dict):
        result["notes"].append("summary_object_required")
        return result
    required = ("status",) + COUNTS + FLAGS
    missing = [key for key in required if key not in summary]
    if missing:
        result["notes"].append("missing_required_fields")
        result["missing_fields"] = missing
        return result
    if (any(type(summary[key]) is not int or summary[key] < 0 for key in COUNTS)
            or any(type(summary[key]) is not bool for key in FLAGS)
            or summary["status"] not in ("complete", "in_progress", "failed")):
        result["notes"].append("invalid_field_type_or_value")
        return result
    # Whitelist fields: do not forward free-form text, IDs or unknown data.
    result["summary"] = {key: summary[key] for key in required}
    errors = any(summary[key] for key in ERROR_COUNTS + FLAGS)
    pending = summary["translations_pending"]
    if pending != summary["translations_failed"] + summary["translations_deferred"]:
        errors = True
        result["notes"].append("pending_counts_inconsistent")
    expected = "failed" if errors else ("in_progress" if pending else "complete")
    if errors:
        result["summary_verdict"] = "failed"
    elif summary["status"] == expected:
        result["summary_verdict"] = expected
    if summary["status"] != expected:
        result["notes"].append("status_counts_inconsistent")
    attempted = summary["translations_attempted"]
    completed = summary["translations_completed"]
    # Attempt counts may be per chunk, while completed/updated count pages.
    # Do not enforce attempted == completed or sum pending into updated.
    inconsistent_translations = (
        completed > attempted
        or completed > summary["updated"]
        or (expected == "complete" and completed == 0
            and (attempted > 0 or summary["updated"] > 0))
    )
    if inconsistent_translations:
        result["notes"].append("translation_counts_inconsistent")
        if not errors:
            result["summary_verdict"] = "unverified"
    # A new error field must not be silently ignored when the schema evolves.
    # Do not print unknown names or values: they can contain sensitive data.
    if set(summary) - set(required):
        result["notes"].append("unknown_summary_fields")
        if not errors:
            result["summary_verdict"] = "unverified"
    if expected == "complete":
        if summary["updated"] + summary["skipped"] != summary["discovered"]:
            result["summary_verdict"] = "unverified"
            result["notes"].append("document_counts_inconsistent")
        elif summary["discovered"] == 0:
            result["notes"].append("empty_discovery_requires_baseline_review")
        elif summary["updated"] == 0 and summary["skipped"] == summary["discovered"]:
            result["notes"].append("all_skipped_no_new_translation_evidence")
    if pending:
        result["notes"].append("translations_not_complete")
    result["notes"].append("verify_run_sha_event_attempt_and_conclusion_separately")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Local JSON or single-run log file")
    args = parser.parse_args(argv)
    try:
        result = assess(parse_summary(args.file.read_text(encoding="utf-8-sig")))
    except (OSError, UnicodeError, ValueError):
        result = {"summary_verdict": "unverified", "notes": ["input_unreadable_or_ambiguous"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {"complete": 0, "in_progress": 1, "failed": 1}.get(result["summary_verdict"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
