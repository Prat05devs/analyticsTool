"""District- and city-level internet speed from Ookla Open Data (Speedtest tiles, ~610 m).

Run on your laptop (needs internet access to AWS S3 and GitHub):
    pip install duckdb geopandas pyarrow shapely requests
    python scripts/ookla_district_speeds.py --year 2026 --quarter 2

What it does
1. Reads Ookla's quarterly fixed + mobile performance tiles (Parquet on the public S3 bucket
   s3://ookla-open-data, no AWS account needed) for India's bounding box only.
2. Spatially joins tile centroids to district boundaries (geoBoundaries gbOpen IND ADM2).
3. Writes test-weighted average download / upload (Mbps), latency (ms), tests and devices per district.
4. Writes a city table for the major cities in the 7 pilot states (city = its district).

LICENCE: Ookla open data is CC BY-NC-SA 4.0 (non-commercial). Fine for research or a demo.
For a commercial product you need Ookla's permission or a licence, so flag this in the app's methods page.
Required attribution: "Speedtest by Ookla Global Fixed and Mobile Network Performance Maps.
Based on analysis by Ookla of Speedtest Intelligence data for <quarter>. Provided by Ookla and accessed <date>."

Caveats to show in the app: speed tests are user-initiated (urban and enthusiast bias); tiles with few tests
are noisy (min_tests filter); fixed and mobile are separate; this is measured speed, not coverage.
"""
import argparse, datetime as dt, pathlib
import duckdb, geopandas as gpd, pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "curated" / "internet_speed"
ADM2_URL = ("https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/IND/ADM2/"
            "geoBoundaries-IND-ADM2.geojson")
INDIA_BBOX = (68.0, 6.5, 97.5, 37.5)  # lon_min, lat_min, lon_max, lat_max
CITIES = {  # pilot-state major cities -> (lon, lat) used to pick the district polygon
    "Mumbai": (72.8777, 19.0760), "Pune": (73.8567, 18.5204), "Nagpur": (79.0882, 21.1458),
    "Nashik": (73.7898, 19.9975), "Ahmedabad": (72.5714, 23.0225), "Surat": (72.8311, 21.1702),
    "Vadodara": (73.1812, 22.3072), "Rajkot": (70.8022, 22.3039), "Bengaluru": (77.5946, 12.9716),
    "Mysuru": (76.6394, 12.2958), "Hubballi-Dharwad": (75.1240, 15.3647), "Mangaluru": (74.8560, 12.9141),
    "Chennai": (80.2707, 13.0827), "Coimbatore": (76.9558, 11.0168), "Madurai": (78.1198, 9.9252),
    "Tiruchirappalli": (78.7047, 10.7905), "Hyderabad": (78.4867, 17.3850), "Warangal": (79.5941, 17.9689),
    "Lucknow": (80.9462, 26.8467), "Noida": (77.3910, 28.5355), "Kanpur": (80.3319, 26.4499),
    "Ghaziabad": (77.4538, 28.6692), "Agra": (78.0081, 27.1767), "Varanasi": (82.9739, 25.3176),
    "Jaipur": (75.7873, 26.9124), "Jodhpur": (73.0243, 26.2389), "Udaipur": (73.7125, 24.5854),
    "Kota": (75.8648, 25.2138),
}


S3_HTTP = "https://ookla-open-data.s3.amazonaws.com"
RAW = ROOT / "data" / "raw" / "ookla_open_data"


def raw_tiles(kind, year, quarter):
    """Download the quarterly tile file once into data/raw (immutable) and register its sha256."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import download_sources as d
    month = {1: "01", 2: "04", 3: "07", 4: "10"}[quarter]
    key = f"parquet/performance/type={kind}/year={year}/quarter={quarter}/{year}-{month}-01_performance_{kind}_tiles.parquet"
    folder = RAW / f"{year}Q{quarter}"
    dest = folder / key.split("/")[-1]
    if not dest.exists():
        import hashlib, requests, time
        folder.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        for attempt in range(8):  # resumable: large files time out on slow links
            have = part.stat().st_size if part.exists() else 0
            try:
                with requests.get(f"{S3_HTTP}/{key}", stream=True, timeout=120,
                                  headers={"Range": f"bytes={have}-"} if have else {}) as r:
                    if r.status_code == 416:
                        break
                    r.raise_for_status()
                    with open(part, "ab" if have and r.status_code == 206 else "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                break
            except requests.RequestException as e:
                print(f"  retry {attempt + 1}: {e}")
                time.sleep(5)
        size = int(requests.head(f"{S3_HTTP}/{key}", timeout=60).headers["content-length"])
        if part.stat().st_size != size:
            raise IOError(f"incomplete download {part} ({part.stat().st_size} of {size} bytes)")
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        part.rename(dest)
        d.register({"dataset_id": f"ookla_{kind}_{year}Q{quarter}", "publisher": "Ookla Open Data",
                    "url": f"s3://ookla-open-data/{key}", "local_path": str(dest.relative_to(ROOT)),
                    "sha256": h.hexdigest(), "acquisition_date": dt.date.today().isoformat(),
                    "observation_period": f"{year}Q{quarter}", "unit": "kbps / ms",
                    "caveat": "CC BY-NC-SA 4.0 (non-commercial); user-initiated tests", "status": "downloaded"})
    return dest


def load_tiles(con, kind, year, quarter, min_tests):
    url = str(raw_tiles(kind, year, quarter))
    lon0, lat0, lon1, lat1 = INDIA_BBOX
    q = f"""
      SELECT quadkey, avg_d_kbps, avg_u_kbps, avg_lat_ms, tests, devices,
             ST_X(ST_Centroid(ST_GeomFromText(tile))) AS lon,
             ST_Y(ST_Centroid(ST_GeomFromText(tile))) AS lat
      FROM read_parquet('{url}')
      WHERE tests >= {min_tests}
    """
    df = con.execute(q).df()
    df = df[(df.lon.between(lon0, lon1)) & (df.lat.between(lat0, lat1))]
    df["kind"] = kind
    print(f"{kind}: {len(df):,} tiles in India bbox from {url}")
    return df


def raw_boundaries():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import download_sources as d
    folder = ROOT / "data" / "raw" / "geoboundaries_ind_adm2" / dt.date.today().isoformat()
    have = list((ROOT / "data" / "raw" / "geoboundaries_ind_adm2").glob("*/geoBoundaries-IND-ADM2.geojson"))
    if have:
        return have[0]
    d.save("geoboundaries_ind_adm2", ADM2_URL, folder, {"publisher": "geoBoundaries (William & Mary geoLab)",
                                                       "caveat": "gbOpen ADM2, CC BY 4.0; district names may differ from Census"},
           name="geoBoundaries-IND-ADM2.geojson")
    return folder / "geoBoundaries-IND-ADM2.geojson"


def aggregate(tiles, districts):
    g = gpd.GeoDataFrame(tiles, geometry=gpd.points_from_xy(tiles.lon, tiles.lat), crs="EPSG:4326")
    j = gpd.sjoin(g, districts[["shapeName", "shapeID", "geometry"]], predicate="within", how="inner")
    j["w_d"] = j.avg_d_kbps * j.tests
    j["w_u"] = j.avg_u_kbps * j.tests
    j["w_l"] = j.avg_lat_ms * j.tests
    a = j.groupby(["shapeID", "shapeName", "kind"]).agg(
        tests=("tests", "sum"), devices=("devices", "sum"), tiles=("quadkey", "count"),
        w_d=("w_d", "sum"), w_u=("w_u", "sum"), w_l=("w_l", "sum")).reset_index()
    a["avg_download_mbps"] = a.w_d / a.tests / 1000
    a["avg_upload_mbps"] = a.w_u / a.tests / 1000
    a["avg_latency_ms"] = a.w_l / a.tests
    return a.drop(columns=["w_d", "w_u", "w_l"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--quarter", type=int, default=2, help="latest published quarter; check the S3 listing")
    ap.add_argument("--min-tests", type=int, default=3)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    for ext in ("spatial",):
        con.execute(f"INSTALL {ext}; LOAD {ext};")

    tiles = pd.concat([load_tiles(con, k, a.year, a.quarter, a.min_tests) for k in ("fixed", "mobile")])
    districts = gpd.read_file(raw_boundaries()).to_crs("EPSG:4326")
    agg = aggregate(tiles, districts)
    tag = f"{a.year}Q{a.quarter}"
    agg["period"] = tag
    agg["source"] = "Ookla Open Data (CC BY-NC-SA 4.0)"
    agg.to_csv(OUT / f"district_speed_{tag}.csv", index=False)

    pts = gpd.GeoDataFrame({"city": list(CITIES)},
                           geometry=gpd.points_from_xy(*zip(*CITIES.values())), crs="EPSG:4326")
    city_d = gpd.sjoin(pts, districts[["shapeID", "shapeName", "geometry"]], predicate="within")
    city = city_d[["city", "shapeID", "shapeName"]].merge(agg, on=["shapeID", "shapeName"], how="left")
    city.to_csv(OUT / f"city_speed_{tag}.csv", index=False)
    print(f"wrote {len(agg)} district rows and {len(city)} city rows to {OUT}  (accessed {dt.date.today()})")


if __name__ == "__main__":
    main()
