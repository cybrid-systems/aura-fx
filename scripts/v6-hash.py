#!/usr/bin/env python3
"""Write sha256 of processed v6 files (not the raw Dukascopy cache).

usage: v6-hash.py [OUT=data/v6/SHA256SUMS]
"""
import hashlib, os, sys

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "data/v6/SHA256SUMS"
    root = "data/v6"
    files = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith("-h1.csv") or n == "SHA256SUMS":
                continue
            files.append(os.path.join(dirpath, n))
    files.sort()
    with open(out, "w") as fh:
        for p in files:
            fh.write(f"{sha(p)}  {p}\n")
    print(f"HASH_OK {out} files={len(files)}")

if __name__ == "__main__":
    main()
