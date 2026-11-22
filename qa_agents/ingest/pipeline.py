"""Ingest pipeline: files -> scenario use-case packages.

    fetch (sources) -> read (readers) -> annotate -> clean (cleaners) -> extract items
      -> find scenarios -> cluster/match across documents -> assign items
      -> detect conflicts -> assemble one package per scenario -> confidence report

Every stage's output can be saved to <run>/00_ingest/ for inspection.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

from . import registry
from .model import Conflict, IngestedDocument, IngestReport, IngestResult, Item, Scenario, ScenarioPackage
from .profile import ClientProfile, load_profile
from .readers import LEGACY_FORMATS
from .scenarios import SHARED, cluster_mentions, mentions_in
from .tables import detect_id_column, detect_scenario_column, norm, scenario_mentions

TRACE_HEADER = re.compile(r"trace|brd ref|parent|derived|maps? to|linked|source req", re.I)


class IngestError(RuntimeError):
    pass


class IngestPipeline:
    def __init__(self, profile: ClientProfile | str | None = None, plugins: list[str] | None = None,
                 source_settings: dict | None = None, log=print):
        registry.load_builtin()
        registry.load_external(plugins)
        self.profile = profile if isinstance(profile, ClientProfile) else load_profile(profile)
        self.source_settings = source_settings or {}
        self.log = log

    # ------------------------------------------------------------ fetch + read
    def fetch(self, inputs: Iterable[str], download_dir: Path) -> list[tuple[Path, str]]:
        files: list[tuple[Path, str]] = []
        sources = [cls(self.source_settings.get(name, {})) for name, cls in registry.available("source").items()]
        sources.sort(key=lambda s: s.priority)
        for uri in inputs:
            src = next((s for s in sources if s.can_handle(uri)), None)
            if src is None:
                raise IngestError(f"No source plug-in can open '{uri}'. Is the path or link correct?")
            got = src.fetch(uri, download_dir)
            if not got:
                raise IngestError(f"'{uri}' contained no supported files.")
            files.extend(got)
        return files

    def read(self, files: list[tuple[Path, str]]) -> tuple[list[IngestedDocument], list[str]]:
        readers = [cls() for cls in registry.available("reader").values()]
        docs, warnings = [], []
        for path, display in files:
            ext = path.suffix.lower()
            if ext in LEGACY_FORMATS:
                warnings.append(f"{display}: {LEGACY_FORMATS[ext]}")
                continue
            reader = next((r for r in readers if r.can_read(path)), None)
            if reader is None:
                warnings.append(f"{display}: unsupported file type '{ext}', skipped.")
                continue
            doc = reader.read(path, self.profile, display)
            self._annotate(doc)
            for name in self.profile.cleaners:
                doc = registry.get("cleaner", name)().apply(doc, self.profile)
            docs.append(doc)
        return docs, warnings

    def _annotate(self, doc: IngestedDocument) -> None:
        parts = [doc.title, doc.name]
        for b in doc.blocks[:60]:
            parts.append(b.text)
            if b.kind == "table":
                parts.append(" | ".join(b.headers))
                parts += [" | ".join(f"{k} | {v}" for k, v in r.cells.items()) for r in b.rows[:6]]
        sample = "\n".join(p for p in parts if p)
        head = "\n".join([doc.title, doc.name] + [b.text for b in doc.blocks[:8]])
        if any(re.search(m if m.startswith("\\") else re.escape(m), head, re.I) for m in self.profile.brs_markers):
            doc.role = "brs"
        elif any(re.search(m if m.startswith("\\") else re.escape(m), head, re.I) for m in self.profile.brd_markers):
            doc.role = "brd"
        ids = [m for p in self.profile.doc_id_patterns for m in re.findall(p, sample, re.I)]
        parents = [m for p in self.profile.parent_id_patterns for m in re.findall(p, sample, re.I)]
        doc.doc_ids = list(dict.fromkeys(i for i in ids if i not in parents))
        doc.parent_ids = list(dict.fromkeys(p for p in parents if p not in doc.doc_ids))
        if not doc.title:
            doc.title = next((b.text for b in doc.blocks if b.kind == "heading" and not b.meta.get("sheet_title")), doc.name)

    # ------------------------------------------------------------ items
    def extract_items(self, doc: IngestedDocument, start: int = 0) -> list[Item]:
        p, items, stack = self.profile, [], []   # stack: (level, text, has_mention)
        n = start
        headings_seen = 0
        for b in doc.blocks:
            if b.kind == "heading" and not b.meta.get("sheet_title"):
                headings_seen += 1
            front = doc.format in ("pdf", "docx") and headings_seen <= 1
            if b.kind == "heading":
                stack = [s for s in stack if s[0] < b.level] + [(b.level, b.text, bool(scenario_mentions(b.text, p)))]
                continue
            section = " > ".join(s[1] for s in stack)
            heading_hint = next((s[1] for s in reversed(stack) if s[2]), None)
            if b.kind == "table":
                id_col = b.meta.get("id_column") or detect_id_column(b, p)
                sc_col = b.meta.get("scenario_column")
                if sc_col is None:
                    sc_col = detect_scenario_column(b, p, id_col)
                trace_cols = [h for h in b.headers if TRACE_HEADER.search(h)]
                for r in b.rows:
                    n += 1
                    iid = r.cells.get(id_col) if id_col and p.is_id(r.cells.get(id_col, "")) else None
                    fields = dict(r.cells)
                    traces = [m.group(0) for c in trace_cols for rx in p.id_regexes() for m in rx.finditer(r.cells.get(c, ""))]
                    items.append(Item(uid=f"I{n:05d}", item_id=iid, doc=doc.name, role=doc.role, section=section,
                                      fields=fields, ref=r.ref.model_copy(update={"section": section}),
                                      scenario_hint=r.cells.get(sc_col) if sc_col else None,
                                      has_scenario_column=bool(sc_col), heading_hint=heading_hint,
                                      traces=list(dict.fromkeys(traces)), front_matter=front))
            elif b.kind in ("paragraph", "list_item"):
                n += 1
                text = norm(b.text)
                body = re.sub(r"^\s*(\d{1,2}[.)]\s+)", "", text)
                iid = p.leading_id(body)
                if not iid:
                    m = re.search(r"\(([^()]{2,25})\)", body[:90])
                    iid = m.group(1) if m and p.is_id(m.group(1)) else None
                ms = scenario_mentions(body, p)
                hint = body if ms and ms[0].start() == 0 else None
                items.append(Item(uid=f"I{n:05d}", item_id=iid, doc=doc.name, role=doc.role, section=section,
                                  text=text, ref=b.ref.model_copy(update={"section": section}),
                                  scenario_hint=hint, heading_hint=heading_hint, front_matter=front))
        return items

    # ------------------------------------------------------------ run
    def run(self, inputs: list[str], work_dir: Path, save: bool = True) -> IngestResult:
        work_dir = Path(work_dir)
        dl = work_dir / "00_ingest" / "downloads"
        dl.mkdir(parents=True, exist_ok=True)
        files = self.fetch(inputs, dl)
        docs, warnings = self.read(files)
        if not docs:
            raise IngestError("No readable documents. " + " ".join(warnings))
        items: list[Item] = []
        for d in docs:
            items += self.extract_items(d, start=len(items))
            warnings += d.warnings

        mentions = []
        for d in docs:
            for name in self.profile.scenario_finders:
                mentions += registry.get("scenario_finder", name)().find(d, self.profile)
        if self.profile.segment_mode == "whole_file":
            mentions = []
        scenarios, mapping = cluster_mentions(mentions, self.profile, [d.name for d in docs])
        from .scenarios import assign
        if scenarios:
            assign(items, scenarios, mapping, self.profile)
        else:
            for it in items:
                it.scenarios, it.assigned_by = [SHARED], "whole-file"

        conflicts: list[Conflict] = []
        for name in self.profile.conflict_detectors:
            conflicts += registry.get("conflict_detector", name)().detect(items, docs, self.profile)
        for i, c in enumerate(conflicts, 1):
            c.id = f"CF-{i:02d}"

        packages = self._assemble(docs, scenarios, items, conflicts)
        report = self._report(docs, scenarios, items, conflicts, warnings, mentions)
        result = IngestResult(documents=docs, scenarios=scenarios, items=items, packages=packages, report=report)
        if save:
            self.save(result, work_dir / "00_ingest")
        return result

    # ------------------------------------------------------------ assemble
    def _assemble(self, docs, scenarios, items, conflicts) -> list[ScenarioPackage]:
        if not scenarios:
            name = docs[0].title if len(docs) == 1 else "Combined requirements"
            sc = Scenario(key="SCN-01", name=name[:90], found_in=[d.name for d in docs])
            return [ScenarioPackage(scenario=sc, items=items, conflicts=conflicts,
                                    text=self._render(sc, items, [], conflicts, docs))]
        out = []
        for sc in scenarios:
            own = [it for it in items if sc.key in it.scenarios]
            shared = [it for it in items if SHARED in it.scenarios]
            cfs = [c for c in conflicts if not c.scenarios or sc.key in c.scenarios]
            out.append(ScenarioPackage(scenario=sc, items=own + shared, conflicts=cfs,
                                       text=self._render(sc, own, shared, cfs, docs)))
        return out

    @staticmethod
    def _fmt_item(it: Item) -> str:
        src = f" _(source: {it.ref.label()})_"
        if it.fields:
            body = "; ".join(f"{k}: {v}" for k, v in it.fields.items() if v != it.item_id).replace("\n", " / ")
        else:
            body = it.text
        return f"- {'**' + it.item_id + '** — ' if it.item_id else ''}{body}{src}"

    def _render(self, sc: Scenario, own: list[Item], shared: list[Item], cfs: list[Conflict], docs) -> str:
        role = {d.name: d for d in docs}
        lines = [f"# {sc.key}: {sc.name}", ""]
        if sc.aliases:
            lines.append(f"Also referred to as: {'; '.join(sc.aliases)}")
        lines.append("Combined from: " + "; ".join(
            f"{d.name} ({d.role.upper()}{', ' + ', '.join(d.doc_ids) if d.doc_ids else ''})" for d in docs))
        lines.append("")

        def section(title, its):
            if not its:
                return
            lines.extend([f"## {title}", ""])
            by_doc: dict[str, dict[str, list[Item]]] = {}
            for it in its:
                by_doc.setdefault(it.doc, {}).setdefault(it.section or "(untitled section)", []).append(it)
            for dname, secs in by_doc.items():
                d = role.get(dname)
                lines.append(f"### From {dname} ({d.role.upper() if d else ''})")
                for s, group in secs.items():
                    lines.append(f"#### {s}")
                    lines.extend(self._fmt_item(it) for it in group)
                lines.append("")

        section("Scenario-specific requirements", own)
        section("Shared / cross-scenario requirements (apply to this scenario too)", shared)
        if cfs:
            lines.extend(["## Conflicts detected automatically between sources (must be raised with the BA)", ""])
            lines.extend(f"- **{c.id}** [{c.kind}]: {c.description}" for c in cfs)
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------ report
    def _report(self, docs, scenarios, items, conflicts, warnings, mentions) -> IngestReport:
        rep = IngestReport(conflicts=conflicts, warnings=warnings)
        reasons = []
        for d in docs:
            its = [it for it in items if it.doc == d.name]
            by = {}
            for it in its:
                by[it.assigned_by] = by.get(it.assigned_by, 0) + 1
            n_ids = sum(bool(it.item_id) for it in its)
            rep.documents.append({"name": d.name, "format": d.format, "role": d.role, "doc_ids": d.doc_ids,
                                  "traces_to": d.parent_ids, "blocks": len(d.blocks), "items": len(its),
                                  "items_with_id": n_ids, "assignment": by,
                                  "scenario_mentions": sum(m.doc == d.name for m in mentions)})
            shared_share = (by.get("shared", 0)) / len(its) if its else 0
            if scenarios and its and shared_share > 0.6:
                reasons.append(f"{d.name}: {shared_share:.0%} of its items could not be tied to a scenario.")
        for sc in scenarios:
            own = [it for it in items if sc.key in it.scenarios]
            rep.scenarios.append({"key": sc.key, "name": sc.name, "aliases": sc.aliases, "found_in": sc.found_in,
                                  "items": len(own), "keywords": sc.keywords,
                                  "by_document": {d.name: sum(it.doc == d.name for it in own) for d in docs}})
            missing = [d.name for d in docs if not any(it.doc == d.name for it in own)]
            if missing and len(docs) > 1:
                reasons.append(f"{sc.key} ({sc.name}) has no items from: {', '.join(missing)}.")
        n_ids = sum(bool(it.item_id) for it in items)
        if not scenarios:
            if n_ids >= 15 and self.profile.segment_mode != "whole_file":
                rep.confidence = "low"
                reasons.append(f"No scenarios / use cases were found, but {n_ids} ID'd requirements exist. Treating "
                               f"everything as ONE use case is probably wrong. Set a client profile "
                               f"(scenario_patterns / segment_mode) or confirm with segment_mode: whole_file.")
            else:
                rep.confidence = "medium"
                reasons.append("No scenarios found: the whole input is treated as one use case.")
        elif reasons:
            rep.confidence = "medium"
        if any("look scanned" in w for w in warnings):
            reasons.append("Some PDF pages look scanned and were not read.")
            if not items:
                rep.confidence = "low"
            elif rep.confidence == "high":
                rep.confidence = "medium"
        rep.confidence_reasons = reasons
        rep.ok_to_continue = rep.confidence != "low"
        return rep

    # ------------------------------------------------------------ save
    @staticmethod
    def save(result: IngestResult, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        dump = lambda o: json.dumps(o, indent=2, ensure_ascii=False, default=str)  # noqa: E731
        (out / "documents.json").write_text(dump([d.model_dump(mode="json") for d in result.documents]), encoding="utf-8")
        (out / "items.json").write_text(dump([i.model_dump(mode="json") for i in result.items]), encoding="utf-8")
        (out / "report.json").write_text(dump(result.report.model_dump(mode="json")), encoding="utf-8")
        (out / "report.md").write_text(render_report(result), encoding="utf-8")
        for pkg in result.packages:
            (out / f"{pkg.scenario.key}.md").write_text(pkg.text, encoding="utf-8")


def render_report(result: IngestResult) -> str:
    r = result.report
    L = [f"# Ingest preview", "", f"**Confidence: {r.confidence.upper()}**"
         + (" — the pipeline will continue." if r.ok_to_continue else " — the pipeline will STOP until this is fixed.")]
    if r.confidence_reasons:
        L += [""] + [f"- {x}" for x in r.confidence_reasons]
    L += ["", "## Documents", "", "| File | Type | Doc ID | Traces to | Items (with ID) | How items were assigned |",
          "|---|---|---|---|---|---|"]
    for d in r.documents:
        how = ", ".join(f"{k or '-'}: {v}" for k, v in sorted(d["assignment"].items()))
        L.append(f"| {d['name']} | {d['role'].upper()} ({d['format']}) | {', '.join(d['doc_ids']) or '-'} | "
                 f"{', '.join(d['traces_to']) or '-'} | {d['items']} ({d['items_with_id']}) | {how} |")
    L += ["", "## Scenarios (one use case each)", ""]
    if r.scenarios:
        L += ["| Key | Name | Found in | Items per document | Also called |", "|---|---|---|---|---|"]
        for s in r.scenarios:
            per = ", ".join(f"{k}: {v}" for k, v in s["by_document"].items())
            L.append(f"| {s['key']} | {s['name']} | {len(s['found_in'])} file(s) | {per} | {'; '.join(s['aliases'][:3])} |")
        shared = sum(SHARED in it.scenarios for it in result.items)
        L += ["", f"Shared items (added to every scenario): {shared}"]
    else:
        L.append("No scenarios found; the whole input is one use case.")
    L += ["", f"## Conflicts between sources ({len(r.conflicts)})", ""]
    L += [f"- **{c.id}** ({c.kind}, {c.confidence}): {c.description}" for c in r.conflicts] or ["None found."]
    if r.warnings:
        L += ["", "## Warnings", ""] + [f"- {w}" for w in r.warnings]
    return "\n".join(L) + "\n"


def render_document_text(result: IngestResult) -> str:
    """All content as text (used for --reference material)."""
    out = []
    for d in result.documents:
        out.append(f"## {d.name}")
        for it in result.items:
            if it.doc == d.name:
                out.append(IngestPipeline._fmt_item(it))
    return "\n".join(out)
