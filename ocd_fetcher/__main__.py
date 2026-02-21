import argparse
import csv
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

try:
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUROPE_PMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
UNPAYWALL = "https://api.unpaywall.org/v2"
SPORT_KEYWORDS = ["baseball", "gymnastics", "tennis", "judo", "handball", "volleyball", "softball", "pitcher", "throwing"]


@dataclass
class PaperRecord:
    PMID: str
    DOI: str
    PMCID: str
    Title: str
    Authors: str
    Year: str
    Journal: str
    Abstract: str
    PublicationType: str
    Keywords: str
    StudyDesign: str
    Sport: str
    OA: bool
    PDF_URL: str
    Source: str


class RateLimiter:
    def __init__(self, per_sec: float = 3.0):
        self.delay = 1.0 / per_sec
        self.last_ts = 0.0

    def wait(self) -> None:
        elapsed = time.time() - self.last_ts
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self.last_ts = time.time()


def parse_simple_yaml(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(0, out)]
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, _, val = raw.strip().partition(":")
        val = val.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        cur = stack[-1][1]
        if not val:
            cur[key] = {}
            stack.append((indent, cur[key]))
        else:
            if val.lower() in {"null", "none"}:
                cur[key] = None
            elif val.lower() in {"true", "false"}:
                cur[key] = val.lower() == "true"
            elif re.fullmatch(r"-?\d+", val):
                cur[key] = int(val)
            else:
                cur[key] = val.strip("'\"")
    return out


def load_config(path: Path) -> dict[str, Any]:
    txt = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(txt)
    return parse_simple_yaml(txt)


def setup_logger(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("ocd_fetcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def safe_request(limiter: RateLimiter, url: str, params: dict[str, Any] | None = None, timeout: int = 30, retries: int = 4) -> tuple[bytes, dict[str, str]]:
    full_url = url
    if params:
        full_url = f"{url}?{urllib.parse.urlencode(params)}"
    last_err = None
    for i in range(retries):
        try:
            limiter.wait()
            req = urllib.request.Request(full_url, headers={"User-Agent": "ocd-fetcher/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), dict(resp.headers.items())
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"request failed: {full_url} err={last_err}")


def build_query(config: dict[str, Any], args: argparse.Namespace) -> str:
    if args.query_override:
        return args.query_override
    query = config["search"]["base_query"]
    exclude = config["search"].get("exclude_query")
    return f"({query}) NOT ({exclude})" if exclude else query


def search_pubmed(limiter: RateLimiter, query: str, max_results: int, since_year: int | None, until_year: int | None, email: str | None) -> list[str]:
    params: dict[str, Any] = {"db": "pubmed", "term": query, "retmode": "json", "retmax": max_results, "sort": "pub date"}
    if since_year or until_year:
        params["datetype"] = "pdat"
    if since_year:
        params["mindate"] = since_year
    if until_year:
        params["maxdate"] = until_year
    if email:
        params["email"] = email
    body, _ = safe_request(limiter, f"{NCBI_BASE}/esearch.fcgi", params=params)
    return json.loads(body.decode("utf-8")).get("esearchresult", {}).get("idlist", [])


def chunked(items: list[str], n: int = 100):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def text_or_empty(elem: ET.Element | None, xpath: str) -> str:
    if elem is None:
        return ""
    found = elem.find(xpath)
    return (found.text or "").strip() if found is not None else ""


def infer_study_design(pub_types: str, title: str, abstract: str) -> str:
    text = f"{pub_types} {title} {abstract}".lower()
    if "review" in text or "meta-analysis" in text:
        return "review"
    if "epidemiolog" in text or "incidence" in text or "prevalence" in text:
        return "epidemiology"
    if any(k in text for k in ["ultrasound", "mri", "ct", "imaging"]):
        return "diagnostic"
    if any(k in text for k in ["surgery", "operative", "arthroscop"]):
        return "surgery"
    if any(k in text for k in ["prospective", "retrospective", "cohort"]):
        return "clinical"
    return "other"


def infer_sport(text: str) -> str:
    lower = text.lower()
    return "; ".join([s for s in SPORT_KEYWORDS if s in lower])


def parse_article(article: ET.Element) -> PaperRecord:
    medline = article.find("MedlineCitation")
    article_node = medline.find("Article") if medline is not None else None
    pmid = text_or_empty(medline, "PMID")
    title = article_node.findtext("ArticleTitle", default="") if article_node is not None else ""

    abstract_parts = []
    if article_node is not None and article_node.find("Abstract") is not None:
        for txt in article_node.findall("Abstract/AbstractText"):
            label = txt.attrib.get("Label", "").strip()
            body = "".join(txt.itertext()).strip()
            abstract_parts.append(f"{label}: {body}" if label else body)
    abstract_text = "\n".join([x for x in abstract_parts if x])

    authors = []
    if article_node is not None:
        for auth in article_node.findall("AuthorList/Author"):
            name = f"{text_or_empty(auth, 'LastName')} {text_or_empty(auth, 'Initials')}".strip()
            if name:
                authors.append(name)

    pub_types = [pt.text.strip() for pt in article_node.findall("PublicationTypeList/PublicationType") if pt.text] if article_node is not None else []

    keywords = []
    if medline is not None:
        keywords.extend(["".join(k.itertext()).strip() for k in medline.findall("KeywordList/Keyword")])
        keywords.extend(["".join(k.itertext()).strip() for k in medline.findall("MeshHeadingList/MeshHeading/DescriptorName")])
    keywords = [k for k in keywords if k]

    doi, pmcid = "", ""
    pubmed_data = article.find("PubmedData")
    if pubmed_data is not None:
        for aid in pubmed_data.findall("ArticleIdList/ArticleId"):
            t = aid.attrib.get("IdType", "").lower()
            v = (aid.text or "").strip()
            if t == "doi" and not doi:
                doi = v
            if t == "pmc" and not pmcid:
                pmcid = v

    return PaperRecord(
        PMID=pmid,
        DOI=doi,
        PMCID=pmcid,
        Title=title,
        Authors="; ".join(authors),
        Year=text_or_empty(article_node, "Journal/JournalIssue/PubDate/Year") or text_or_empty(article_node, "ArticleDate/Year"),
        Journal=text_or_empty(article_node, "Journal/Title"),
        Abstract=abstract_text,
        PublicationType="; ".join(pub_types),
        Keywords="; ".join(sorted(set(keywords))),
        StudyDesign=infer_study_design(" ".join(pub_types), title, abstract_text),
        Sport=infer_sport(title + " " + abstract_text),
        OA=False,
        PDF_URL="",
        Source="",
    )


def fetch_details(limiter: RateLimiter, pmids: list[str], email: str | None) -> list[PaperRecord]:
    records = []
    for ids in chunked(pmids):
        params: dict[str, Any] = {"db": "pubmed", "retmode": "xml", "id": ",".join(ids)}
        if email:
            params["email"] = email
        body, _ = safe_request(limiter, f"{NCBI_BASE}/efetch.fcgi", params=params)
        root = ET.fromstring(body)
        records.extend(parse_article(a) for a in root.findall("PubmedArticle"))
    return records


def pick_oa_pdf(limiter: RateLimiter, r: PaperRecord, email: str | None) -> tuple[bool, str, str]:
    if r.PMCID:
        pmcid = r.PMCID if r.PMCID.startswith("PMC") else f"PMC{r.PMCID}"
        return True, f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf", "PMC"
    if r.PMID:
        try:
            b, _ = safe_request(limiter, EUROPE_PMC_SEARCH, params={"query": f"EXT_ID:{r.PMID} SRC:MED", "format": "json", "pageSize": 1})
            result = json.loads(b.decode("utf-8")).get("resultList", {}).get("result", [])
            if result and result[0].get("isOpenAccess") == "Y":
                for u in result[0].get("fullTextUrlList", {}).get("fullTextUrl", []):
                    if u.get("documentStyle", "").lower() == "pdf":
                        return True, u.get("url", ""), "EuropePMC"
        except Exception:
            pass
    if r.DOI and email:
        try:
            b, _ = safe_request(limiter, f"{UNPAYWALL}/{r.DOI}", params={"email": email})
            data = json.loads(b.decode("utf-8"))
            if data.get("is_oa") and (data.get("best_oa_location") or {}).get("url_for_pdf"):
                return True, data["best_oa_location"]["url_for_pdf"], "Unpaywall"
        except Exception:
            pass
    return False, "", ""


def sanitize(s: str, max_len: int = 40) -> str:
    return (re.sub(r"[^\w\-.]+", "_", (s or "").strip())[:max_len].strip("_")) or "NA"


def make_pdf_filename(r: PaperRecord) -> str:
    first = r.Authors.split(";")[0].split(" ")[0] if r.Authors else "NA"
    short_title = "_".join(r.Title.split()[:6])
    ident = r.PMID or r.DOI or "NA"
    return f"{sanitize(r.Year or 'NA',4)}_{sanitize(first)}_{sanitize(r.Journal,25)}_{sanitize(short_title,35)}_{sanitize(ident,30)}.pdf"


def download_pdf(limiter: RateLimiter, url: str, out_path: Path) -> bool:
    if out_path.exists():
        return True
    try:
        body, headers = safe_request(limiter, url, timeout=45)
        ctype = headers.get("Content-Type", "").lower()
        if "pdf" not in ctype and not body.startswith(b"%PDF"):
            return False
        out_path.write_bytes(body)
        return True
    except Exception:
        return False


def write_bibtex(records: list[PaperRecord], path: Path) -> None:
    entries = []
    for r in records:
        key = sanitize((r.Authors.split(";")[0] if r.Authors else "unknown") + (r.Year or ""), 32)
        entries.append("\n".join([f"@article{{{key},", f"  title = {{{r.Title}}},", f"  author = {{{r.Authors}}},", f"  journal = {{{r.Journal}}},", f"  year = {{{r.Year}}},", f"  doi = {{{r.DOI}}},", f"  pmid = {{{r.PMID}}},", "}"]))
    path.write_text("\n\n".join(entries), encoding="utf-8")


def write_ris(records: list[PaperRecord], path: Path) -> None:
    blocks = []
    for r in records:
        b = ["TY  - JOUR", f"TI  - {r.Title}", f"JO  - {r.Journal}", f"PY  - {r.Year}", f"DO  - {r.DOI}", f"ID  - {r.PMID}"]
        b.extend([f"AU  - {a.strip()}" for a in r.Authors.split(";") if a.strip()])
        b.append("ER  -")
        blocks.append("\n".join(b))
    path.write_text("\n\n".join(blocks), encoding="utf-8")


def render_summary_md(r: PaperRecord) -> str:
    links = [f"- PubMed: https://pubmed.ncbi.nlm.nih.gov/{r.PMID}/" if r.PMID else "", f"- DOI: https://doi.org/{r.DOI}" if r.DOI else "", f"- OA PDF: {r.PDF_URL}" if r.PDF_URL else ""]
    links = [x for x in links if x] or ["- N/A"]
    return "\n".join([f"# {r.Title}", "", "## 要点", f"- StudyDesign: {r.StudyDesign}", f"- PublicationType: {r.PublicationType or 'N/A'}", f"- Sportタグ: {r.Sport or 'N/A'}", "", "## 方法", "- 抄録とPublicationTypeから推定（自動生成）", "", "## 主要結果", f"- Abstract: {r.Abstract or 'N/A'}", "", "## 臨床的示唆", "- 肘・上腕骨小頭OCDの診療意思決定を補助", "", "## 限界", "- 自動抽出のため、最終判断は原著確認が必要", "", "## リンク", *links, ""])


def write_outputs(records: list[PaperRecord], outdir: Path) -> None:
    (outdir / "data").mkdir(parents=True, exist_ok=True)
    (outdir / "bib").mkdir(parents=True, exist_ok=True)
    (outdir / "summaries").mkdir(parents=True, exist_ok=True)

    fields = list(PaperRecord.__annotations__.keys())
    with (outdir / "data" / "papers.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow(asdict(r))
    with (outdir / "data" / "papers.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    write_bibtex(records, outdir / "bib" / "papers.bib")
    write_ris(records, outdir / "bib" / "papers.ris")

    for r in records:
        sid = r.PMID or r.DOI or sanitize(r.Title, 20)
        (outdir / "summaries" / f"{sanitize(sid,40)}.md").write_text(render_summary_md(r), encoding="utf-8")


def load_checkpoint(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"processed_pmids": [], "stats": {}}


def save_checkpoint(path: Path, processed_pmids: set[str], stats: dict[str, int]) -> None:
    path.write_text(json.dumps({"processed_pmids": sorted(processed_pmids), "stats": stats}, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch elbow/capitellar OCD papers from PubMed")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--outdir", default=".")
    p.add_argument("--max", dest="max_results", type=int, default=None)
    p.add_argument("--since-year", type=int, default=None)
    p.add_argument("--until-year", type=int, default=None)
    p.add_argument("--query-override", default=None)
    p.add_argument("--download-pdf", default=None)
    return p.parse_args()


def str_to_bool(v: str | None, default: bool) -> bool:
    return default if v is None else v.lower() in {"1", "true", "yes", "y"}


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    config = load_config(Path(args.config))
    for d in ["data", "pdf", "bib", "summaries", "logs"]:
        (outdir / d).mkdir(parents=True, exist_ok=True)
    logger = setup_logger(outdir / "logs" / "fetch.log")

    max_results = args.max_results or config["search"].get("max_results", 200)
    since_year = args.since_year or config["search"].get("since_year")
    until_year = args.until_year or config["search"].get("until_year")
    query = build_query(config, args)
    download_pdf_enabled = str_to_bool(args.download_pdf, config["download"].get("download_pdf", True))

    limiter = RateLimiter(config.get("rate_limit", {}).get("requests_per_sec", 3))
    email = os.getenv("NCBI_EMAIL")
    ckpt_path = outdir / "logs" / "checkpoint.json"
    ckpt = load_checkpoint(ckpt_path)
    processed_pmids = set(ckpt.get("processed_pmids", []))

    logger.info("query: %s", query)
    pmids = search_pubmed(limiter, query, max_results, since_year, until_year, email)
    target_pmids = [p for p in pmids if p not in processed_pmids]
    logger.info("found=%s new=%s skipped=%s", len(pmids), len(target_pmids), len(pmids) - len(target_pmids))

    records = fetch_details(limiter, target_pmids, email)
    all_records: list[PaperRecord] = []
    existing = outdir / "data" / "papers.jsonl"
    if existing.exists():
        all_records.extend(PaperRecord(**json.loads(line)) for line in existing.read_text(encoding="utf-8").splitlines() if line.strip())

    stats = {"total": 0, "oa_true": 0, "pdf_saved": 0, "pdf_failed": 0}
    for r in records:
        stats["total"] += 1
        oa, pdf_url, source = pick_oa_pdf(limiter, r, email)
        r.OA, r.PDF_URL, r.Source = oa, pdf_url, source
        if oa:
            stats["oa_true"] += 1
        if download_pdf_enabled and oa and pdf_url:
            if download_pdf(limiter, pdf_url, outdir / "pdf" / make_pdf_filename(r)):
                stats["pdf_saved"] += 1
            else:
                stats["pdf_failed"] += 1
        all_records.append(r)
        processed_pmids.add(r.PMID)
        save_checkpoint(ckpt_path, processed_pmids, stats)

    unique = {(r.PMID or r.DOI or r.Title): r for r in all_records}
    deduped = sorted(unique.values(), key=lambda x: (x.Year or "", x.PMID), reverse=True)
    write_outputs(deduped, outdir)
    logger.info("done total=%s oa=%s pdf_saved=%s pdf_failed=%s", stats["total"], stats["oa_true"], stats["pdf_saved"], stats["pdf_failed"])


if __name__ == "__main__":
    main()
