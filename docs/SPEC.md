Below is a detailed, build-ready specification for a **Gellish Translation Agent** (English → Gellish), designed for Linux (WSL/Ubuntu) and intended to scale from “MVP translator” to “semi-autonomous document formalisation system.” It is written to be directly consumable by a strong coding agent (Codex/Claude). It assumes your environment is already set up (Postgres + Python + optional pgvector, FastAPI, Redis/Celery, etc.).

---

# 1. Project overview

## 1.1 Goal

Build an agent that ingests unstructured documents (plain text, web pages, LLM output, Word, PDF), guides a user through translation into **Gellish** (formal semantic expressions), and continuously improves automation through:

* translation memory,
* learned heuristics,
* term/UID governance,
* proactive dictionary extension (including consulting external LLMs),
* human-in-the-loop review when ambiguity persists.

## 1.2 Non-goals (for MVP)

* Full bidirectional Gellish editing environment (beyond minimal UI for review).
* Full OWL/RDF export (can be added later).
* Full Datalog compilation (explicitly deferred for now).
* “Perfect” NLP understanding of arbitrary prose—focus on controlled incremental improvement.

## 1.3 Key design principles

1. **Deterministic outputs**: LLM produces structured intermediate representation (IR); rendering to Gellish is deterministic.
2. **Auditability & provenance**: Every extracted statement has source offsets, confidence, and decision trace.
3. **UID governance first**: Missing UIDs are handled explicitly via provisional concepts; merges are curated.
4. **Small stable relation set**: Start with a constrained set of relation types; expand deliberately.
5. **Progressive automation**: Start guided; add auto-accept thresholds and background improvements.

---

# 2. User experience and workflow

## 2.1 Primary user story

1. User opens web UI.
2. User loads a document (upload file or provide URL or paste text).
3. System extracts text and segments it (sections → paragraphs → sentences).
4. UI presents a guided translation flow:

   * sentence-by-sentence view,
   * candidate Gellish expressions for each sentence,
   * term mappings (surface term → concept UID),
   * relation choices and qualifiers.
5. Agent proposes dictionary extensions when terms/relations are missing or ambiguous.
6. User approves, edits, merges, or rejects suggestions.
7. Agent writes final Gellish expressions to the DB and export formats (CSV/Excel-like).
8. Translation memory is updated to improve future automation.

## 2.2 Secondary user stories

* Review and resolve “provisional concepts” backlog.
* Search dictionary by label/synonyms; merge concepts.
* Re-run translation after dictionary changes (incremental).
* Export translated knowledge for downstream pipelines.

---

# 3. Input document types and ingestion

## 3.1 Supported input types

MVP must support:

* Plain text files (.txt)
* Paste-in text (ASCII/UTF-8)
* URL web page ingestion (HTML to text)

Phase 2:

* PDF (text extraction first; OCR optional)
* Word (.docx)

Phase 3:

* “LLM output” structured text formats (Markdown, JSON) treated as text with layout hints.

## 3.2 Ingestion requirements

* Every document is stored with metadata:

  * original filename/URL,
  * MIME type,
  * upload time,
  * content hash,
  * user-provided tags.
* Text extraction produces:

  * raw text,
  * normalized text,
  * sentence segmentation,
  * mapping from sentences back to document offsets (char ranges and/or page numbers for PDF).

## 3.3 Extraction tools

* `.txt` and pasted: direct.
* Web pages: `trafilatura` or `readability-lxml` to extract main text.
* `.docx`: `python-docx`.
* PDF: `pypdf` / `pdfminer.six`; fallback OCR via `tesseract` for scanned pages.

---

# 4. Output representation: Gellish

## 4.1 Gellish representation format

Internally store expressions as structured records; provide export as:

* “Gellish triple table” (Subject UID, Relation UID, Object UID + labels)
* optional qualifiers table (time, modality, source, confidence)
* optional Excel/CSV suitable for import into other Gellish tools

## 4.2 Expression model

Minimum expression fields:

* `expression_id`
* `subject` (concept UID)
* `relation_type` (relation UID)
* `object` (concept UID or literal value)
* `qualifiers` (JSON: time interval, location, units, modality, negation, “according to”)
* `provenance` (document_id, sentence_id, char spans)
* `confidence` (0..1)
* `status` (`proposed|accepted|rejected|superseded`)

## 4.3 Controlled relation set (initial)

Include at least:

* `rel:is_a` (subtype/classification)
* `rel:has_part`
* `rel:part_of` (optional; derivable inverse if you support it)
* `rel:located_in`
* `rel:located_on`
* `rel:causes`
* `rel:used_for` (function / purpose)
* `rel:has_property`
* `rel:has_value` (property-value)
* `rel:has_unit`
* `rel:has_role` (optional)
* `rel:has_name` / `rel:has_alias` (for alternate labels)
* `rel:asserted_by` / `rel:according_to` (provenance/discourse; optional but helpful)

Note: Keep the set small at first; relations are a major source of semantic drift.

---

# 5. Intermediate Representation (IR) contract (LLM output)

## 5.1 Why IR

LLM should not output “final Gellish” directly. It must output a strict JSON IR that is:

* easy to validate,
* stable across prompt versions,
* deterministic to render into Gellish statements.

## 5.2 IR schema (JSON)

For each sentence:

```json
{
  "sentence_id": "doc123:s45",
  "text": "A lever on the side of the toaster is pressed down.",
  "entities": [
    {
      "span": [2, 7],
      "surface": "lever",
      "candidate_concepts": [
        {"uid": "concept:lever", "score": 0.82},
        {"uid": "provisional:doc123:lever:001", "score": 0.55}
      ],
      "chosen_uid": "concept:lever",
      "needs_review": false
    }
  ],
  "relations": [
    {
      "subject_surface": "lever",
      "subject_uid": "concept:lever",
      "relation_uid": "rel:located_on",
      "object_surface": "side of the toaster",
      "object_uid": "concept:toaster_side",
      "qualifiers": {"direction": "side"},
      "confidence": 0.74,
      "needs_review": true,
      "notes": "Object phrase may need decomposition."
    }
  ],
  "open_terms": [
    {
      "surface": "toaster_side",
      "suggested_parent": "concept:side",
      "reason": "compound noun; likely part of toaster"
    }
  ]
}
```

## 5.3 LLM constraints

* Must emit valid JSON.
* Must pick relations from the allowed set.
* Must not invent “magic” UIDs; if unknown, use `provisional:*`.
* Must include `needs_review` for uncertain items.
* Must include confidence scores with defensible heuristics.

---

# 6. Dictionary / UID governance

## 6.1 Dictionary structure

Concepts:

* UID
* preferred label
* definition
* status: active/provisional/deprecated
* parent concept UID(s) (taxonomy)
* synonyms/aliases (terms)
* source/provenance of definition and creation

Relations:

* relation UID
* preferred label
* definition
* domain/range constraints (optional but recommended later)
* inverse relation UID (optional)

## 6.2 UID generation rules

* Permanent UIDs:

  * namespace-based: `org:concept:<increment>` or `energyOS:concept:<id>`
  * stored centrally in DB with uniqueness constraints
* Provisional UIDs:

  * `provisional:<docid>:<termhash>` or `provisional:<timestamp>:<rand>`
  * always marked provisional, queued for review/merge

## 6.3 Concept lookup

Lookup must include:

* exact label match (normalized)
* synonym match
* fuzzy match (rapidfuzz)
* embedding match (pgvector optional)
* context-aware match: look at nearby words / sentence role / parent hints

Return ranked candidates with evidence.

## 6.4 Merge workflow

User can merge provisional into an existing concept:

* move all expressions referencing provisional UID to canonical UID
* retain alias labels and provenance
* mark provisional deprecated or merged

---

# 7. Agent behaviour: automation, learning, and prompting

## 7.1 Translation process stages

1. **Parse & segment**
2. **Entity identification**
3. **Relation extraction** → candidate Gellish triples
4. **Concept mapping** (UID linking)
5. **Qualification** (time, modality, quantities)
6. **Validation** (schema checks)
7. **User review** for low-confidence items
8. **Commit** accepted statements
9. **Update translation memory** + heuristics

## 7.2 Translation memory

Store mappings:

* surface phrase → concept UID (with context features)
* relation patterns:

  * dependency parse patterns
  * n-grams around relation verbs
  * examples of accepted triples

Use memory to auto-accept:

* if mapping confidence exceeds threshold and no rule violations.

## 7.3 Heuristic rules storage

Represent heuristics as data, not code:

* YAML/JSON rule pack:

  * triggers (regex / parse patterns)
  * output templates (relation UID + argument slots)
  * constraints
  * confidence prior
  * examples / tests

Agent updates rule pack:

* by adding new patterns from accepted user corrections.
* by proposing candidate generalisations (requires review).

## 7.4 When to prompt the user

Prompt user when:

* no acceptable concept candidate exists,
* multiple candidates are close (ambiguous),
* relation type is uncertain,
* statement requires decomposition (n-ary or complex structure),
* proposed dictionary extension would introduce conflicts.

Prompts must be targeted:

* ask a multiple-choice question with top candidates
* provide a recommended default with explanation
* allow “create new concept UID” action

---

# 8. Proactive dictionary extension and external consultation

## 8.1 Goals

When encountering unknown term/sense, the agent should:

* search existing local dictionary
* attempt decomposition (compound splitting)
* propose parent concept and definition
* consult external LLM(s) to check whether:

  * term already exists in known Gellish resources (if accessible)
  * term is a synonym of an existing concept
  * term introduces a new sense requiring a new concept

## 8.2 External consultation design

Important: external LLM responses are advisory.
Workflow:

1. Retrieve internal candidates (lexical + embedding).

2. If below threshold, call “LLM advisor” with:

   * the sentence context
   * your controlled relation set
   * top internal candidates
   * instruction to return:

     * candidate sense grouping,
     * suggested parent,
     * suggested short definition,
     * suggested synonyms,
     * whether “new UID likely needed”.

3. Validate advisor output:

   * reject if it proposes unknown relation types,
   * reject if it conflicts with existing taxonomy constraints.

4. If still uncertain → prompt user.

## 8.3 “Consult chatbots on the web”

Implement as:

* pluggable “advisor providers”:

  * OpenAI model provider
  * Anthropic provider
  * (optional) web-based retrieval provider (via standard web search APIs if you later integrate)
* In MVP, implement at least one provider with local config.

All advisor calls must be stored:

* prompt,
* response,
* timestamp,
* model name,
* decision taken.

---

# 9. Web UI specification

## 9.1 UI pages

1. **Dashboard**

   * recent documents
   * pending reviews (provisional terms, ambiguous mappings)
2. **New Document**

   * upload file / paste text / URL input
   * choose extraction options (PDF OCR yes/no)
3. **Translation Workspace**

   * left pane: document text with sentence selection
   * middle: proposed entities + relations (IR)
   * right pane: dictionary panel (concept lookup, create concept, merge)
   * actions:

     * accept statement
     * edit statement (change relation, subject/object)
     * split statement
     * reject statement
   * show confidence and rationale
4. **Dictionary Manager**

   * search concepts
   * view/edit concept, synonyms, parents
   * merge tool
5. **Review Queue**

   * list unresolved concepts/relations
   * suggested actions and advisor notes

## 9.2 UI technology

* Backend: FastAPI
* Frontend: simple React/Vite or server-rendered HTML for MVP
* Authentication: local (single user) initially; add multi-user later.

---

# 10. Backend services and modules

## 10.1 Services

* `ingest_service`: converts input → text + segments
* `nlp_service`: tokenization, NER-ish hints, dependency parse (spaCy)
* `translation_service`: calls LLM to generate IR
* `mapping_service`: maps surface terms to concept UIDs (dictionary lookup)
* `render_service`: IR → Gellish expressions
* `validation_service`: type/relation checks; duplicates; contradictions (light)
* `advisor_service`: consult external LLM provider(s)
* `review_service`: queue and manage unresolved items

## 10.2 Job orchestration

* For small usage: synchronous in API request.
* For scaling: Celery tasks:

  * `ingest_document`
  * `translate_document`
  * `update_embeddings`
  * `reprocess_document_after_dictionary_change`

---

# 11. Storage schema requirements (Postgres)

Minimum tables:

* `document` (id, source, mime, hash, metadata)
* `document_text` (doc_id, extracted_text, normalized_text)
* `sentence` (sentence_id, doc_id, text, char_start, char_end, page_no)
* `concept` (uid, label, definition, status, created_at)
* `term` (concept_uid, label, label_norm, lang, preferred)
* `relation_type` (uid, label, definition, status)
* `expression` (id, subj_uid, rel_uid, obj_uid/literal, qualifiers_json, provenance, confidence, status)
* `translation_run` (id, doc_id, version, model, params, created_at)
* `advisor_call` (id, run_id, request_json, response_json, decision_json)
* `review_queue` (id, item_type, item_ref, reason, status, assigned_to)

Optional:

* embeddings tables (pgvector)
* audit log table

---

# 12. Validation and quality controls

## 12.1 Validation checks

* relation UID exists in relation_type
* subject/object UIDs exist or are provisional (provisional allowed)
* forbidden relations not used
* confidence thresholds respected for auto-accept
* duplicate expressions detection (exact duplicates)
* basic contradiction checks (optional early):

  * same subject has two different `is_a` parents with disjointness (only if you model disjointness)

## 12.2 Regression tests

Create a small “gold” corpus:

* 50–200 sentences
* expected IR + expected final expressions
* run in CI on every update to prompts/rules/dictionary

---

# 13. Initial configuration / bootstrap process

## 13.1 Purpose

Ensure the agent can translate simple documents immediately without the user having to build a dictionary from scratch.

## 13.2 Bootstrap wizard requirements (UI + CLI)

* create namespace settings:

  * org prefix
  * UID pattern
* install base relation set (as above)
* load a **concise starter dictionary**, including:

  * generic upper ontology: object, physical object, process, event, property, location, agent, document, device, component
  * basic relations concept entries where needed
  * optional domain mini-dictionary: “toaster”, “lever”, “button”, “sensor”, “timer”, etc. (sample domain pack)

## 13.3 Starter dictionary format

Store as CSV or YAML:

* `concepts.csv`: uid, preferred_label, definition, status, parent_uid
* `terms.csv`: concept_uid, label, lang, is_preferred
* `relations.csv`: rel_uid, label, definition, (domain/range optional)

Agent must provide CLI command:

* `gellish-agent init --load starter_pack/basic.yaml`

---

# 14. Prompting and LLM integration details

## 14.1 Prompt templates

* `IR_GENERATION_PROMPT`: takes sentence + context + allowed relations + top concept candidates
* `TERM_DISAMBIGUATION_PROMPT`: takes term + sentence contexts + candidate concepts
* `NEW_CONCEPT_PROPOSAL_PROMPT`: asks for definition, parent class, synonyms

All prompts must:

* require JSON-only output
* include schema
* include relation whitelist
* forbid creating non-provisional UIDs

## 14.2 Configurable model providers

* `OpenAIProvider`
* `AnthropicProvider`
* future: local LLM provider (LM Studio / vLLM)

Config via `.env` / YAML.

---

# 15. Deliverables and milestones

## MVP milestone (works end-to-end)

* Web UI: upload/paste/URL, translate workspace, accept/reject statements
* Text extraction: txt + web pages
* IR generation via one LLM provider
* Dictionary lookup + provisional UID creation
* Store expressions + export to CSV
* Review queue for provisional concepts
* Bootstrap wizard loads starter pack

## Phase 2

* PDF + docx ingestion
* Embedding-based concept retrieval (pgvector)
* More relation types + qualifiers (time/units/modality)
* Background jobs + batch ingestion
* Concept merge UI + incremental reprocessing

## Phase 3

* Multi-document coreference improvements
* Auto-suggest rules/heuristics updates from accepted edits
* Large-scale ingestion pipeline
* Advanced QA metrics dashboards

---

# 16. Acceptance criteria (MVP)

1. User can ingest at least: txt + URL web page.
2. System segments into sentences and displays them.
3. For each sentence, system proposes Gellish expressions (triples) using IR.
4. Unknown terms create provisional concepts; these appear in review queue.
5. User can approve/edit mappings and relations.
6. Accepted expressions are stored with provenance and exported as CSV.
7. Agent remembers mappings and reuses them in later documents (translation memory).
8. System can run entirely locally on Ubuntu/WSL.

---

# 17. Notes for the coding agent

* Prioritise correctness, determinism, and auditability over “maximum automation.”
* Keep the relation set small and enforced by validation.
* Make all “learning” explicit: rules and translation memory must be inspectable and versioned.
* Treat external LLMs as advisors with validation gates.
* Ensure all DB writes are transactional and idempotent for re-runs.

---

