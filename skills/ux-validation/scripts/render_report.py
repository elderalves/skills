import argparse
import base64
import json
from html import escape
from pathlib import Path
from string import Template
from tempfile import NamedTemporaryFile


OUTCOMES = {"completed": "Completed", "blocked": "Blocked", "not-tested": "Not tested"}
REVIEWS = {"completed": "Completed", "blocked": "Blocked", "unavailable": "Unavailable"}
CONFIDENCE = {"observed": "Observed", "hypothesis": "Hypothesis"}
PRIORITIES = {"P0": "Stops the task", "P1": "Serious obstacle", "P2": "Avoidable effort", "P3": "Minor friction"}
CATEGORIES = {
    "fix": ("Needs to be Fixed", "What to change"),
    "improvement": ("Needs Improvement", "What to change"),
    "idea": ("Ideas", "What to try"),
    "good": ("Good!", "What works"),
}
PROBLEM_CATEGORIES = {"fix", "improvement"}
TAKEAWAYS = {"ux": "Key UX Takeaways", "ui": "Key UI Takeaways"}
REVIEWERS = {"task-friction": "Task friction", "heuristics": "Heuristics and mental model"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
VIDEO_TYPES = {".mp4": "video/mp4", ".webm": "video/webm"}


def check_type(value, expected, label):
    if type(value) is not expected:
        names = {dict: "an object", list: "a list", str: "a string"}
        raise ValueError(f"{label} must be {names[expected]}")
    return value


def check_text(value, label):
    if not check_type(value, str, label).strip():
        raise ValueError(f"{label} must contain text")
    return value


def check_choice(value, choices, label):
    if check_text(value, label) not in choices:
        raise ValueError(f"{label} must be one of {', '.join(choices)}")


def load_media(media, label, run_dir, mime_types):
    file = Path(check_text(media.get("file"), f"{label}.file"))
    mime = mime_types.get(file.suffix.lower())
    if file.is_absolute() or file.parts[:1] != ("assets",) or not mime:
        raise ValueError(f"{label}.file must be under assets/ and end in {', '.join(mime_types)}")
    path = (run_dir / file).resolve()
    if not path.is_relative_to(run_dir / "assets") or not path.is_file():
        raise ValueError(f"{label}.file must resolve to a file under assets/: {file}")
    content = path.read_bytes()
    if not content:
        raise ValueError(f"{label}.file is empty: {file}")
    media["mime"] = mime
    media["data"] = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def check_marker(marker, label):
    check_type(marker, dict, label)
    check_text(marker.get("label"), f"{label}.label")
    for axis in ("x", "y"):
        coordinate = marker.get(axis)
        if type(coordinate) not in (int, float) or not 0 <= coordinate <= 100:
            raise ValueError(f"{label}.{axis} must be a number between 0 and 100")

    if "bounds" in marker:
        bounds = check_type(marker["bounds"], dict, f"{label}.bounds")
        for axis, dimension in (("x", "width"), ("y", "height")):
            start = bounds.get(axis)
            size = bounds.get(dimension)
            if type(start) not in (int, float) or not 0 <= start <= 100:
                raise ValueError(f"{label}.bounds.{axis} must be a number between 0 and 100")
            if type(size) not in (int, float) or not 0 < size <= 100 or start + size > 100:
                raise ValueError(f"{label}.bounds.{dimension} must be positive and stay within the screenshot")


def load_report(source):
    report = check_type(json.loads(source.read_text(encoding="utf-8")), dict, "report")
    run_dir = source.parent.resolve()
    categorized = "format_version" in report
    if categorized:
        version = report["format_version"]
        if type(version) is not int or version != 2:
            raise ValueError("format_version must be 2 for a categorized report")
        if "takeaways" in report:
            takeaways = check_type(report["takeaways"], dict, "takeaways")
            for key in TAKEAWAYS:
                check_text(takeaways.get(key), f"takeaways.{key}")

    scope = check_type(report.get("scope"), dict, "scope")
    for key in ("url", "section", "user", "task"):
        check_text(scope.get(key), f"scope.{key}")

    outcome = check_type(report.get("outcome"), dict, "outcome")
    check_choice(outcome.get("status"), OUTCOMES, "outcome.status")
    check_text(outcome.get("observation"), "outcome.observation")

    coverage = check_type(report.get("coverage"), dict, "coverage")
    if "capture" in coverage:
        check_text(coverage["capture"], "coverage.capture")
    gaps = check_type(coverage.get("gaps"), list, "coverage.gaps")
    for gap in gaps:
        check_text(gap, "coverage gap")
    reviewers = check_type(coverage.get("reviewers"), dict, "coverage.reviewers")
    for role in REVIEWERS:
        label = f"coverage.reviewers.{role}"
        review = check_type(reviewers.get(role), dict, label)
        check_choice(review.get("status"), REVIEWS, f"{label}.status")
        if review["status"] != "completed" or "note" in review:
            check_text(review.get("note"), f"{label}.note")

    steps = check_type(report.get("steps"), list, "steps")
    if not steps and (outcome["status"] != "not-tested" or not gaps):
        raise ValueError("An empty walkthrough requires a not-tested outcome and a coverage gap")
    marker_findings = []
    for number, step in enumerate(steps, 1):
        label = f"step {number}"
        check_type(step, dict, label)
        for field in ("action", "observation"):
            check_text(step.get(field), f"{label}.{field}")
        if "viewport" in step:
            check_text(step["viewport"], f"{label}.viewport")
        if "image" in step:
            image = check_type(step["image"], dict, f"{label}.image")
            check_text(image.get("alt"), f"{label}.image.alt")
            markers = check_type(image.get("markers", []), list, f"{label}.image.markers")
            for index, marker in enumerate(markers, 1):
                marker_label = f"{label} marker {index}"
                check_marker(marker, marker_label)
                if marker.get("finding") is not None:
                    marker_findings.append((number, marker_label, marker["finding"]))
            load_media(image, f"{label}.image", run_dir, IMAGE_TYPES)
        if "clip" in step:
            clip = check_type(step["clip"], dict, f"{label}.clip")
            check_text(clip.get("caption"), f"{label}.clip.caption")
            load_media(clip, f"{label}.clip", run_dir, VIDEO_TYPES)

    findings = check_type(report.get("findings"), list, "findings")
    for number, finding in enumerate(findings, 1):
        label = f"finding {number}"
        check_type(finding, dict, label)
        for key in ("title", "what", "why"):
            check_text(finding.get(key), f"{label}.{key}")
        if "review_note" in finding:
            check_text(finding["review_note"], f"{label}.review_note")
        if categorized:
            check_choice(finding.get("category"), CATEGORIES, f"{label}.category")
            if finding["category"] in PROBLEM_CATEGORIES:
                check_choice(finding.get("priority"), PRIORITIES, f"{label}.priority")
            elif "priority" in finding:
                raise ValueError(f"{label}.priority is only used for fix and improvement findings")
        else:
            check_choice(finding.get("priority"), PRIORITIES, f"{label}.priority")
        check_choice(finding.get("confidence"), CONFIDENCE, f"{label}.confidence")
        references = check_type(finding.get("steps"), list, f"{label}.steps")
        if not references or any(type(n) is not int or not 1 <= n <= len(steps) for n in references):
            raise ValueError(f"{label}.steps must cite at least one existing step by number")

    for step_number, label, finding_number in marker_findings:
        if type(finding_number) is not int or not 1 <= finding_number <= len(findings):
            raise ValueError(f"{label}.finding must reference an existing finding by number or be null")
        if step_number not in findings[finding_number - 1]["steps"]:
            raise ValueError(f"{label}.finding references finding {finding_number}, which does not cite step {step_number}")
    return report


def finding_groups(report):
    findings = sorted(
        ({**finding, "number": number} for number, finding in enumerate(report["findings"], 1)),
        key=lambda finding: finding.get("priority", ""),
    )
    if not findings:
        return []
    if "format_version" not in report:
        return [{"heading": None, "whatLabel": "What should improve", "findings": findings}]

    groups = []
    for category, (heading, what_label) in CATEGORIES.items():
        items = [finding for finding in findings if finding["category"] == category]
        if items:
            groups.append({"heading": heading, "whatLabel": what_label, "findings": items})
    return groups


def report_takeaways(report):
    if "format_version" not in report or "takeaways" not in report:
        return []
    return [{"heading": heading, "text": report["takeaways"][key]} for key, heading in TAKEAWAYS.items()]


def render_image(image):
    pins = []
    labels = []
    for number, marker in enumerate(image.get("markers", []), 1):
        x, y = marker["x"], marker["y"]
        pins.append(f'<span class="pin" style="left:{x:g}%;top:{y:g}%" aria-hidden="true">{number}</span>')
        labels.append(f'<li>{escape(marker["label"])}</li>')
    caption = f'<figcaption><ol>{"".join(labels)}</ol></figcaption>' if labels else ""
    return (
        f'<figure><div class="image"><img src="{image["data"]}" alt="{escape(image["alt"])}">'
        f'{"".join(pins)}</div>{caption}</figure>'
    )


def render_step(number, step):
    viewport = f'<p class="viewport">{escape(step["viewport"])}</p>' if "viewport" in step else ""
    image = render_image(step["image"]) if "image" in step else ""
    video = ""
    if "clip" in step:
        clip = step["clip"]
        video = (
            f'<figure><video controls playsinline preload="metadata" aria-labelledby="clip-{number}">'
            f'<source src="{clip["data"]}" type="{clip["mime"]}"></video>'
            f'<figcaption id="clip-{number}">{escape(clip["caption"])}</figcaption></figure>'
        )
    return (
        f'<article class="card step" id="step-{number}">'
        f'<h3><span class="step-number">{number}.</span> {escape(step["action"])}</h3>'
        f'{viewport}<p>{escape(step["observation"])}</p>{image}{video}</article>'
    )


def render_finding(finding, what_label, heading_tag):
    priority = finding.get("priority")
    priority_tag = ""
    if priority:
        priority_tag = f'<span class="priority {priority.lower()}">{priority} · {PRIORITIES[priority]}</span>'
    confidence = finding["confidence"]
    links = " ".join(f'<a href="#step-{n}">Step {n}</a>' for n in dict.fromkeys(finding["steps"]))
    note = ""
    if "review_note" in finding:
        note = f'<p class="review-note"><strong>Reviewer disagreement</strong> {escape(finding["review_note"])}</p>'
    return (
        f'<article class="card finding"><div class="tags">'
        f'{priority_tag}'
        f'<span class="confidence {confidence}">{CONFIDENCE[confidence]}</span></div>'
        f'<{heading_tag}>{escape(finding["title"])}</{heading_tag}>'
        f'<dl><dt>{escape(what_label)}</dt><dd>{escape(finding["what"])}</dd>'
        f'<dt>Why it matters</dt><dd>{escape(finding["why"])}</dd></dl>{note}'
        f'<p class="evidence-links"><strong>Evidence</strong> {links}</p></article>'
    )


def render_findings(report):
    sections = []
    for group in finding_groups(report):
        heading = group["heading"]
        heading_tag = "h4" if heading else "h3"
        cards = "\n".join(render_finding(finding, group["whatLabel"], heading_tag) for finding in group["findings"])
        if heading:
            cards = f'<section class="finding-group"><h3>{escape(heading)}</h3>{cards}</section>'
        sections.append(cards)
    return "\n".join(sections) or '<p class="card">No findings recorded.</p>'


def render_coverage(coverage):
    capture = ""
    if "capture" in coverage:
        capture = f'<p class="capture"><strong>Browser capture</strong> {escape(coverage["capture"])}</p>'
    reviews = []
    for role, label in REVIEWERS.items():
        review = coverage["reviewers"][role]
        status = REVIEWS[review["status"]]
        note = f'<p>{escape(review["note"])}</p>' if "note" in review else ""
        reviews.append(f'<li><strong>{label}</strong><span>{status}</span>{note}</li>')
    gaps = "".join(f'<li>{escape(gap)}</li>' for gap in coverage["gaps"])
    gap_list = f'<h3>Coverage gaps</h3><ul class="gaps">{gaps}</ul>' if gaps else ""
    return f'{capture}<ul class="reviews">{"".join(reviews)}</ul>{gap_list}'


def render_report(report):
    scope = report["scope"]
    outcome = report["outcome"]
    steps = "\n".join(render_step(n, step) for n, step in enumerate(report["steps"], 1))
    takeaways = "".join(
        f'<div class="takeaway"><h3>{escape(item["heading"])}</h3><p>{escape(item["text"])}</p></div>'
        for item in report_takeaways(report)
    )
    template = Path(__file__).resolve().parents[1] / "assets" / "report-template.html"
    return Template(template.read_text(encoding="utf-8")).substitute(
        section=escape(scope["section"]),
        task=escape(scope["task"]),
        user=escape(scope["user"]),
        url=escape(scope["url"]),
        status=outcome["status"],
        outcome=OUTCOMES[outcome["status"]],
        observation=escape(outcome["observation"]),
        takeaways=takeaways,
        findings=render_findings(report),
        steps=steps or '<p class="card">No walkthrough steps recorded.</p>',
        coverage=render_coverage(report["coverage"]),
    )


def write_report(output, report_html, default_mode):
    with NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as temporary:
        path = Path(temporary.name)
        try:
            temporary.write(report_html)
            temporary.close()
            try:
                mode = output.stat().st_mode
            except FileNotFoundError:
                mode = default_mode
            path.chmod(mode & 0o666)
            path.replace(output)
        finally:
            path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Render a UX validation run as offline HTML.")
    parser.add_argument("report", type=Path, help="path to report.json")
    source = parser.parse_args().report
    if source.suffix.lower() != ".json":
        parser.error("report input must be a JSON file")
    output = source.with_name("report.html")
    try:
        report = load_report(source)
        write_report(output, render_report(report), source.stat().st_mode)
    except (OSError, ValueError) as error:
        parser.exit(1, f"UX validation report: {error}\n")
    print(output.resolve())


if __name__ == "__main__":
    main()
