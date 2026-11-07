"""Shared fixtures. All tests are offline: synthetic PDFs, manual/pseudo/fake backends,
and a fake HTTP opener for DeepL logic. No network, no API quota."""
from __future__ import annotations

import os
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "fixtures"))
sys.path.insert(0, str(HERE))
import make_fixtures  # noqa: E402

sys.path.insert(0, str(HERE.parent / "src"))
from patt_pdf.osenv import find_tesseract  # noqa: E402

# same discovery as the product: PATT_PDF_TESSERACT, PATH, OS default install folders
HAS_TESSERACT = find_tesseract()[0] is not None
HAS_CV2 = importlib.util.find_spec("cv2") is not None
HAS_OCR = HAS_TESSERACT and HAS_CV2
needs_ocr = pytest.mark.skipif(not HAS_OCR, reason="tesseract CLI and opencv required")


@pytest.fixture(scope="session")
def corpus(tmp_path_factory):
    d = tmp_path_factory.mktemp("corpus")
    src = d / "src"
    make_fixtures.main(str(src))
    shutil.move(str(src / "truth.json"), d / "truth.json")
    shutil.move(str(src / "manual_tm.json"), d / "manual_tm.json")
    return {"src": src, "truth": make_fixtures.load_truth(d / "truth.json"), "manual_tm": d / "manual_tm.json", "root": d}


@pytest.fixture
def mini(tmp_path, corpus):
    """A private, writable copy of a few fixtures (tests may modify/replace files)."""
    src = tmp_path / "src"; src.mkdir()
    for n in ("toc.pdf", "financial.pdf", "image_text.pdf", "rotated.pdf"):
        shutil.copy(corpus["src"] / n, src / n)
    return {"src": src, "state": tmp_path / "state", "manual_tm": corpus["manual_tm"], "tmp": tmp_path}


@pytest.fixture(scope="session")
def fonts_ready(tmp_path_factory):
    """Extract CJK fonts once per test session into a temp dir (from system Noto CJK)."""
    from patt_pdf import fonts
    if os.environ.get("PATT_PDF_FONT_DIR") and all((Path(os.environ["PATT_PDF_FONT_DIR"]) / f).exists()
                                                   for f in fonts.FACES.values()):
        return Path(os.environ["PATT_PDF_FONT_DIR"])
    d = tmp_path_factory.mktemp("fonts")
    os.environ["PATT_PDF_FONT_DIR"] = str(d)
    rep = fonts.install_fonts(d)
    if any(v.startswith(("MISSING", "FAILED")) for v in rep.values()):
        pytest.skip("Noto CJK fonts not installed on this system")
    return d


@pytest.fixture(scope="session")
def rendered(corpus, fonts_ready, tmp_path_factory):
    """Full offline pipeline once with the manual backend (fixture TM) + a fake MT for the rest."""
    from fakes import FakeMT
    from patt_pdf.backends import ManualBackend
    from patt_pdf.jobs import Workspace, plan_file, render_file, translate
    state = tmp_path_factory.mktemp("state")
    ws = Workspace(corpus["src"], state)
    files = ws.sources()
    plans = {rel: plan_file(ws, rel, ocr=HAS_OCR) for rel in files}
    manual = ManualBackend(corpus["manual_tm"])
    tr = translate(ws, files, manual, max_chars=100_000)
    # the manual TM does not cover every segment (e.g. OCR'd footer "Page 3 of 9"): render with
    # the fake MT identity, after copying the manual results into it
    fake = FakeMT()
    tm = ws.tm()
    for (ns, src_), (tgt, _) in list(tm.entries.items()):
        if ns == manual.namespace:
            tm.put(src_, tgt, fake.namespace, "manual")
    tr2 = translate(ws, files, fake, max_chars=100_000)
    qa = {rel: render_file(ws, rel, fake.namespace, ocr_qa=HAS_OCR) for rel in files}
    return {"ws": ws, "files": files, "plans": plans, "qa": qa, "tr": (tr, tr2), "src": corpus["src"],
            "ns": fake.namespace}
