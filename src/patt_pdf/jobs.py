"""Job orchestration: plan → estimate → translate → render (+QA) → report/publish.

State directory layout (private; contains source text — do not publish):
  state/plans/<rel>.json, state/plans/<rel>.parts/<n>.json   page plans (resumable)
  state/plans/<rel>.error.json                               last planning error of a file
  state/tm.jsonl                                             translation memory (namespaced, see tm.py)
  state/ledger.jsonl                                         API request ledger (no key)
  state/runs.jsonl                                           translate-run summaries
  state/out/<rel>                                            rendered PDFs
  state/qa/<rel>.json                                        per-page QA
  state/accept.json                                          explicitly accepted QA limitations (optional)

v0.2 changes (see docs/STATUS.md for the reproduced v0.1 defects):
* translation memory lookups are scoped by backend namespace (pseudo ≠ manual ≠ deepl);
* every consumer of a plan re-validates it against the current source file
  (SHA-1, page count, engine version, OCR setting) and refuses stale plans;
* QA statuses: pass / review / unverified / fail (+ error), strict --only-pass;
* pages whose planning raised an error are retried on the next `plan` run;
* translation submits batches in a bounded window and stops submitting after a
  quota/auth error; requests that were in flight are reported as "possibly billed".
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path

import pymupdf

from . import ENGINE_VERSION
from .backends import AuthError, Backend, BackendError, BudgetExceeded, Meter, QuotaExceeded
from .model import PagePlan, Unit
from .tm import TranslationMemory

# ---------------------------------------------------------------- statuses
# Page / file QA status, ordered from best to worst. File status = worst page status.
PASS, REVIEW, UNVERIFIED, FAIL, ERROR = "pass", "review", "unverified", "fail", "error"
_RANK = {PASS: 0, REVIEW: 1, UNVERIFIED: 2, FAIL: 3, ERROR: 4}

# issue -> status it forces at least. Anything not listed is informational.
ISSUE_STATUS = {
    # FAIL: output is known to be wrong or incomplete
    "untranslated": FAIL, "number_or_url": FAIL, "keep_changed": FAIL, "residual_english": FAIL,
    "overflow": FAIL, "keep_lost": FAIL, "page_error": FAIL, "page_not_processed": FAIL,
    "textured_background_left_english": FAIL, "image_text_left_english": FAIL,
    "not_publishable_backend": FAIL, "mixed_translation_sources": REVIEW,
    # UNVERIFIED: a check that would be needed could not run
    "residual_check_skipped": UNVERIFIED, "image_not_inspected": UNVERIFIED, "image_unverified": UNVERIFIED,
    "possible_text_not_checked": UNVERIFIED, "source_repaired": UNVERIFIED,
    # REVIEW: probably fine, but a human must look
    "ocr_digits_review": REVIEW, "shrunk": REVIEW, "keep_restored": REVIEW, "override_used": REVIEW,
    "patch_on_textured_background": REVIEW,
    # underlines, strike-through lines and links attached to translated text (decor.py)
    "decoration_not_adjusted": REVIEW, "link_area_not_mapped": REVIEW,
    "markup_annotation_on_translated_text": REVIEW, "possible_underline_in_image": REVIEW,
    "decoration_check_failed": FAIL, "link_lost": FAIL, "text_crosses_rule": FAIL,
}


def worst(statuses) -> str:
    st = PASS
    for s in statuses:
        if _RANK[s] > _RANK[st]:
            st = s
    return st


class Workspace:
    def __init__(self, src: str | os.PathLike, state: str | os.PathLike):
        self.src = Path(src).resolve(); self.state = Path(state).resolve()
        if self.src.is_dir() and (self.state == self.src or self.src in self.state.parents):
            raise ValueError("state directory must not be inside the source directory")
        self.state.mkdir(parents=True, exist_ok=True)

    # -- inputs
    def sources(self, pattern: str | None = None) -> list[str]:
        if self.src.is_file():
            return [self.src.name] if self.src.suffix.lower() == ".pdf" else []
        out = []
        for p in sorted(self.src.rglob("*")):
            if p.is_file() and p.suffix.lower() == ".pdf":
                rel = p.relative_to(self.src).as_posix()
                if pattern is None or fnmatch.fnmatch(rel, pattern):
                    out.append(rel)
        return out

    def path(self, rel: str) -> Path:
        return self.src if self.src.is_file() else self.src / rel

    def plan_path(self, rel): return self.state / "plans" / (rel + ".json")
    def error_path(self, rel): return self.state / "plans" / (rel + ".error.json")
    def out_path(self, rel): return self.state / "out" / rel
    def qa_path(self, rel): return self.state / "qa" / (rel + ".json")

    def tm(self, overrides: dict | None = None) -> TranslationMemory:
        return TranslationMemory(self.state / "tm.jsonl", overrides)

    def accepted(self) -> dict:
        """{rel: {page(str) | "*": [issue, ...]}} from state/accept.json (explicit user decisions)."""
        p = self.state / "accept.json"
        return json.loads(p.read_text(encoding="utf-8")).get("files", {}) if p.exists() else {}

    def accept(self, rel: str, page: str, issue: str, note: str) -> None:
        """Record an explicit acceptance of a known limitation (kept in the report as REVIEW)."""
        if issue in NEVER_ACCEPTABLE:
            raise ValueError(f"issue {issue!r} cannot be accepted (output contradicts the source)")
        if issue not in ISSUE_STATUS:
            raise ValueError(f"unknown issue {issue!r}")
        p = self.state / "accept.json"
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"files": {}, "log": []}
        data["files"].setdefault(rel, {}).setdefault(page, [])
        if issue not in data["files"][rel][page]:
            data["files"][rel][page].append(issue)
        data["log"].append({"rel": rel, "page": page, "issue": issue, "note": note,
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
        atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1))


def sha1_file(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """UTF-8, atomic. Used for JSON state. File names that the OS could not decode (POSIX
    surrogate escapes) are written as JSON escapes ("\\udc93"), which json.loads reads back
    to the identical string, instead of crashing the batch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="backslashreplace") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def replace_file(tmp: str | os.PathLike, target: Path) -> None:
    """os.replace with a clear error when the target is locked (typical on Windows when the
    PDF is open in a viewer). The temp file is removed on failure; the old target stays."""
    try:
        os.replace(tmp, target)
    except PermissionError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise PermissionError(f"cannot replace {target}: file is in use or read-only "
                              f"(close it in your PDF viewer and re-run) [{e.__class__.__name__}]") from None


# ======================================================================== plan validity
class StalePlan(RuntimeError):
    """The stored plan does not describe the current source file / settings."""


def plan_state(ws: Workspace, rel: str, ocr: bool | None = None) -> tuple[str, str]:
    """Return (state, reason): state ∈ {"ok", "missing", "stale", "partial", "error", "source_missing"}.

    `ocr=None` accepts whatever OCR setting the plan was made with (used by consumers);
    `plan` passes the requested setting so a changed setting forces re-planning."""
    src = ws.path(rel); pp = ws.plan_path(rel)
    if not src.exists():
        return "source_missing", f"source file not found: {rel}"
    if not pp.exists():
        if ws.error_path(rel).exists():
            return "error", json.loads(ws.error_path(rel).read_text(encoding="utf-8")).get("error", "planning failed")
        return "missing", "not planned"
    j = json.loads(pp.read_text(encoding="utf-8"))
    if not j.get("complete"):
        return "partial", "planning did not finish"
    if j.get("engine") != ENGINE_VERSION:
        return "stale", f"planned with engine {j.get('engine')}, current is {ENGINE_VERSION}"
    if ocr is not None and j.get("ocr") != ocr:
        return "stale", f"planned with ocr={j.get('ocr')}, requested ocr={ocr}"
    st = src.stat()
    if j.get("size") != st.st_size or j.get("mtime_ns") != st.st_mtime_ns:   # cheap pre-check, then hash
        if j.get("sha") != sha1_file(src):
            return "stale", "source file content changed since planning"
    if j.get("failed_pages"):
        return "ok", f"pages with planning errors: {j['failed_pages']}"
    return "ok", ""


def load_plan(ws: Workspace, rel: str, verify: bool = True) -> list[PagePlan]:
    if verify:
        state, why = plan_state(ws, rel)
        if state != "ok":
            raise StalePlan(f"{rel}: {why} — run `patt-pdf plan` again")
    j = json.loads(ws.plan_path(rel).read_text(encoding="utf-8"))
    if verify:
        with pymupdf.open(ws.path(rel)) as d:
            if d.page_count != len(j["pages"]):
                raise StalePlan(f"{rel}: page count {d.page_count} ≠ planned {len(j['pages'])} — re-plan")
    return [PagePlan(p["page"], p["kind"], [Unit(**u) for u in p["units"]], p["keeps"], p.get("notes", []))
            for p in j["pages"]]


# ======================================================================== plan
def _no_paths(ws: Workspace, msg: str) -> str:
    """Error messages end up in reports that users share: strip local absolute paths."""
    for root, label in ((str(ws.src), "<input>"), (str(ws.state), "<state>")):
        msg = msg.replace(root, label)
    return msg


def _plan_error(ws: Workspace, rel: str, msg: str) -> dict:
    st = {"rel": rel, "status": "error", "error": _no_paths(ws, msg)}
    atomic_write_text(ws.error_path(rel), json.dumps(st, ensure_ascii=False))
    pp = ws.plan_path(rel)
    if pp.exists():                      # a previous plan no longer describes this file
        pp.unlink()
    return st


def plan_file(ws: Workspace, rel: str, ocr: bool = True, deadline: float | None = None) -> dict:
    """Plan one file with page-level checkpoints. Returns a status dict, never raises.
    Pages whose planning raised are retried on the next call; good pages are reused."""
    from . import analyze
    src = ws.path(rel); pp = ws.plan_path(rel)
    try:
        state, _ = plan_state(ws, rel, ocr)
        if state == "ok":
            j = json.loads(pp.read_text(encoding="utf-8"))
            if not j.get("failed_pages"):
                return {"rel": rel, "status": "cached", "pages": len(j["pages"])}
        sha = sha1_file(src)
        doc = pymupdf.open(src)
        if doc.needs_pass:
            return _plan_error(ws, rel, "PDF is encrypted (password required)")
        if doc.page_count == 0:
            return _plan_error(ws, rel, "PDF has no pages (damaged or empty)")
        # MuPDF silently reconstructs broken files (e.g. truncated downloads); depending on the
        # MuPDF version the result opens with blank or partial pages. Never let that pass.
        repaired = bool(getattr(doc, "is_repaired", False))
    except Exception as e:                                  # unreadable file: report, continue the batch
        return _plan_error(ws, rel, f"{type(e).__name__}: {e}"[:300])
    partd = Path(str(pp) + ".parts"); partd.mkdir(parents=True, exist_ok=True)
    pages, failed, reused = [], [], 0
    for pno in range(doc.page_count):
        f = partd / f"{pno}.json"
        if f.exists():
            j = json.loads(f.read_text(encoding="utf-8"))
            if (j.get("sha") == sha and j.get("engine") == ENGINE_VERSION and j.get("ocr") == ocr
                    and j["plan"]["kind"] != "error"):
                pages.append(j["plan"]); reused += 1; continue
        if deadline and time.time() > deadline:
            total = doc.page_count; doc.close()
            return {"rel": rel, "status": "partial", "pages": len(pages), "total": total}
        try:
            pl = asdict(analyze.plan_page(doc[pno], pno, ocr))
            if repaired:
                pl["notes"].append({"source_repaired": True})
        except Exception as e:
            pl = asdict(PagePlan(pno, "error", [], [], [{"error": f"{type(e).__name__}: {e}"[:300]}]))
            failed.append(pno + 1)
        atomic_write_text(f, json.dumps({"sha": sha, "engine": ENGINE_VERSION, "ocr": ocr, "plan": pl}, ensure_ascii=False))
        pages.append(pl)
    doc.close()
    st_ = src.stat()
    atomic_write_text(pp, json.dumps({"sha": sha, "size": st_.st_size, "mtime_ns": st_.st_mtime_ns,
                                      "engine": ENGINE_VERSION, "ocr": ocr, "rel": rel, "pages": pages,
                                      "page_count": len(pages), "failed_pages": failed, "complete": True},
                                     ensure_ascii=False))
    if ws.error_path(rel).exists():
        ws.error_path(rel).unlink()
    st = {"rel": rel, "status": "planned", "pages": len(pages), "reused_pages": reused}
    if failed:
        st["status"] = "planned_with_errors"; st["page_errors"] = failed
    return st


# ======================================================================== estimate
def estimate(ws: Workspace, files: list[str], ns: str, tm: TranslationMemory | None = None) -> dict:
    """Characters that still need translation in namespace `ns`, de-duplicated across files.
    DeepL bills source characters (including spaces) — this is what is counted."""
    tm = tm or ws.tm(); need: dict[str, None] = {}; per_file = {}; kinds: dict[str, int] = {}
    problems: dict[str, str] = {}
    cache_hits = 0
    for rel in files:
        state, why = plan_state(ws, rel)
        if state != "ok":
            problems[rel] = f"{state}: {why}"; continue
        c = 0
        for p in load_plan(ws, rel):
            kinds[p.kind] = kinds.get(p.kind, 0) + 1
            for u in p.units:
                if u.kind == "imgtext":
                    continue                       # image text is not translated (v0.x)
                if tm.get(u.src, ns)[0] is not None:
                    cache_hits += 1; continue
                if u.src not in need:
                    c += len(u.src); need[u.src] = None
        per_file[rel] = c
    return {"namespace": ns, "chars": sum(len(s) for s in need), "segments": len(need), "cache_hits": cache_hits,
            "per_file": per_file, "page_kinds": kinds, "problems": problems, "texts": list(need)}


# ======================================================================== translate
def translate(ws: Workspace, files: list[str], backend: Backend, max_chars: int, batch_chars: int = 6000,
              batch_items: int = 50, workers: int = 2, reserve: int = 20000, time_budget_s: float | None = None,
              log=print) -> dict:
    """Translate missing segments of `files` with `backend` into its TM namespace.

    Budget: refuses to start when the estimate exceeds `max_chars`, or (billable backends)
    the remaining account quota minus `reserve`. Backends that send requests get a Meter:
    every HTTP attempt, retries included, is counted in `sent_chars` and refused before
    sending if it would exceed `max_chars`, so retries cannot overrun the budget. Attempts
    whose outcome is unknown (timeout, network error, 5xx) are `possibly_billed_chars`:
    the server may have processed them; the client cannot know.

    Remote setup (DeepL glossary creation) happens in backend.prepare(), only after all
    budget checks passed and only if there is something to translate.

    Concurrency: at most `workers` batches are in flight; new batches are submitted only
    while no stop condition (quota/auth error, deadline) has occurred. Running requests
    cannot be cancelled; they are waited for and accounted for.
    """
    ns = backend.namespace
    tm = ws.tm(); est = estimate(ws, files, ns, tm)
    summary = {"backend": backend.name, "namespace": ns, "estimate_chars": est["chars"], "segments": est["segments"],
               "cache_hits": est["cache_hits"], "max_chars": max_chars, "batches_total": 0, "batches_submitted": 0,
               "batches_completed": 0, "batches_failed": 0, "submitted_chars": 0, "translated_chars": 0,
               "possibly_billed_chars": 0, "missing_from_backend": 0, "stopped": None, "outcome": None,
               "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    blocking = {r: p for r, p in est["problems"].items() if not p.startswith("error:")}
    summary["skipped_unreadable"] = sorted(r for r, p in est["problems"].items() if p.startswith("error:"))
    if blocking:
        summary["stopped"] = "plans missing or stale: " + "; ".join(f"{r} ({p})" for r, p in list(blocking.items())[:5])
        summary["outcome"] = "refused"; return _log_run(ws, summary)
    if not files:
        summary["stopped"] = "no input PDFs"; summary["outcome"] = "failed"; return _log_run(ws, summary)
    if len(summary["skipped_unreadable"]) == len(files):
        summary["stopped"] = f"no readable input: all {len(files)} file(s) failed planning"
        summary["outcome"] = "failed"; return _log_run(ws, summary)
    if est["chars"] == 0:
        summary["stopped"] = "nothing to translate"; summary["outcome"] = "complete"
        return _log_run(ws, _unreadable_is_incomplete(summary))
    if est["chars"] > max_chars:
        summary["stopped"] = f"estimate {est['chars']} chars exceeds --max-chars {max_chars}"
        summary["outcome"] = "refused"; return _log_run(ws, summary)
    if backend.billable:
        u = backend.usage()
        remaining = u["character_limit"] - u["character_count"]
        summary["usage_before"] = {"count": u["character_count"], "limit": u["character_limit"]}
        if est["chars"] > remaining - reserve:
            summary["stopped"] = f"estimate {est['chars']} exceeds remaining quota {remaining} minus reserve {reserve}"
            summary["outcome"] = "refused"; return _log_run(ws, summary)
    meter = Meter(max_chars)
    backend.meter = meter
    try:
        backend.prepare()                      # e.g. create the DeepL glossary: after budget checks only
    except (QuotaExceeded, AuthError, BackendError) as e:
        summary["stopped"] = f"backend setup failed: {e}"; summary["outcome"] = "failed"
        return _log_run(ws, summary)
    batches, cur, cc = [], [], 0
    for s in est["texts"]:
        if cur and (cc + len(s) > batch_chars or len(cur) >= batch_items):
            batches.append(cur); cur, cc = [], 0
        cur.append(s); cc += len(s)
    if cur:
        batches.append(cur)
    summary["batches_total"] = len(batches)
    deadline = time.time() + time_budget_s if time_budget_s else None
    stop = threading.Event()
    lock = threading.Lock()

    def run(b):
        return backend.translate(b)

    pending = list(batches)
    inflight: dict = {}
    workers = max(1, workers)
    with ThreadPoolExecutor(workers) as ex:
        while pending or inflight:
            while pending and len(inflight) < workers and not stop.is_set():
                if deadline and time.time() > deadline:
                    summary["stopped"] = summary["stopped"] or "time budget reached"; stop.set(); break
                if summary["submitted_chars"] + sum(len(s) for s in pending[0]) > max_chars:   # defensive
                    summary["stopped"] = "max_chars reached"; stop.set(); break
                b = pending.pop(0)
                inflight[ex.submit(run, b)] = b
                summary["batches_submitted"] += 1; summary["submitted_chars"] += sum(len(s) for s in b)
            if not inflight:
                break
            done, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
            for f in done:
                b = inflight.pop(f); chars = sum(len(s) for s in b)
                try:
                    res = f.result()
                except BudgetExceeded as e:           # a retry would overrun --max-chars
                    with lock:
                        summary["stopped"] = summary["stopped"] or f"budget: {e}"; summary["batches_failed"] += 1
                    stop.set(); continue
                except (QuotaExceeded, AuthError) as e:
                    with lock:
                        summary["stopped"] = summary["stopped"] or str(e); summary["batches_failed"] += 1
                    stop.set(); continue
                except BackendError as e:
                    summary["batches_failed"] += 1
                    if not meter.attempts: summary["possibly_billed_chars"] += chars   # unmetered backend
                    log(f"batch failed (will be retried on the next run): {e}"); continue
                except Exception as e:                        # unexpected: treat like a failed request
                    summary["batches_failed"] += 1
                    if not meter.attempts: summary["possibly_billed_chars"] += chars
                    log(f"batch failed unexpectedly: {type(e).__name__}: {e}"); continue
                summary["batches_completed"] += 1
                for s, t in zip(b, res):
                    if t is None:
                        summary["missing_from_backend"] += 1; continue
                    tm.put(s, t, ns, backend.name); summary["translated_chars"] += len(s)
    backend.meter = None
    if meter.attempts:                               # backend reported its HTTP attempts
        summary["sent_chars"] = meter.sent           # all attempts incl. retries (upper bound of billing)
        summary["retry_attempts"] = meter.retries
        summary["rejected_chars"] = meter.rejected   # answered with an error: not processed
        summary["possibly_billed_chars"] = meter.unknown
    else:
        summary["sent_chars"] = summary["submitted_chars"]
    if backend.billable and "usage_before" in summary:
        try:
            u = backend.usage(); summary["usage_after"] = {"count": u["character_count"], "limit": u["character_limit"]}
            summary["billed_delta"] = u["character_count"] - summary["usage_before"]["count"]
        except Exception as e:
            summary["usage_after_error"] = f"{type(e).__name__}"
    summary["remaining_chars"] = estimate(ws, files, ns, ws.tm())["chars"]
    if summary["remaining_chars"] == 0 and not summary["batches_failed"]:
        summary["outcome"] = "complete"
    elif summary["translated_chars"] > 0:
        summary["outcome"] = "partial"
    else:
        summary["outcome"] = "failed"
    return _log_run(ws, _unreadable_is_incomplete(summary))


def _unreadable_is_incomplete(summary):
    """Readable files may be complete, but the batch is not: unreadable inputs were skipped."""
    sk = summary["skipped_unreadable"]
    if sk and summary["outcome"] == "complete":
        summary["outcome"] = "partial"
        summary["stopped"] = ((summary["stopped"] + "; ") if summary["stopped"] else "") + (
            f"{len(sk)} unreadable file(s) skipped: {', '.join(sk[:5])} - repair, decrypt or remove them "
            "and run `plan` again, or leave them out with --files")
    return summary


def _log_run(ws, summary):
    with open(ws.state / "runs.jsonl", "a", encoding="utf-8", errors="backslashreplace") as fh:   # see atomic_write_text
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary


# ======================================================================== render
def _page_status(pq: dict, accepted: list[str]) -> str:
    sts = []
    for i in pq["issues"]:
        s = ISSUE_STATUS.get(i.get("issue"))
        if s is None:
            continue
        if i.get("issue") in accepted and s in (REVIEW, UNVERIFIED, FAIL) and i.get("issue") not in NEVER_ACCEPTABLE:
            i["accepted"] = True
            s = REVIEW                                # accepted limitations stay visible as REVIEW
        sts.append(s)
    return worst(sts)


# Issues that cannot be waived: they mean the output contradicts the source.
NEVER_ACCEPTABLE = {"link_lost", "number_or_url", "keep_changed", "keep_lost", "page_error", "not_publishable_backend", "untranslated"}


def render_file(ws: Workspace, rel: str, ns: str, publishable: bool = True, ocr_qa: bool = True) -> dict:
    """Render one file to state/out/<rel> with translations from TM namespace `ns`, and
    write state/qa/<rel>.json. Never raises. `publishable=False` (pseudo) forces FAIL."""
    from . import fonts as F
    from .qa import keep_integrity, number_check, residual_english, residual_english_ocr, url_check
    from .render import apply_plan
    src = ws.path(rel); out_path = ws.out_path(rel)
    qa = {"rel": rel, "engine": ENGINE_VERSION, "namespace": ns, "pages": [], "status": ERROR}
    accepted_file = ws.accepted().get(rel, {})
    try:
        state, why = plan_state(ws, rel)
        if state != "ok":
            raise StalePlan(f"{state}: {why}")
        src_sha = sha1_file(src)
        tm = ws.tm(); plans = load_plan(ws, rel)
        origins: set[str] = set()
        for plan in plans:
            for u in plan.units:
                t, origin = tm.get(u.src, ns)
                if t:
                    u.tgt = t; origins.add(origin)
        fs = F.FontSet([u.tgt for p in plans for u in p.units if u.tgt])
        token = F.activate(fs)
        tmp = None
        doc = pymupdf.open(src)
        try:
            for plan in plans:
                pq = {"page": plan.page + 1, "kind": plan.kind, "units": len(plan.units), "issues": []}
                missing = 0
                for u in plan.units:
                    if u.kind == "imgtext":
                        continue                   # reported via image inventory / screen_units
                    if not u.tgt:
                        missing += 1; continue
                    for issue in number_check(u.src, u.tgt) + url_check(u.src, u.tgt):
                        pq["issues"].append({"uid": u.uid, "issue": "number_or_url", "detail": issue,
                                             "src": u.src[:80], "tgt": u.tgt[:80]})
                    if u.kind in ("vector", "raster") and any(ch.isdigit() for ch in u.src):
                        pq["issues"].append({"uid": u.uid, "issue": "ocr_digits_review", "src": u.src[:70]})
                    if tm.get(u.src, ns)[1] == "override":
                        pq["issues"].append({"uid": u.uid, "issue": "override_used"})
                if missing:
                    pq["issues"].append({"issue": "untranslated", "detail": f"{missing} unit(s) have no translation in {ns}"})
                pq["untranslated_units"] = missing
                if not publishable and plan.units:
                    pq["issues"].append({"issue": "not_publishable_backend",
                                         "detail": "placeholder text from the pseudo backend"})
                for n in plan.notes:
                    for im in n.get("images", []):
                        if im.get("english"):
                            pq["issues"].append({"issue": "image_text_left_english", "src": im["english"], "bbox": im["bbox"]})
                        elif im.get("english") is None:
                            pq["issues"].append({"issue": "image_not_inspected", "bbox": im["bbox"]})
                        else:   # OCR found nothing legible: it may still contain text (busy backgrounds)
                            pq["issues"].append({"issue": "image_unverified", "bbox": im["bbox"]})
                for n in plan.notes:
                    if n.get("source_repaired"):
                        pq["issues"].append({"issue": "source_repaired",
                                             "detail": "the PDF was damaged and reconstructed while opening; content may be missing"})
                    if "unverified" in n:
                        pq["issues"].append({"issue": "possible_text_not_checked", "detail": n["unverified"]})
                if any("skipped" in n for n in plan.notes):
                    pq["issues"].append({"issue": "page_not_processed",
                                         "detail": "; ".join(n["skipped"] for n in plan.notes if "skipped" in n)})
                if plan.kind == "error":
                    pq["issues"].append({"issue": "page_error", "detail": plan.notes})
                elif plan.units:
                    pq["issues"] += apply_plan(doc[plan.page], plan)
                qa["pages"].append(pq)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=out_path.parent, prefix=".tmp-", suffix=".pdf"); os.close(fd)
            try:
                doc.save(tmp, garbage=3, deflate=True)
            except BaseException:
                os.unlink(tmp); tmp = None
                raise
        finally:
            doc.close(); F._ACTIVE.reset(token); shutil.rmtree(fs.workdir, ignore_errors=True)
        replace_file(tmp, out_path)
        # post-render checks on the saved file (fresh handles)
        _compare_links(src, out_path, plans, qa["pages"])
        for plan, pq in zip(plans, qa["pages"]):
            if plan.kind not in ("error", "blank", "graphics"):
                pq["keep_changed"] = keep_integrity(src, out_path, plan.page, plan)
                if pq["keep_changed"]:
                    pq["issues"].append({"issue": "keep_changed", "detail": pq["keep_changed"][:5]})
                tg = [u.tgt for u in plan.units if u.tgt]
                with pymupdf.open(out_path) as o:
                    if plan.kind == "text":
                        pq["residual_en"] = residual_english(o[plan.page], plan, tg)
                    elif ocr_qa:
                        pq["residual_en"] = residual_english_ocr(o[plan.page], plan, tg)
                    else:
                        pq["residual_en"] = None; pq["issues"].append({"issue": "residual_check_skipped"})
                if pq["residual_en"] and len(pq["residual_en"]) > 3:
                    pq["issues"].append({"issue": "residual_english", "detail": " ".join(pq["residual_en"][:8])})
            pq["notes"] = plan.notes
            pq["status"] = _page_status(pq, accepted_file.get(str(pq["page"]), []) + accepted_file.get("*", []))
            pq["pass"] = pq["status"] == PASS
        qa["status"] = worst(p["status"] for p in qa["pages"]) if qa["pages"] else ERROR
        qa["source_sha1"] = src_sha
        qa["translation_origins"] = sorted(origins)
    except Exception as e:
        qa["status"] = ERROR; qa["error"] = _no_paths(ws, f"{type(e).__name__}: {e}")[:300]
    qa["pass"] = qa["status"] == PASS                 # kept for backward compatibility
    atomic_write_text(ws.qa_path(rel), json.dumps(qa, ensure_ascii=False, indent=1))
    return qa


def _compare_links(src, out_path, plans, pages):
    """Independent check on the saved file: every link target of the source page must still
    exist on the output page (MuPDF redaction deletes overlapping links)."""
    def targets(p):
        return sorted(str((l.get("kind"), l.get("uri"), l.get("page"), l.get("file"), l.get("name")))
                      for l in p.get_links())
    with pymupdf.open(src) as s_, pymupdf.open(out_path) as o_:
        for plan, pq in zip(plans, pages):
            a, b = targets(s_[plan.page]), targets(o_[plan.page])
            if a != b and not any(i.get("issue") == "link_lost" for i in pq["issues"]):
                pq["issues"].append({"issue": "link_lost", "expected": len(a), "found": len(b)})


# ======================================================================== publish
def publish(ws: Workspace, files: list[str], dest: str | os.PathLike, min_status: str = PASS,
            suffix: str = "", only_pass: bool | None = None) -> list[dict]:
    """Copy rendered PDFs to `dest`. A file is published only if its QA status is at least
    as good as `min_status` (default: pass), its QA was made from the CURRENT source file,
    and the output exists. Existing targets are never overwritten."""
    if only_pass is not None:                         # v0.1 compatibility
        min_status = PASS if only_pass else ERROR
    dest = Path(dest).resolve()
    if ws.src.is_dir() and (dest == ws.src or ws.src in dest.parents):
        raise ValueError("destination must not be inside the source directory")
    out = []
    for rel in files:
        qp, op = ws.qa_path(rel), ws.out_path(rel)
        if not (qp.exists() and op.exists()):
            out.append({"rel": rel, "published": False, "why": "not rendered"}); continue
        qa = json.loads(qp.read_text(encoding="utf-8"))
        status = qa.get("status") or (PASS if qa.get("pass") else FAIL)
        if status == ERROR or _RANK.get(status, 9) > _RANK[min_status]:
            out.append({"rel": rel, "published": False, "why": f"QA status {status} (required: {min_status} or better)"}); continue
        if qa.get("source_sha1") != sha1_file(ws.path(rel)):
            out.append({"rel": rel, "published": False, "why": "source changed after rendering — re-plan and re-render"}); continue
        target = dest / rel
        if suffix:
            target = target.with_name(target.stem + suffix + target.suffix)
        if target.exists():
            out.append({"rel": rel, "published": False, "why": f"exists: {target} (not overwritten)"}); continue
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".pdf"); os.close(fd)
        try:
            shutil.copyfile(op, tmp); replace_file(tmp, target)
        except OSError as e:
            if os.path.exists(tmp):
                os.unlink(tmp)
            out.append({"rel": rel, "published": False, "why": str(e)}); continue
        out.append({"rel": rel, "published": True, "to": str(target), "status": status})
    return out
