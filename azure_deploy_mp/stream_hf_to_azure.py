#!/usr/bin/env python3
"""
Stream files from a Hugging Face dataset repo directly into Azure Blob Storage
without keeping the whole dataset locally.

Usage (example):
  pip install -r requirements-stream.txt
  python azure_deploy_mp/stream_hf_to_azure.py \
    --hf-repo RenzKa/simlingo \
    --storage-account daijpepdde0b7efc169e98db \
    --container data-ai-vla \
    --dest-prefix datasets/processing_incoming/simlingo_stream_test \
    --workers 8

Notes:
- Requires network bandwidth; the script streams each file from Hugging Face
  and uploads directly to Azure via the SDK, so no full local checkout is kept.
- For private repos provide `--hf-token <TOKEN>`.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import requests
from huggingface_hub import HfApi
from azure.storage.blob import ContainerClient

LOG = logging.getLogger("stream_hf_to_azure")


def list_files(hf_repo: str, hf_token: str | None) -> List[str]:
    api = HfApi()
    try:
        files = api.list_repo_files(repo_id=hf_repo, repo_type="dataset")
        return files
    except Exception:
        # fallback to generic listing (some older hf versions)
        return api.list_repo_files(repo_id=hf_repo)


def build_raw_url(hf_repo: str, path: str, revision: str | None = None) -> str:
    rev = revision or "main"
    # Raw file URL for datasets: /datasets/<repo>/resolve/<revision>/<path>
    return f"https://huggingface.co/datasets/{hf_repo}/resolve/{rev}/{path}"


def upload_file(session: requests.Session, container: ContainerClient, hf_repo: str, path: str,
                dest_prefix: str, hf_token: str | None, overwrite: bool, max_retries: int = 3) -> None:
    url = build_raw_url(hf_repo, path)
    headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}
    blob_path = f"{dest_prefix.rstrip('/')}/{path}"
    blob_client = container.get_blob_client(blob_path)

    for attempt in range(1, max_retries + 1):
        try:
            with session.get(url, headers=headers, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                # Upload the streaming response raw to Azure Blob (SDK will stream chunks)
                blob_client.upload_blob(resp.raw, overwrite=overwrite)
            LOG.debug("Uploaded %s -> %s", path, blob_path)
            return
        except Exception as exc:
            LOG.warning("Attempt %d failed for %s: %s", attempt, path, exc)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                raise


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hf-repo", required=True, help="Hugging Face dataset repo (owner/repo)")
    parser.add_argument("--hf-token", default=None, help="Hugging Face token for private repos")
    parser.add_argument("--revision", default=None, help="Revision/commit to use (default main)")
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--dest-prefix", required=True, help="Destination prefix inside the container")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-ext", default="", help="Comma-separated extensions to skip (e.g. .mp4,.mov)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_repo = args.hf_repo
    hf_token = args.hf_token
    revision = args.revision
    storage_account = args.storage_account
    container_name = args.container
    dest_prefix = args.dest_prefix
    workers = args.workers
    overwrite = args.overwrite
    skip_exts = {e.strip().lower() for e in args.skip_ext.split(",") if e.strip()} if args.skip_ext else set()

    # build container client using connection via environment or default Azure auth
    blob_url = f"https://{storage_account}.blob.core.windows.net/{container_name}"
    container = ContainerClient(account_url=f"https://{storage_account}.blob.core.windows.net", container_name=container_name)

    LOG.info("Listing files in %s", hf_repo)
    files = list_files(hf_repo, hf_token)
    LOG.info("Found %d files", len(files))

    # Filter to files only (huggingface includes paths to files; we assume all returned are files)
    to_upload = [p for p in files if not p.endswith("/") and os.path.splitext(p)[1].lower() not in skip_exts]
    LOG.info("Uploading %d files (skip_exts=%s)", len(to_upload), skip_exts)

    session = requests.Session()
    if hf_token:
        session.headers.update({"Authorization": f"Bearer {hf_token}"})

    errors = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(upload_file, session, container, hf_repo, path, dest_prefix, hf_token, overwrite): path for path in to_upload}
        for fut in as_completed(futures):
            path = futures[fut]
            try:
                fut.result()
            except Exception as exc:
                LOG.error("Failed to upload %s: %s", path, exc)
                errors += 1

    elapsed = time.time() - start
    LOG.info("Done. Uploaded %d/%d files with %d errors in %.1fs", len(to_upload) - errors, len(to_upload), errors, elapsed)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
