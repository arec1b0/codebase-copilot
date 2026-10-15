# Prompt card

| Field | Value |
| --- | --- |
| Version | `grounded-codebase-v2` |
| Implementation | `app/prompt.py`; `ModelAnswer` in `app/contracts.py` |
| Identity | SHA-256 over instructions, schema, format marker, bounds, and generation settings |
| Input | Question and ranked labeled source records with locations/text |
| Output | English statements with source IDs, abstention flag, and reason |

Every query response records the computed static prompt hash. Dynamic questions
and source text are not part of this hash. Corpus/index versions and Git commit
identify the snapshot; evaluations must retain their input questions separately.

Instructions require supplied evidence for each statement and abstention for
missing evidence. Inline markers are rendered by the API from validated statement
source IDs. The model does not maintain a second citation representation. User
messages use JSON; questions and sources are untrusted. There is no tool interface.

The service validates statement labels and renders canonical citations. It cannot
establish whether every claim has adequate evidence. Empty context, undeclared
labels, citation rendering, and abstentions are tested offline. Faithfulness and
injection resilience require labeled and adversarial evaluations.
