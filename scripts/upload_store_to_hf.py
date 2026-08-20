"""
Upload the Oxigraph store to a Hugging Face dataset repo.

Run once locally after `make ingest`:

    python scripts/upload_store_to_hf.py --repo YOUR_HF_USERNAME/water-contamination-kg

Requires HF_TOKEN env var (or pass --token).
The repo is created automatically if it does not exist.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
STORE_PATH = ROOT / "data" / "ontology" / "oxigraph_store"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="HF repo ID, e.g. username/water-contamination-kg")
    parser.add_argument("--token", default=os.getenv("HF_TOKEN"), help="HF write token")
    args = parser.parse_args()

    if not STORE_PATH.exists():
        raise SystemExit(f"Oxigraph store not found at {STORE_PATH}. Run `make ingest` first.")

    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise SystemExit("Install huggingface_hub: pip install huggingface_hub")

    api = HfApi(token=args.token)

    print(f"Creating/verifying dataset repo: {args.repo}")
    api.create_repo(repo_id=args.repo, repo_type="dataset", exist_ok=True, private=False)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "oxigraph_store.zip"
        print(f"Zipping {STORE_PATH} …")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in STORE_PATH.rglob("*"):
                zf.write(f, Path("oxigraph_store") / f.relative_to(STORE_PATH))
        size_mb = zip_path.stat().st_size / 1_048_576
        print(f"Compressed size: {size_mb:.1f} MB")

        print("Uploading to Hugging Face …")
        api.upload_file(
            path_or_fileobj=str(zip_path),
            path_in_repo="oxigraph_store.zip",
            repo_id=args.repo,
            repo_type="dataset",
            commit_message="Upload Oxigraph store",
        )

    print(f"\nDone. Set HF_REPO_ID={args.repo} in Streamlit secrets.")


if __name__ == "__main__":
    main()
