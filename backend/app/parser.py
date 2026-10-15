"""Parser for _sae-test Jira comments (renderedBody HTML). Pure functions, no DB access."""
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from .jobnames import normalize_job_name

SUITE_LABEL = re.compile(r"\b([A-Z][A-Z0-9_]{1,19})\s*:")
GHOST_VERSION = re.compile(r"Ghost version:\s*(\S+)", re.I)
SANDBOX_ROW = re.compile(r"^Sandbox-Testing\s*#(\d+)", re.I)
ARTIFACT_TYPES = {"GhostAsanBuild": "GhostAsan", "LsanBuild": "Lsan", "TsanBuild": "Tsan"}


@dataclass
class ParsedArtifact:
    artifact_type: str
    download_url: str
    wget_command: str | None


@dataclass
class ParsedSuite:
    suite_name: str
    job_link: str | None = None
    report_link: str | None = None
    siam_link: str | None = None


@dataclass
class ParsedJob:
    job_name: str
    job_status: str
    outcome: str
    result_text: str
    job_url: str | None = None
    summary_url: str | None = None
    analysis_url: str | None = None
    plots_url: str | None = None
    artifacts: list[ParsedArtifact] = field(default_factory=list)
    suites: list[ParsedSuite] = field(default_factory=list)


@dataclass
class ParsedRun:
    ticket_key: str
    title: str
    alsi_version: str | None
    metadata_mode: str
    sandbox_build_no: int | None
    sandbox_build_url: str | None
    sandbox_status: str | None
    ghost_version: str | None
    not_selected_jobs: list[str]
    ghost_crashes_url: str | None
    jobs: list[ParsedJob]


class ParseError(ValueError):
    pass


class NotARunComment(ParseError):
    """Comment by _sae-test that is not a sandbox run report (e.g. legacy format)."""


def derive_outcome(text: str | None) -> str:
    t = (text or "").lower()
    if "detected degradation" in t:
        return "DEGRADED"
    if "passed" in t:
        return "PASSED"
    if "no information found" in t:
        return "NO_INFO"
    return "NA"


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,:;])", r"\1", text)


def _link_by_text(cell: Tag, label: str) -> str | None:
    for a in cell.find_all("a", href=True):
        if a.get_text(strip=True).lower() == label:
            return a["href"]
    return None


def _parse_suites(cell: Tag) -> list[ParsedSuite]:
    suites: list[ParsedSuite] = []
    current: ParsedSuite | None = None
    for node in cell.descendants:
        if isinstance(node, NavigableString):
            if node.find_parent("a") is not None:
                continue
            m = SUITE_LABEL.search(str(node))
            if m:
                current = ParsedSuite(suite_name=m.group(1))
                suites.append(current)
        elif node.name == "a" and current is not None and node.get("href"):
            label = node.get_text(strip=True).lower()
            if label == "job link":
                current.job_link = node["href"]
            elif label == "report":
                current.report_link = node["href"]
            elif label == "siam link":
                current.siam_link = node["href"]
    return suites


def _parse_artifacts(cell: Tag, text: str) -> list[ParsedArtifact]:
    out = []
    for a in cell.find_all("a", href=True):
        url = a["href"]
        m = re.search(r"-(GhostAsanBuild|LsanBuild|TsanBuild)\.bz2", url)
        if not m:
            continue
        cmd = re.search(r"(wget\b.*?" + re.escape(url) + ")", text)
        out.append(
            ParsedArtifact(ARTIFACT_TYPES[m.group(1)], url, cmd.group(1) if cmd else None)
        )
    return out


def _parse_header(soup: BeautifulSoup) -> tuple[str, str]:
    a = soup.find("a", attrs={"data-issue-key": True}) or soup.find(
        "a", string=re.compile(r"^[A-Z]+-\d+$")
    )
    if a is None:
        raise NotARunComment("no GREL ticket link: not a sandbox run comment")
    key = a.get("data-issue-key") or a.get_text(strip=True)
    p = a.find_parent("p") or a.parent
    text = _clean(p.get_text(" ", strip=True))
    title = re.sub(r"^" + re.escape(key) + r"\s*-\s*", "", text).strip()
    return key, title or key


def _metadata_mode(soup: BeautifulSoup) -> str:
    node = soup.find(string=re.compile(r"\(\s*Tests with", re.I))
    if node is not None:
        t = str(node).lower()
        if "non-default" in t or "user-specified" in t:
            return "NON_DEFAULT"
    return "DEFAULT"


def parse_comment_html(html: str) -> ParsedRun:
    soup = BeautifulSoup(html, "html.parser")
    key, title = _parse_header(soup)

    alsi = None
    m = re.search(r"ALSI version:\s*(\S+)", soup.get_text(" "), re.I)
    if m:
        alsi = m.group(1).strip().lower()

    sandbox_no = sandbox_url = sandbox_status = None
    jobs: dict[str, ParsedJob] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 3:
            continue
        name_cell, status_cell, result_cell = tds
        link = name_cell.find("a")
        raw_name = _clean(link.get_text(" ", strip=True) if link else name_cell.get_text(" "))
        status = _clean(status_cell.get_text(" "))
        sm = SANDBOX_ROW.match(raw_name)
        if sm:
            sandbox_no = int(sm.group(1))
            sandbox_url = link["href"] if link and link.get("href") else None
            sandbox_status = status or None
            continue
        if not raw_name or not status:
            continue
        name = normalize_job_name(raw_name)
        text = _clean(result_cell.get_text(" "))
        job = ParsedJob(
            job_name=name,
            job_status=status,
            outcome=derive_outcome(text),
            result_text=text,
            job_url=link["href"] if link and link.get("href") else None,
        )
        if name in ("PERF", "LOAD"):
            job.summary_url = _link_by_text(result_cell, "summary")
            job.analysis_url = _link_by_text(result_cell, "analysis")
            job.plots_url = _link_by_text(result_cell, "plots")
        if name.endswith(" build"):
            job.artifacts = _parse_artifacts(result_cell, text)
        if name == "Baseline Regression":
            job.suites = _parse_suites(result_cell)
        jobs[name] = job

    ghost_version = None
    for jn in ("PERF", "LOAD"):
        if jn in jobs:
            gm = GHOST_VERSION.search(jobs[jn].result_text)
            if gm:
                ghost_version = gm.group(1)
                break

    not_selected: list[str] = []
    node = soup.find(string=re.compile(r"\(\s*Not selected\s*:", re.I))
    if node is not None:
        body = re.sub(r"^.*?Not selected\s*:", "", str(node), flags=re.I | re.S)
        body = body.split(")")[0]
        for part in body.split(","):
            if part.strip():
                n = normalize_job_name(part)
                if n not in not_selected:
                    not_selected.append(n)

    crashes = None
    for a in soup.find_all("a", href=True):
        p = a.find_parent(["h6", "p"])
        if p is not None and "ghost crashes" in p.get_text(" ").lower():
            crashes = a["href"]
            break

    return ParsedRun(
        ticket_key=key,
        title=title,
        alsi_version=alsi,
        metadata_mode=_metadata_mode(soup),
        sandbox_build_no=sandbox_no,
        sandbox_build_url=sandbox_url,
        sandbox_status=sandbox_status,
        ghost_version=ghost_version,
        not_selected_jobs=not_selected,
        ghost_crashes_url=crashes,
        jobs=list(jobs.values()),
    )


def parse_owner_field(value) -> str | None:
    """SQA/DevQA custom field: user object, list of users/strings, string or null."""
    if value is None:
        return None
    if isinstance(value, dict):
        v = value.get("displayName") or value.get("name")
        return str(v) if v else None
    if isinstance(value, (list, tuple)):
        parts = [p for p in (parse_owner_field(x) for x in value) if p]
        return ", ".join(parts) if parts else None
    s = str(value).strip()
    return s or None


BATS_GROUP = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*:\s*")


def parse_bats_groups(html: str) -> list[dict]:
    """BATS cell -> [{name, name_url, links: [{label, url}], note}], one per <br>-separated line.

    Lines that are not "<group>: ..." (e.g. "See <url>") are ignored.
    """
    soup = BeautifulSoup(html, "html.parser")
    cell = None
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) == 3 and normalize_job_name(_clean(tds[0].get_text(" "))) == "BATS":
            cell = tds[2]
            break
    if cell is None:
        return []
    lines: list[list] = [[]]
    for node in cell.children:
        if isinstance(node, Tag) and node.name == "br":
            lines.append([])
        else:
            lines[-1].append(node)
    groups = []
    for nodes in lines:
        text = _clean("".join(n.get_text(" ") if isinstance(n, Tag) else str(n) for n in nodes))
        m = BATS_GROUP.match(text)
        if not m or m.group(1).lower().startswith("http"):
            continue
        name = m.group(1)
        anchors = [n for n in nodes if isinstance(n, Tag) and n.name == "a" and n.get("href")]
        name_url = None
        if anchors and _clean(anchors[0].get_text(" ")) == name:
            name_url = anchors.pop(0)["href"]
        links = [{"label": _clean(a.get_text(" ")), "url": a["href"]} for a in anchors]
        note = None
        if not links:
            note = text[m.end():].strip() or None
        groups.append({"name": name, "name_url": name_url, "links": links, "note": note})
    return groups
