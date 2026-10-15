# Generation model card

| Field | Value |
| --- | --- |
| Model selector | `qwen2.5-coder:3b` |
| Serving | Local Ollama, native HTTP `/api/chat` |
| Revision | Actual Ollama model digest captured at startup and returned per response |
| Backend | Actual Ollama version returned per response |
| Intended use | English explanations of retrieved code from a pinned Git snapshot |
| Settings | Temperature 0, seed 42, context 8,192, output limit 512 tokens |
| Inputs | Question up to 1,024 characters; prompt content up to 6,000 UTF-8 bytes |
| Output | Up to three sourced statements, abstention flag, and abstention reason |

The model tag is mutable. The API pins its observed digest for the process lifetime.
Re-downloading a model or updating Ollama can require an API restart. Retain the
returned digest and backend version when comparing results.

The 3B model was selected for the local first implementation. No minimum RAM,
throughput, multilingual quality, or correctness level has been established on
the user's machine. Loading and CPU inference can be slow; bounded context can
omit dependencies. Valid citation labels do not establish factual faithfulness.
Deterministic settings do not guarantee identical outputs.

Adapter and service checks passed with synthetic model responses. Real Ollama and
Windows operation require the Step 5 live acceptance run. No quality score is
claimed. Upstream model information and licensing:
https://ollama.com/library/qwen2.5-coder:3b

Embedding asset identities remain in the retrieval manifest independently of this
generation model.

The user accepted Step 5 on Windows with actual model revision
`sha256:f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225`.
The latest reported single Counter request had model-side TTFT 12.86 seconds and
total service time 16.29 seconds. These are observations, not percentiles or a
capacity claim. Step 6 records its actual current revision and measurements in
a separate 30-question baseline; local-judge scores remain uncalibrated.
