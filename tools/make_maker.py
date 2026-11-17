#!/usr/bin/env python3
"""把 skill 的 template.html 與範例 JSON 嵌進 tools/maker.src.html，產生 repo 根目錄的 maker.html（線上製作頁；index.html 是安裝教學首頁）。
修改 six-w-writing/assets/template.html 之後要重新執行：python tools/make_maker.py"""
import json
from pathlib import Path
R = Path(__file__).resolve().parent.parent
tpl = (R / "six-w-writing/assets/template.html").read_text(encoding="utf-8").replace("</script>", "<\\/script>")
ex = json.dumps(json.loads((R / "six-w-writing/references/example-lesson.json").read_text(encoding="utf-8")), ensure_ascii=False).replace("</", "<\\/")
src = (R / "tools/maker.src.html").read_text(encoding="utf-8")
out = src.replace("/*__TEMPLATE__*/", tpl, 1).replace("/*__EXAMPLE__*/", ex, 1)
(R / "maker.html").write_text(out, encoding="utf-8")
print("maker.html 已更新")
