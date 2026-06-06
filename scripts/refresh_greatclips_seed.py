"""
scripts/refresh_greatclips_seed.py
Runs the Great Clips coupon scan locally (home IP, not blocked),
then rewrites the _SEED_COUPONS and _SEED_DATE constants in
scanners/deals_greatclips.py and commits + pushes to GitHub.

Run: python scripts/refresh_greatclips_seed.py
"""

import re
import sys
import os
import subprocess
from datetime import datetime

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TARGET_CITIES   = ["Plano", "McKinney", "Frisco"]
PAGE_FILE       = os.path.join(ROOT, "scanners", "deals_greatclips.py")


def run_scan() -> list[dict]:
    """Import and run the live scanner directly."""
    from scanners.deals_greatclips import (
        _scan_primary, _scan_secondary, _SEED_COUPONS
    )
    import warnings
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    print("Scanning primary source…")
    results, _ = _scan_primary(TARGET_CITIES)

    if not results:
        print("Primary blocked/empty — trying secondary…")
        results, _ = _scan_secondary(TARGET_CITIES)

    if results:
        print(f"  Found {len(results)} live coupon(s).")
    else:
        print("  No live results — seed unchanged.")

    return results


def build_seed_literal(coupons: list[dict]) -> str:
    """Render the _SEED_COUPONS list as Python source."""
    today = datetime.now().strftime("%b %d, %Y")
    lines = [f'_SEED_DATE = "{today}"\n']
    lines.append("_SEED_COUPONS: list[dict] = [\n")
    for c in coupons:
        lines.append("    {\n")
        lines.append(f'        "city": {c["city"]!r}, "location": {c["location"]!r},\n')
        lines.append(f'        "address": {c["address"]!r},\n')
        lines.append(f'        "amount": {c["amount"]}, "coupon_type": {c["coupon_type"]!r}, "sort_key": {c["sort_key"]},\n')
        lines.append(f'        "denomination": {c["denomination"]!r}, "denomination_label": {c.get("denomination_label","")!r},\n')
        lines.append(f'        "coupon_url": {c["coupon_url"]!r},\n')
        lines.append("    },\n")
    lines.append("]\n")
    return "".join(lines)


def update_seed_in_file(new_literal: str):
    """Replace the _SEED_DATE + _SEED_COUPONS block in deals_greatclips.py."""
    with open(PAGE_FILE, "r", encoding="utf-8") as f:
        src = f.read()

    pattern = re.compile(
        r'_SEED_DATE\s*=\s*"[^"]*"\n_SEED_COUPONS.*?^\]\n',
        re.DOTALL | re.MULTILINE,
    )
    if not pattern.search(src):
        print("ERROR: could not locate _SEED_DATE / _SEED_COUPONS block in file.")
        sys.exit(1)

    new_src = pattern.sub(new_literal, src, count=1)
    with open(PAGE_FILE, "w", encoding="utf-8") as f:
        f.write(new_src)
    print(f"Updated {PAGE_FILE}")


def git_commit_push():
    os.chdir(ROOT)
    date_str = datetime.now().strftime("%Y-%m-%d")
    subprocess.run(["git", "add", "scanners/deals_greatclips.py"], check=True)

    # Check if there's actually anything staged
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True
    )
    if result.returncode == 0:
        print("No changes to commit — seed data unchanged.")
        return

    msg = (
        f"chore: refresh Great Clips seed coupons {date_str}\n\n"
        "Automated weekly update via scripts/refresh_greatclips_seed.py\n\n"
        "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    )
    subprocess.run(["git", "commit", "-m", msg], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)
    print("Committed and pushed.")


def main():
    coupons = run_scan()
    if not coupons:
        print("Scan returned nothing — skipping file update.")
        sys.exit(0)

    literal = build_seed_literal(coupons)
    update_seed_in_file(literal)
    git_commit_push()
    print("Done.")


if __name__ == "__main__":
    main()
