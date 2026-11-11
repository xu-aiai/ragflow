"""管线入口：python pipeline.py --input 手册A.docx --doc A --variant 国内干桥 --version 202608 --out dist/"""
from xc975_pipeline.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
