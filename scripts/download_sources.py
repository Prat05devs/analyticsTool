"""Download official files listed in data_sources.yaml into data/raw/<source_id>/<vintage>/
and append a row per file to data/source_register.csv.

Usage:  python scripts/download_sources.py            # RBI handbook tables
        python scripts/download_sources.py --all      # every *_pdf / xlsx URL in the yaml
        python scripts/download_sources.py --register-manual   # hash files you dropped into data/raw by hand

If a server returns HTML (bot check) instead of the file, the script reports it and moves on.
Do NOT try to bypass the check: download that file in a browser into the printed folder.

RBI tables: when the XLSX on rbidocs.rbi.org.in is blocked, the script saves the same table's official
HTML page (www.rbi.org.in/scripts/PublicationsView.aspx?id=...), which is listed in data_sources.yaml
as the `html` link. That is a published format of the same table, not a workaround of the check.
The XLSX still goes on the manual-download list; etl/ingest_rbi_hsis.py prefers XLSX when both exist.

Re-running is safe: a (dataset_id, sha256) pair already in the register is not appended again.
"""
import argparse, csv, datetime as dt, hashlib, pathlib, sys
import requests, yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
REG = ROOT / "data" / "source_register.csv"
FIELDS = ["dataset_id", "publisher", "url", "local_path", "sha256", "acquisition_date",
          "release_date", "observation_period", "table", "unit", "price_base", "caveat", "status"]
HEADERS = {"User-Agent": "india-expansion-intel research script (personal, non-commercial)"}
BLOCKED = []


def registered():
    if not REG.exists():
        return set()
    with REG.open() as f:
        return {(r["dataset_id"], r["sha256"]) for r in csv.DictReader(f)}


def register(row):
    new = not REG.exists()
    if (row["dataset_id"], row["sha256"]) in registered():
        return False
    with REG.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})
    return True


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r


def save(dataset_id, url, folder, meta, name=None, expect_html=False, status="downloaded"):
    """Return True if a file was saved (or was already present)."""
    folder.mkdir(parents=True, exist_ok=True)
    name = name or url.split("/")[-1].split("?")[0] or "download"
    dest = folder / name
    if dest.exists():
        print(f"  have {dataset_id} ({dest.name})")
        return True
    try:
        r = fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED {dataset_id}: {e}")
        return False
    ctype = r.headers.get("content-type", "")
    if "text/html" in ctype and not expect_html and not url.lower().endswith((".htm", ".html", ".aspx")):
        print(f"  BLOCKED (got HTML, likely a browser check) {dataset_id}")
        BLOCKED.append((dataset_id, url, folder))
        return False
    if expect_html and b"<table" not in r.content.lower():
        print(f"  BLOCKED (HTML page without a data table) {dataset_id}")
        BLOCKED.append((dataset_id, url, folder))
        return False
    dest.write_bytes(r.content)
    register({"dataset_id": dataset_id, "url": url, "local_path": str(dest.relative_to(ROOT)),
              "sha256": hashlib.sha256(r.content).hexdigest(),
              "acquisition_date": dt.date.today().isoformat(), "status": status, **meta})
    print(f"  ok {dataset_id} ({len(r.content)//1024} KB)")
    return True


def rbi_tables(src):
    rbi = src["rbi_handbook_states_2024_25"]
    vintage = str(rbi["release_date"])
    folder = ROOT / "data/raw/rbi_hsis" / vintage
    for tid, links in rbi["tables"].items():
        meta = {"publisher": rbi["publisher"], "release_date": vintage, "table": tid,
                "price_base": rbi["price_base"], "unit": "see table header", "caveat": links.get("title", "")}
        url = links.get("xlsx", "")
        if url.startswith("http") and save(f"rbi_hsis_2024_25_{tid}", url, folder, meta, name=f"{tid}.xlsx"):
            continue
        html = links.get("html", "")
        if html.startswith("http"):
            save(f"rbi_hsis_2024_25_{tid}_html", html, folder, meta, name=f"{tid}.html", expect_html=True,
                 status="downloaded (official HTML table; XLSX blocked by browser check)")


def register_manual():
    """Hash files that were downloaded by hand and are not yet in the register."""
    have = {r for _, r in registered()}
    for p in sorted((ROOT / "data/raw").rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest in have:
            continue
        rel = p.relative_to(ROOT / "data/raw")
        register({"dataset_id": f"{rel.parts[0]}_{p.stem}", "local_path": str(p.relative_to(ROOT)), "sha256": digest,
                  "acquisition_date": dt.date.today().isoformat(), "release_date": rel.parts[1] if len(rel.parts) > 2 else "",
                  "status": "manual download"})
        print(f"  registered {p.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--register-manual", action="store_true")
    args = ap.parse_args()
    if args.register_manual:
        register_manual()
        return 0
    src = yaml.safe_load((ROOT / "data_sources.yaml").read_text())
    rbi_tables(src)

    if args.all:
        for sid, s in src.items():
            if sid == "rbi_handbook_states_2024_25" or not isinstance(s, dict):
                continue
            for k, v in s.items():
                if isinstance(v, dict):  # nested {period, pdf} blocks
                    v = v.get("pdf", "")
                    k = f"{k}_pdf"
                if isinstance(v, str) and v.startswith("http") and k.endswith(("_pdf", "_xlsx")):
                    save(f"{sid}_{k}", v, ROOT / "data/raw" / sid / dt.date.today().isoformat(),
                         {"publisher": s.get("publisher", ""), "caveat": s.get("caveat", "")})

    if BLOCKED:
        print(f"\n{len(BLOCKED)} file(s) need a manual browser download:")
        for did, url, folder in BLOCKED:
            print(f"  {did}\n    {url}\n    -> {folder.relative_to(ROOT)}/")
        print("Then run: python scripts/download_sources.py --register-manual")
    return 0


if __name__ == "__main__":
    sys.exit(main())
