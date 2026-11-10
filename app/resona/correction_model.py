"""Correction preparation without Qt, live state mutation, or shared-memory writes."""
from dataclasses import dataclass
from pathlib import Path

from . import correction, validation


@dataclass(frozen=True)
class Snapshot:
    filters: list[dict]
    enabled: float
    curve: list[float]
    warning: str = ""


def prepare(info: dict | None, sample_rate: int, frequencies, enabled: float) -> Snapshot:
    info = info or {}
    filters = info.get("filters", [])
    warning = ""
    if info.get("kind") == "vdc" and info.get("text"):
        try:
            filters = correction.parse_vdc(info["text"], sample_rate)
        except ValueError as error:
            filters, enabled = [], 0
            warning = f"{error}; correction bypassed"
    curve = correction.response_db(filters, frequencies, sample_rate, info.get("preamp", 0)).round(2).tolist() \
        if filters else [0.0] * len(frequencies)
    return Snapshot(filters, enabled, curve, warning)


def from_file(path: Path, sample_rate: int) -> dict:
    text = path.read_text(errors="replace")
    if "SR_44100" in text or "SR_48000" in text or path.suffix.lower() == ".vdc":
        filters = correction.parse_vdc(text, sample_rate)
        info = {"name": path.stem, "source": "ViPER DDC", "kind": "vdc", "text": text,
                "filters": filters, "count": len(filters), "preamp": correction.safe_preamp(filters, sample_rate)}
    else:
        preamp, filters = correction.parse_parametric(text)
        if not filters:
            raise ValueError("no 'Filter: ON …' lines found")
        info = {"name": path.stem, "source": "EqualizerAPO / AutoEq file", "kind": "parametric",
                "filters": filters, "preamp": preamp}
    return validation.correction(info)


def describe(info: dict | None) -> dict:
    info = info or {}
    return {"name": info.get("name", ""), "source": info.get("source", ""), "kind": info.get("kind", ""),
            "count": len(info.get("filters", [])) or info.get("count", 0), "preamp": info.get("preamp", 0)}
