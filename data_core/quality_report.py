"""Data-quality report for the RPA data foundation.

Aggregates the outputs of cleaning, validation and splitting into a single,
human- and machine-readable report. The report makes it easy to judge whether
the dataset is trustworthy at a glance, per the Step 1 acceptance criteria:
total raw records, accepted, rejected, duplicate count, missing-value counts,
invalid-value counts, validation failures, cleaning transformations and the
final record counts (including the train/val/test/demo split).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from .cleaning import CleaningReport
from .validation import ValidationResult


@dataclass
class DataQualityReport:
    dataset_name: str
    generated_counts: Dict[str, int] = field(default_factory=dict)
    cleaning: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    splits: Dict[str, int] = field(default_factory=dict)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    trusted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "generated_counts": self.generated_counts,
            "total_raw": sum(self.generated_counts.values()),
            "cleaning": self.cleaning,
            "validation": self.validation,
            "splits": self.splits,
            "trusted": self.trusted,
            "tables": self.tables,
        }

    def to_json(self, path: str | Any) -> str:
        text = json.dumps(self.to_dict(), indent=2, default=str)
        p = open(path, "w", encoding="utf-8")  # noqa: SIM115
        p.write(text)
        p.close()
        return text

    def to_markdown(self) -> str:
        lines: List[str] = []
        add = lines.append
        add(f"# Data Quality Report — {self.dataset_name}\n")
        add(f"**Dataset trusted for insertion:** {self.trusted}\n")
        add(f"**Generated record counts:**\n")
        add("| Entity | Records |")
        add("|---|---|")
        for t, c in self.generated_counts.items():
            add(f"| {t} | {c} |")
        add("")
        add("## Cleaning summary\n")
        c = self.cleaning
        add(
            f"- raw: {c.get('total_raw')} | cleaned: {c.get('total_cleaned')} | "
            f"rejected: {c.get('total_rejected')} | duplicates removed: {c.get('total_duplicates')}"
        )
        add("\n### Per-entity cleaning\n")
        add("| Entity | Raw | Cleaned | Rejected | Dups |")
        add("|---|---|---|---|---|")
        for t, r in c.get("by_entity", {}).items():
            add(f"| {t} | {r['raw']} | {r['cleaned']} | {r['rejected']} | {r['duplicates_removed']} |")
        add("")
        add("### Cleaning transformations\n")
        any_t = False
        for t, r in c.get("by_entity", {}).items():
            for tr in r.get("transformations", []):
                any_t = True
                add(f"- `{t}.{tr['field']}`: {tr['rule']} (n={tr['count']})")
        if not any_t:
            add("- (no transformations applied)")
        add("")
        add("## Validation summary\n")
        v = self.validation
        add(
            f"- raw validated: {v.get('total_raw')} | accepted: {v.get('total_accepted')} | "
            f"rejected: {v.get('total_rejected')}"
        )
        fc = v.get("failure_counts_by_table", {})
        add(f"- failures by table: {fc if fc else 'none'}")
        add("\n| Table | Row | Field | Message |")
        add("|---|---|---|---|")
        for f in v.get("failures", [])[:200]:
            add(f"| {f['table']} | {f['row']} | {f['field']} | {f['message']} |")
        if len(v.get("failures", [])) > 200:
            add(f"\n_(truncated; {len(v['failures'])} total failures)_")
        add("")
        add("## Dataset splits\n")
        add("| Split | Records |")
        add("|---|---|")
        for name in ["train", "val", "test", "demo"]:
            add(f"| {name} | {self.splits.get(name, 0)} |")
        add("")
        return "\n".join(lines)


def build_quality_report(
    dataset_name: str,
    generated: Any,
    cleaning_report: CleaningReport,
    validation_result: ValidationResult,
    splits: Dict[str, pd.DataFrame],
) -> DataQualityReport:
    """Assemble a :class:`DataQualityReport` from the pipeline stages."""
    gen_counts = generated.counts() if hasattr(generated, "counts") else {
        t: len(f) for t, f in (generated if isinstance(generated, dict) else {}).items()
    }
    report = DataQualityReport(
        dataset_name=dataset_name,
        generated_counts=gen_counts,
        cleaning=cleaning_report.to_dict(),
        validation=validation_result.to_dict(),
        splits={k: int(len(v)) for k, v in splits.items()},
        tables=[],
    )
    report.trusted = validation_result.valid and validation_result.n_rejected == 0
    for table, frame in validation_result.accepted.items():
        report.tables.append(
            {
                "table": table,
                "rows": int(len(frame)),
                "columns": list(frame.columns),
            }
        )
    return report


__all__ = ["DataQualityReport", "build_quality_report"]
