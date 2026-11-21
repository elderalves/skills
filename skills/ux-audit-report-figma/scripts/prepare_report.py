import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ux-validation" / "scripts"))
from render_report import load_report


def project_setting(run_dir):
    for parent in run_dir.parents:
        if parent.name == "validation" and parent.parent.name == ".ux":
            return parent.parent / "figma-report.json"
        candidate = parent / ".ux" / "figma-report.json"
        if candidate.is_file():
            return candidate
    return None


def load_destination(setting):
    if setting is None or not setting.exists():
        return None

    config = json.loads(setting.read_text(encoding="utf-8"))
    file_url = config.get("fileUrl") if isinstance(config, dict) else None
    if not isinstance(file_url, str):
        raise ValueError(f"{setting} needs a fileUrl for an editable Figma Design file")

    url = urlsplit(file_url)
    match = re.fullmatch(r"/design/([A-Za-z0-9]+)(?:/[^/]*)?/?", url.path)
    if url.scheme != "https" or url.netloc not in {"figma.com", "www.figma.com"} or not match:
        raise ValueError(f"{setting} needs a fileUrl from https://www.figma.com/design/")
    return {"fileUrl": file_url, "fileKey": match[1]}


def evidence_step(number, step, run_dir):
    result = {"number": number, "action": step["action"], "observation": step["observation"]}
    if "viewport" in step:
        result["viewport"] = step["viewport"]
    if "image" in step:
        image = step["image"]
        result["image"] = {
            "path": str((run_dir / image["file"]).resolve()),
            "mime": image["mime"],
            "alt": image["alt"],
            "markers": image.get("markers", []),
        }
    return result


def prepare(run_dir):
    source = run_dir / "report.json"
    report = load_report(source)
    setting = project_setting(run_dir)
    steps = report["steps"]
    cited = sorted({number for finding in report["findings"] for number in finding["steps"]})
    return {
        "runId": run_dir.name,
        "runDirectory": str(run_dir),
        "projectSetting": str(setting) if setting else None,
        "destination": load_destination(setting),
        "scope": report["scope"],
        "outcome": report["outcome"],
        "findings": report["findings"],
        "coverage": report["coverage"],
        "evidence": [evidence_step(number, steps[number - 1], run_dir) for number in cited],
        "clips": [
            {"step": number, "caption": step["clip"]["caption"]}
            for number, step in enumerate(steps, 1)
            if "clip" in step
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare a UX validation run for the Figma report skill.")
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    try:
        report = prepare(args.run_directory.resolve(strict=True))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot prepare Figma audit report: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
