# Manual Parser Domain Context

## Purpose

This bounded context turns an uploaded XCMG company manual (`DOC`, `DOCX`, or
`PDF`) into one evidence-backed document tree. It is a parser product, not a
RAG ingestion pipeline and not a parser comparison workbench.

## Ubiquitous language

- **Source document**: the exact uploaded file. It is immutable within a job.
- **Visual document**: the PDF used to render pages and run DeepDOC. Office
  documents are converted to this representation by LibreOffice.
- **Native structure**: semantic facts read directly from DOCX OOXML, such as
  paragraph styles, heading levels, table cells, merges, and image relations.
- **Source order**: the monotonic order of body objects in OOXML. It remains
  authoritative when a block has not yet been placed on a physical page.
- **Page**: a rendered visual page with width and height in PDF points.
- **Physical page**: the one-based page position in the uploaded PDF. It is
  stable even when the manual prints Roman numerals or restarts numbering.
- **Printed page label**: the page identifier visible to a reader, such as
  `IV` or `1`. It is metadata, never body text.
- **Block**: the smallest ordered unit exposed by the product: paragraph,
  heading, table, figure, caption, warning, equation, or page furniture.
- **Reading order**: one global sequence formed after every text and visual
  object has been placed back onto its physical page.
- **Section**: a heading and all content governed by it until the next heading
  of equal or higher level, including content that continues onto later pages.
- **TOC entry**: one table-of-contents row containing a title, printed target
  page label, hierarchy level, and optional link to its matching section.
- **TOC root**: the single navigation-only `目录` node governing every TOC
  entry, including entries on continuation pages. It never belongs to a body
  section and is not technical question-answering evidence.
- **Printed-page target**: a TOC entry's printed label plus its resolution
  status, optional physical page, and optional matching heading. Printed-page
  resolution happens before title matching.
- **List**: an ordered or unordered group whose items share an identity and
  indentation hierarchy; it is not a collection of unrelated paragraphs.
- **List item**: one member of a list with a marker, nesting level, and content.
- **Safety notice**: one safety-semantic object containing its symbol, level,
  label, and complete explanatory body. _Avoid_: an isolated warning word.
- **Table grid**: the row/column/cell structure of a table, including headers,
  spans, and the original cell coordinates.
- **Figure asset**: the retrievable image crop for a figure, with page-local
  coordinates and optional caption or description.
- **Semantic symbol**: a small visual sign whose shape carries business
  meaning, such as safety, weight, torque, adhesive, or coolant.
- **Evidence**: a claim about where a block came from (`deepdoc`, `ooxml`,
  `pdf_native`, `pdf_native_table`, or `region_vlm`) and its confidence. Later
  stages never erase earlier evidence.
- **Region image**: a crop associated with a visual block. The fixed region VLM
  receives crops rather than an unconstrained full manual.
- **Fusion**: reconciliation that treats OOXML/native text as semantic truth and
  DeepDOC as page/layout evidence. A VLM result that changes key anchors is
  rejected.
- **Replacement fusion**: native text first improves or replaces the
  spatially corresponding visual block. A new block is added only when no
  corresponding block exists.
- **Visual fallback**: a rendered-page block retained because no OOXML or
  native-text block demonstrably covers its content. It prevents fusion from
  deleting content that exists only in the visual representation.
- **Anchor**: a business-sensitive token such as a model, fault code, pin,
  number, or number-with-unit.
- **Document tree**: headings and their descendant blocks. This is distinct
  from flat reading order.
- **Table intent**: `data_table`, `layout_table`, `layout_container`,
  `warning_container`, or `image_container`.
- **Table integrity**: `verified`, `review_required`, or `unsafe`. Only native
  OOXML or a conservatively recovered PDF grid can be `verified`; visual data
  tables are never silently treated as verified.
- **Table quarantine**: exclusion of an unsafe table's cell values from trusted
  text output while retaining its visual region and evidence for review.
- **Continuation**: a table on the next page that belongs to the same logical
  table. It points to the first table through `continuation_of`.
- **Issue**: a machine-generated request for review; an issue does not make the
  whole job fail.
- **Job**: one asynchronous, durable parsing execution and all its artifacts.
- **Trusted Markdown**: text intended for downstream indexing; it may contain
  verified tables and explicit review warnings, but never unsafe table values.
- **Portable result package**: the Markdown, full evidence JSON, and referenced
  figure assets needed to inspect a result without the live parser service.

## Invariants

1. There is one automatic pipeline and one final result schema.
2. The source document is never modified.
3. Every accepted VLM replacement preserves at least 80% of source anchors.
4. Coordinates always use page-local PDF points `[x0, y0, x1, y1]`.
5. DOC/DOCX visual placement comes from the rendered PDF; semantic table and
   heading structure comes from OOXML whenever available.
6. A parser-stage failure may degrade a region, but may not silently invent
   missing business data.
7. A physical page with low native-text or numeric coverage produces an error
   issue even when the surviving output looks fluent.
8. Page furniture and printed page labels never enter the body Markdown.
9. Reading order is page-local and column-aware; blocks without coordinates are
   interpolated from native source order instead of being appended globally.
10. A table with `qa_eligible: false` is evidence for review, not a trusted
    source for technical question answering.
11. Reconstructing a TOC page may replace a source region only when its content
    is covered by the reconstructed rows; unresolved source regions are kept.
12. Unsafe table values never enter Trusted Markdown.
13. TOC parentage and section paths are owned by the TOC root and are never
    overwritten by the body heading tree.
14. A TOC target is title-matched only on its resolved physical page or an
    adjacent page; an out-of-range printed label never receives a global fuzzy
    heading link.
15. Native text recovery replaces or merges a corresponding visual block
    before adding a new block, so one visual region cannot yield duplicate
    cover titles or paragraphs.
16. An unplaced OOXML block retains Source order and is positioned only by
    monotonic evidence from surrounding placed blocks; it is never assigned
    to physical page 1 by default.
17. Fusion may suppress a rendered-page text block only when native evidence
    demonstrably covers it; otherwise it remains as a Visual fallback.
