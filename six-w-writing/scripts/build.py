#!/usr/bin/env python3
"""六何法分層寫作小幫手：把 lesson.json 變成互動網頁、學習單（HTML／PDF／Word）與教師版。

用法：
    python build.py lesson.json                 # 全部產出到 lesson.json 所在資料夾
    python build.py lesson.json -o 輸出資料夾
    python build.py lesson.json --no-pdf --no-docx
    python build.py lesson.json --check         # 只檢查 JSON，不產生檔案

產出：
    <題目>_互動網頁.html          學生一層一層寫（含全部版本，開啟時選版本）
    <題目>_學習單_<版本>.html/.pdf 每個版本一份，A4 列印
    <題目>_教師版.html/.pdf        全部版本的參考答案＋教學說明
    <題目>_學習單.docx             Word 版（學生版各版本＋教師版），可再編修

需求：
    PDF ：playwright（pip install playwright && playwright install chromium），
          沒有時自動改用電腦上的 Chrome／Edge 無頭列印。
    DOCX：python-docx（pip install python-docx）
"""
import argparse
import base64
import json
import mimetypes
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "template.html"
LV_NAME = {1: "三何起步", 2: "五何擴寫", 3: "六何完整", 4: "事件排序", 5: "情緒加料",
           6: "三段成文", 7: "完整寫作", 8: "遷移寫作與自我檢核"}
LV_SUB = {1: "何人＋何地＋何事", 2: "加入何時＋如何", 3: "加入兩層「為何」", 4: "排列事件＋連接詞",
          5: "動作＋想法＋感受", 6: "開始＋經過＋結果", 7: "整合成一篇文章", 8: "連結自己的經驗"}
DEFAULT_TYPE = {4: "sort", 6: "parts", 7: "essay", 8: "transfer"}
PRESET = {"多": ["choices", "bank", "frame", "cards", "model", "speak"],
          "中": ["bank", "frame", "cards", "speak"], "少": ["speak"]}
SUPS = {"choices": "圈選", "bank": "提示詞／詞庫", "frame": "句型", "cards": "事件卡",
        "model": "範例", "speak": "先說再寫（語音輸入）"}
CHECK4 = [("內容完整", "交代人物、時間、地點與主要事件"), ("組織清楚", "依序敘述，說明原因與方法"),
          ("描寫具體", "加入人物心情、想法或發現"), ("自主修訂", "檢查標點與錯字")]


def ltype(n, lv):
    return lv.get("type") or DEFAULT_TYPE.get(n, "fields")


def sup_list(v):
    return v.get("supports") or PRESET.get(v.get("support", "中"), PRESET["中"])


def safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_") or "六何寫作"


# ---------------------------------------------------------------- 檢查
def check(L, base: Path):
    errs, warns = [], []
    levels = {int(k): v for k, v in (L.get("levels") or {}).items()}
    L["levels"] = {str(k): v for k, v in levels.items()}
    if not L.get("title"):
        errs.append("缺少 title")
    if not levels:
        errs.append("levels 是空的")
    for n in levels:
        if n not in LV_NAME:
            errs.append(f"層次 {n} 不存在（只有 1–8）")
    keys = {}
    for n, lv in levels.items():
        for f in lv.get("fields", []):
            if "key" not in f or "label" not in f:
                errs.append(f"第 {n} 層有欄位缺 key 或 label")
                continue
            keys.setdefault(f["key"], f)
        for p in lv.get("parts", []):
            if "key" not in p:
                errs.append(f"第 {n} 層 parts 缺 key")
    for n, lv in levels.items():
        for k in re.findall(r"\{(\w+)\}", lv.get("frame", "")):
            if k not in keys:
                errs.append(f"第 {n} 層句型用到 {{{k}}}，但沒有這個欄位 key")
        if ltype(n, lv) == "sort" and len(lv.get("events", [])) < 3:
            errs.append(f"第 {n} 層（事件排序）events 至少要 3 個")
        if ltype(n, lv) == "parts" and not lv.get("parts"):
            errs.append(f"第 {n} 層（三段成文）缺 parts")
        if not lv.get("model"):
            if ltype(n, lv) != "parts":
                warns.append(f"第 {n} 層沒有 model（範例／教師版答案）")
        for f in lv.get("fields", []):
            if f.get("choices") and f.get("ans") and not f.get("open") and L.get("mode") != "topic":
                if not any(any(a in c for a in f["ans"]) for c in f["choices"]):
                    warns.append(f"第 {n} 層「{f['label']}」的 choices 裡沒有正確答案")
    vs = L.get("versions") or []
    if not vs:
        warns.append("沒有 versions，將自動做一份「通用版」（全部層次、提示中）")
        L["versions"] = vs = [{"name": "通用版", "levels": sorted(levels), "support": "中"}]
    for v in vs:
        for n in v.get("levels", []):
            if int(n) not in levels:
                errs.append(f"版本「{v.get('name')}」用到第 {n} 層，但 levels 裡沒有")
        for s in v.get("supports", []):
            if s not in SUPS:
                errs.append(f"版本「{v.get('name')}」的學習支持 {s} 不認得（可用：{'、'.join(SUPS)}）")
        if v.get("support") and v["support"] not in PRESET:
            errs.append(f"版本「{v.get('name')}」support 只能是 多／中／少")
    m = L.get("material") or {}
    img = m.get("image")
    if img and not img.startswith("data:"):
        p = (base / img) if not Path(img).is_absolute() else Path(img)
        if p.is_file():
            mt = mimetypes.guess_type(p.name)[0] or "image/png"
            m["image"] = f"data:{mt};base64," + base64.b64encode(p.read_bytes()).decode()
        else:
            warns.append(f"找不到素材圖片 {img}，已略過")
            m.pop("image")
    return errs, warns


# ---------------------------------------------------------------- HTML
def make_html(L, mode, ver=0):
    data = dict(L, __mode=mode, __version=ver)
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__LESSON__*/", js)


# ---------------------------------------------------------------- PDF
def to_pdf(html: Path, out: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return pdf_by_browser(html, out)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(html.resolve().as_uri())
        try:
            pg.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        pg.wait_for_timeout(400)
        pg.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
        b.close()
    print(f"PDF：{out}")
    return True


def pdf_by_browser(html: Path, out: Path) -> bool:
    import glob
    import shutil
    import subprocess
    cands = [shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge")]
    cands += [
        "/opt/pw-browsers/chromium",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    cands += glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome")
    exe = next((c for c in cands if c and Path(c).is_file()), None)
    if not exe:
        print("找不到 playwright 或 Chrome／Edge，略過 PDF。請用瀏覽器開啟學習單 HTML →列印→另存為 PDF。")
        return False
    subprocess.run([exe, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=8000", f"--print-to-pdf={out.resolve()}", html.resolve().as_uri()],
                   check=False, capture_output=True, timeout=180)
    if out.exists():
        print(f"PDF：{out}")
        return True
    print("PDF 產生失敗，請用瀏覽器列印另存 PDF。")
    return False


# ---------------------------------------------------------------- DOCX
def to_docx(L, out: Path, font="標楷體") -> bool:
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Mm, Pt, RGBColor
    except ImportError:
        print("沒有 python-docx，略過 Word。（pip install python-docx）")
        return False
    RED = RGBColor(0xDC, 0x26, 0x26)
    COL = {1: "DBEAFE", 2: "D1FAE5", 3: "EDE9FE", 4: "FCE7F3", 5: "FEF3C7", 6: "CCFBF1", 7: "E0E7FF", 8: "E0F2FE"}
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    for s in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, s, Mm(13))
    st = doc.styles["Normal"]
    st.font.name = font
    st.font.size = Pt(12)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), font)
    st.paragraph_format.space_after = Pt(2)

    def para(target, text="", size=None, bold=False, color=None, align=None):
        p = target.add_paragraph()
        if text:
            r = p.add_run(text)
            r.bold = bold
            if size:
                r.font.size = Pt(size)
            if color:
                r.font.color.rgb = color
        if align == "c":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        return p

    def run(p, text, bold=False, color=None, size=None, u=False):
        r = p.add_run(text)
        r.bold, r.underline = bold, u
        if color:
            r.font.color.rgb = color
        if size:
            r.font.size = Pt(size)
        return r

    def shade(cell, hexcolor):
        tcPr = cell._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear")
        sh.set(qn("w:color"), "auto")
        sh.set(qn("w:fill"), hexcolor)
        tcPr.append(sh)

    def lines(target, n, val=None):
        if val:
            for t in str(val).split("\n"):
                para(target, t, color=RED)
            return
        for _ in range(n):
            para(target, "＿" * 24)

    fields = {}
    for lv in L["levels"].values():
        for f in lv.get("fields", []):
            fields.setdefault(f["key"], f)

    def disp(f):
        if not f:
            return ""
        if f.get("show"):
            return f["show"]
        a = f.get("ans") or []
        for c in f.get("choices") or []:
            if any(k and k in c for k in a):
                return c
        return a[0] if a else ""

    def frame_text(fr, ans):
        def rep(m):
            f = fields.get(m.group(1))
            if ans and disp(f):
                return f"【{disp(f)}】"
            lab = re.sub(r"[（(].*$", "", f["label"]) if f else m.group(1)
            return f"＿＿（{lab}）＿＿"
        return re.sub(r"\{(\w+)\}", rep, fr)

    def shuffled(arr, seed=7):
        a = list(enumerate(arr))
        s = seed
        for i in range(len(a) - 1, 0, -1):
            s = (s * 9301 + 49297) % 233280
            j = int(s / 233280 * (i + 1))
            a[i], a[j] = a[j], a[i]
        if len(a) > 1 and all(x[0] == i for i, x in enumerate(a)):
            a.append(a.pop(0))
        return [x[1] for x in a]

    def level(n, lv, sup, ans):
        t = doc.add_table(rows=1, cols=2)
        t.style = "Table Grid"
        t.autofit = False
        lc, rc = t.rows[0].cells
        lc.width, rc.width = Mm(26), Mm(158)
        t.columns[0].width, t.columns[1].width = Mm(26), Mm(158)
        for i, w in enumerate((Mm(26), Mm(158))):
            t._tbl.tblGrid.findall(qn('w:gridCol'))[i].set(qn('w:w'), str(int(w.twips)))
        shade(lc, COL.get(n, "F1F5F9"))
        lc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        run(lc.paragraphs[0], f"{n}\n{lv.get('name') or LV_NAME[n]}", bold=True)
        para(lc, LV_SUB[n], size=9, align="c")
        rc.paragraphs[0].text = ""
        if lv.get("guide"):
            run(rc.paragraphs[0], lv["guide"])
        tp = ltype(n, lv)
        if tp in ("fields", "transfer"):
            if lv.get("prompt"):
                para(rc, lv["prompt"], bold=True)
            for f in lv.get("fields", []):
                p = rc.add_paragraph()
                run(p, f["label"] + "：", bold=True)
                if "choices" in sup and f.get("choices"):
                    for c in f["choices"]:
                        ok = ans and c == disp(f)
                        run(p, ("☑" if ok else "☐") + c + "　", color=RED if ok else None)
                elif ans and f.get("ans"):
                    run(p, disp(f), color=RED, u=True)
                else:
                    run(p, "＿" * 12)
                if "bank" in sup and f.get("bank"):
                    para(rc, f"{f.get('bankName') or f['label'] + '提示詞'}：" + "、".join(f["bank"]), size=10.5)
            if "bank" in sup and lv.get("bank"):
                para(rc, f"{lv.get('bankName') or '提示詞'}：" + "、".join(lv["bank"]), size=10.5)
            if "frame" in sup and lv.get("frame"):
                para(rc, "句型：" + frame_text(lv["frame"], ans), size=11)
            if lv.get("sentence", True):
                para(rc, lv.get("sentenceLabel") or "寫成完整的句子：")
                lines(rc, lv.get("lines", 2), lv.get("model") if ans else None)
            if tp == "transfer":
                para(rc, "我會檢查：" + "　".join("☐" + c for c in (lv.get("checks") or [x[0] for x in CHECK4])))
        elif tp == "sort":
            ev = lv.get("events", [])
            if "cards" in sup:
                sh = shuffled(ev)
                para(rc, "事件卡：" + "　".join(f"{'ABCDEFGH'[i]} {e}" for i, e in enumerate(sh)), size=10.5)
                if ans:
                    para(rc, " → ".join(f"{'ABCDEFGH'[sh.index(e)]} {e}" for e in ev), color=RED)
                else:
                    para(rc, " → ".join("（　）" for _ in ev))
            else:
                para(rc, " → ".join(ev) if ans else " → ".join("＿＿＿＿" for _ in ev), color=RED if ans else None)
            if "bank" in sup and lv.get("connectors"):
                para(rc, "連接詞：" + "、".join(lv["connectors"]), size=10.5)
            if "frame" in sup and lv.get("frame"):
                para(rc, "句型：" + lv["frame"], size=11)
            para(rc, lv.get("sentenceLabel") or "用連接詞把事件串成一段話：")
            lines(rc, lv.get("lines", 3), lv.get("model") if ans else None)
        elif tp == "parts":
            for p_ in lv.get("parts", []):
                p = rc.add_paragraph()
                run(p, p_["label"], bold=True)
                run(p, f"（{p_.get('hint', '')}）", size=10)
                if "frame" in sup and p_.get("starter"):
                    para(rc, p_["starter"] + "……", size=11)
                lines(rc, p_.get("lines", 2), p_.get("model") if ans else None)
            if "bank" in sup and lv.get("bank"):
                para(rc, f"{lv.get('bankName') or '提示詞'}：" + "、".join(lv["bank"]), size=10.5)
        elif tp == "essay":
            if lv.get("prompt"):
                para(rc, f"題目：{lv['prompt']}" + (f"（約 {lv['words']} 字）" if lv.get("words") else ""), bold=True)
            if "frame" in sup and lv.get("starter"):
                para(rc, "開頭可以這樣寫：" + lv["starter"] + "……", size=11)
            if "bank" in sup and lv.get("bank"):
                para(rc, f"{lv.get('bankName') or '好用詞語'}：" + "、".join(lv["bank"]), size=10.5)
            lines(rc, lv.get("lines", 9), lv.get("model") if ans else None)
        if "model" in sup and lv.get("model") and not ans and tp not in ("essay", "parts"):
            para(rc, "範例：" + lv["model"], size=10, color=RGBColor(0x16, 0x65, 0x34))
        para(doc, "", size=4)

    def sheet(v, ans):
        sup = sup_list(v)
        para(doc, "班級：＿＿＿＿　座號：＿＿＿　姓名：＿＿＿＿＿＿　日期：＿＿月＿＿日", size=11)
        para(doc, f"六何寫作學習單（{v['name']}{'・教師版' if ans else ''}）", size=18, bold=True, align="c")
        para(doc, f"想一想、排一排、說一說，一塊一塊寫出來｜{'題目' if L.get('mode') == 'topic' else '素材'}：{L['title']}", size=11, align="c")
        if L.get("goals"):
            para(doc, "學習目標：" + "　".join(f"{i + 1}. {g}" for i, g in enumerate(L["goals"])), size=11)
        if L.get("core"):
            para(doc, ("寫作重點：" if L.get("mode") == "topic" else "素材核心：") + L["core"], size=11)
        m = L.get("material") or {}
        if m.get("text") and v.get("showMaterial", True):
            para(doc, ("寫作素材：" if L.get("mode") == "topic" else "閱讀素材：") + (m.get("name") or L["title"]), bold=True, size=11)
            for t in m["text"]:
                p = para(doc, t, size=11)
                p.paragraph_format.first_line_indent = Pt(22)
        for n in v["levels"]:
            level(int(n), L["levels"][str(n)], sup, ans)
        para(doc, "學習檢核：" + "　".join("☐" + x[0] for x in CHECK4), size=11)

    vs = L["versions"]
    for i, v in enumerate(vs):
        if i:
            doc.add_page_break()
        sheet(v, False)
    for v in vs:
        doc.add_page_break()
        sheet(v, True)
    doc.add_page_break()
    para(doc, "教學說明（教師用）", size=18, bold=True, align="c")
    t = L.get("teacher") or {}
    para(doc, "版本與學習支持", bold=True)
    for v in vs:
        para(doc, f"・{v['name']}：第 {'、'.join(str(n) for n in v['levels'])} 層；支持：{'、'.join(SUPS[s] for s in sup_list(v))}" + (f"；適用：{v['for']}" if v.get("for") else ""), size=11)
    para(doc, "選層建議（可跨層搭配，不必每次完成全部）", bold=True)
    for s in ("基本句與原因表達：第 1–3 層（圈選、口說與句型提示）", "敘事組織與描寫：第 4–6 層（事件排序、心情與段落）", "完整文章整合：第 7 層＋第 8 層遷移（整合前面所學）"):
        para(doc, "・" + s, size=11)
    if t.get("tips"):
        para(doc, "教學提示", bold=True)
        for x in t["tips"]:
            para(doc, "・" + x, size=11)
    if t.get("adjust"):
        para(doc, "課程調整四面向", bold=True)
        tb = doc.add_table(rows=0, cols=2)
        tb.style = "Table Grid"
        for k in ("學習內容", "學習歷程", "學習環境", "學習評量"):
            if t["adjust"].get(k):
                r = tb.add_row().cells
                r[0].text, r[1].text = k, t["adjust"][k]
    para(doc, "學習檢核重點", bold=True)
    for a, b in CHECK4:
        para(doc, f"☐ {a}：{b}", size=11)
    if L.get("source"):
        para(doc, L["source"], size=9)
    doc.save(out)
    print(f"Word：{out}")
    return True


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="六何法分層寫作：lesson.json → 互動網頁＋學習單")
    ap.add_argument("lesson")
    ap.add_argument("-o", "--out")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--no-docx", action="store_true")
    ap.add_argument("--check", action="store_true", help="只檢查 JSON")
    ap.add_argument("--word-font", default="標楷體")
    a = ap.parse_args()
    src = Path(a.lesson)
    L = json.loads(src.read_text(encoding="utf-8"))
    errs, warns = check(L, src.parent)
    for w in warns:
        print("提醒：" + w)
    if errs:
        for e in errs:
            print("錯誤：" + e)
        sys.exit(1)
    print("JSON 檢查通過。")
    if a.check:
        return
    out = Path(a.out) if a.out else src.parent
    out.mkdir(parents=True, exist_ok=True)
    name = safe(L["title"])
    web = out / f"{name}_互動網頁.html"
    web.write_text(make_html(L, "web"), encoding="utf-8")
    print(f"互動網頁：{web}")
    pages = []
    for i, v in enumerate(L["versions"]):
        h = out / f"{name}_學習單_{safe(v['name'])}.html"
        h.write_text(make_html(L, "sheet", i), encoding="utf-8")
        print(f"學習單：{h}")
        pages.append(h)
    th = out / f"{name}_教師版.html"
    th.write_text(make_html(L, "teacher"), encoding="utf-8")
    print(f"教師版：{th}")
    pages.append(th)
    if not a.no_pdf:
        for h in pages:
            to_pdf(h, h.with_suffix(".pdf"))
    if not a.no_docx:
        to_docx(L, out / f"{name}_學習單.docx", a.word_font)


if __name__ == "__main__":
    main()
