"""암호화 키 생성 및 파일 암·복호화 도구.

  python -m scorer.crypto_tool keygen                 # .competition.key 생성 (Actions Secret 에 등록할 값 출력)
  python -m scorer.crypto_tool encrypt participants.csv          # → participants.csv.enc
  python -m scorer.crypto_tool decrypt competitions/x/final_results.csv.enc   # → final_results.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from .common import KEY_FILE, decrypt_bytes, encrypt_bytes, load_key


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("keygen", help="새 키 생성")
    g.add_argument("--force", action="store_true", help="기존 키 파일 덮어쓰기")
    e = sub.add_parser("encrypt", help="파일 암호화")
    e.add_argument("path")
    e.add_argument("--out")
    d = sub.add_parser("decrypt", help="파일 복호화")
    d.add_argument("path")
    d.add_argument("--out")
    sub.add_parser("show", help="현재 키 출력")
    args = ap.parse_args(argv)

    if args.cmd == "keygen":
        if KEY_FILE.exists() and not args.force:
            print(f"이미 {KEY_FILE.name} 가 있습니다. 덮어쓰려면 --force 를 지정하세요.")
            print("주의: 키를 바꾸면 기존 .enc 파일과 저장된 Private 점수를 모두 다시 암호화해야 합니다.")
            return 1
        key = Fernet.generate_key().decode()
        KEY_FILE.write_text(key + "\n", encoding="utf-8")
        print(f"새 키를 {KEY_FILE.name} 에 저장했습니다 (.gitignore 에 포함되어 커밋되지 않습니다).")
        print("아래 값을 GitHub 저장소 Settings → Secrets and variables → Actions → New repository secret 에")
        print("이름 COMPETITION_KEY 로 등록하세요:\n")
        print(key)
        return 0

    if args.cmd == "show":
        print(load_key().decode())
        return 0

    src = Path(args.path)
    if not src.exists():
        print(f"파일이 없습니다: {src}")
        return 1
    if args.cmd == "encrypt":
        out = Path(args.out) if args.out else src.with_name(src.name + ".enc")
        out.write_bytes(encrypt_bytes(src.read_bytes()))
        print(f"암호화 완료: {out}")
        return 0
    out = Path(args.out) if args.out else (src.with_suffix("") if src.suffix == ".enc" else src.with_name(src.name + ".dec"))
    out.write_bytes(decrypt_bytes(src.read_bytes()))
    print(f"복호화 완료: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
