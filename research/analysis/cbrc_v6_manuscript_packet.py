#!/usr/bin/env python3
"""Generate a manuscript-ready evidence packet from a completed v6 audit.

This script never decides the science itself. It consumes V6_BREADTH_AUDIT.json
and emits claim/table fragments. The packet is marked promotable only when the
pre-specified confirmatory gates have all passed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (float, int)):
        return f"{float(value):.{digits}f}"
    return str(value)


def escape_tex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def build(audit: dict[str, Any]) -> dict[str, Any]:
    clustered = audit["sceneClustered"]
    paired = clustered["pairedOpacityMinusTranslationNonzeroLocalRate"]
    ci = paired["ci95"]
    promotable = bool(audit.get("confirmatoryPass", False))

    claims = {
        "promotable": promotable,
        "independentSceneCount": int(audit["sceneCount"]),
        "datasetCount": int(audit["datasetCount"]),
        "pooledCaseCountSecondary": int(audit["pooledCaseCount"]),
        "meanSceneNonzeroLocalRateAdvantage": paired["mean"],
        "meanSceneNonzeroLocalRateAdvantageCi95": ci,
        "scenesWithNonzeroOpacityLocal": int(clustered["scenesWithNonzeroOpacityLocal"]),
        "scenesWithOpacityCrossover": int(clustered["scenesWithOpacityCrossover"]),
        "sameOpacityLegacyEnvelopeAblation": dict(
            clustered["sameOpacityLegacyEnvelopeAblation"]
        ),
        "certificateTightness": dict(clustered["certificateTightness"]),
        "datasetsWithNonzeroOpacityLocal": list(clustered["datasetsWithNonzeroOpacityLocal"]),
        "certificateExperimentValid": bool(
            audit["certificateAudit"]["certificateExperimentValid"]
        ),
        "confirmatoryGates": dict(audit["confirmatoryGates"]),
        "scientificBoundary": audit["scientificBoundary"],
    }

    methods = []
    for method, item in sorted(audit.get("baselineSceneSummary", {}).items()):
        methods.append(
            {
                "method": method,
                "scenes": int(item["scenes"]),
                "meanScenePassRate": item["meanScenePassRate"],
                "medianSceneWorkRatioFull": item["medianSceneWorkRatioFull"],
                "meanSceneFullRebuildRate": item["meanSceneFullRebuildRate"],
            }
        )

    return {
        "schemaVersion": 1,
        "artifact": "maveb-v6-manuscript-evidence-packet",
        "promotable": promotable,
        "claims": claims,
        "baselineSceneSummary": methods,
    }


def markdown(packet: dict[str, Any]) -> str:
    c = packet["claims"]
    ci = c["meanSceneNonzeroLocalRateAdvantageCi95"]
    lines = [
        "# MAVEB v6 manuscript evidence packet",
        "",
        f"Promotable: **{packet['promotable']}**",
        "",
        "## Confirmatory evidence",
        "",
        f"- Independent scenes: **{c['independentSceneCount']}**",
        f"- Dataset families: **{c['datasetCount']}**",
        (
            "- Mean per-scene non-zero LOCAL-rate advantage "
            f"(opacity certificate minus translation control): **{fmt(c['meanSceneNonzeroLocalRateAdvantage'])}**"
        ),
        f"- Dataset-stratified scene-bootstrap 95% CI: **[{fmt(ci[0])}, {fmt(ci[1])}]**",
        (
            "- Scenes with at least one certified non-zero opacity LOCAL case: "
            f"**{c['scenesWithNonzeroOpacityLocal']}**"
        ),
        f"- Scenes with at least one opacity crossover: **{c['scenesWithOpacityCrossover']}**",
        (
            "- Scenes where the delta certificate rescues at least one same-opacity case "
            "that the legacy envelope would reject: "
            f"**{c['sameOpacityLegacyEnvelopeAblation']['scenesWithAtLeastOneRescuedCase']}**"
        ),
        (
            "- Median scene legacy-envelope / delta residual-bound ratio: "
            f"**{fmt(c['sameOpacityLegacyEnvelopeAblation']['medianSceneLegacyToDeltaResidualBoundRatio'])}**"
        ),
        (
            "- Median of per-scene maximum actual/epsilon among certified opacity LOCAL cases: "
            f"**{fmt(c['certificateTightness']['medianOfSceneMaximumActualToEpsilon'])}**"
        ),
        (
            "- Maximum scene maximum actual/epsilon: "
            f"**{fmt(c['certificateTightness']['maximumSceneMaximumActualToEpsilon'])}**"
        ),
        (
            "- Pooled parameterized cases: "
            f"**{c['pooledCaseCountSecondary']}** (secondary descriptive evidence only)"
        ),
        "",
        "## Baselines and ablations — scene aggregates",
        "",
        "| Method | Scenes | Mean pass rate | Median work/FULL | Mean FULL-rebuild rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in packet["baselineSceneSummary"]:
        lines.append(
            f"| {item['method']} | {item['scenes']} | "
            f"{fmt(item['meanScenePassRate'])} | "
            f"{fmt(item['medianSceneWorkRatioFull'])} | "
            f"{fmt(item['meanSceneFullRebuildRate'])} |"
        )
    lines += [
        "",
        "## Scientific boundary",
        "",
        c["scientificBoundary"],
        "",
    ]
    if not packet["promotable"]:
        lines += [
            "This packet is not promotable because one or more pre-specified "
            "confirmatory gates are OPEN. Do not copy favorable subsets into the manuscript.",
            "",
        ]
    return "\n".join(lines)


def latex(packet: dict[str, Any]) -> str:
    c = packet["claims"]
    ci = c["meanSceneNonzeroLocalRateAdvantageCi95"]
    lines = [
        "% Auto-generated from the frozen MAVEB v6 confirmatory audit.",
        "% Do not edit values manually; regenerate from V6_BREADTH_AUDIT.json.",
        f"\\newcommand{{\\MavebVSixSceneCount}}{{{c['independentSceneCount']}}}",
        f"\\newcommand{{\\MavebVSixDatasetCount}}{{{c['datasetCount']}}}",
        f"\\newcommand{{\\MavebVSixPooledCaseCount}}{{{c['pooledCaseCountSecondary']}}}",
        f"\\newcommand{{\\MavebVSixSceneDelta}}{{{fmt(c['meanSceneNonzeroLocalRateAdvantage'])}}}",
        f"\\newcommand{{\\MavebVSixSceneDeltaLow}}{{{fmt(ci[0])}}}",
        f"\\newcommand{{\\MavebVSixSceneDeltaHigh}}{{{fmt(ci[1])}}}",
        f"\\newcommand{{\\MavebVSixPositiveScenes}}{{{c['scenesWithNonzeroOpacityLocal']}}}",
        f"\\newcommand{{\\MavebVSixCrossoverScenes}}{{{c['scenesWithOpacityCrossover']}}}",
        (
            f"\\newcommand{{\\MavebVSixRescuedScenes}}"
            f"{{{c['sameOpacityLegacyEnvelopeAblation']['scenesWithAtLeastOneRescuedCase']}}}"
        ),
        "",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Method & Scenes & Pass rate & Median work/FULL & FULL rebuild \\\\",
        "\\midrule",
    ]
    for item in packet["baselineSceneSummary"]:
        lines.append(
            f"{escape_tex(item['method'])} & {item['scenes']} & "
            f"{fmt(item['meanScenePassRate'])} & "
            f"{fmt(item['medianSceneWorkRatioFull'])} & "
            f"{fmt(item['meanSceneFullRebuildRate'])} \\\\"
        )
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    packet = build(load_json(args.audit.resolve()))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    (output / "V6_MANUSCRIPT_CLAIMS.json").write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "V6_MANUSCRIPT_PACKET.md").write_text(
        markdown(packet),
        encoding="utf-8",
    )
    (output / "V6_MANUSCRIPT_TABLES.tex").write_text(
        latex(packet),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "promotable": packet["promotable"],
                "claims": str(output / "V6_MANUSCRIPT_CLAIMS.json"),
                "markdown": str(output / "V6_MANUSCRIPT_PACKET.md"),
                "latex": str(output / "V6_MANUSCRIPT_TABLES.tex"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
