---
id: echo-writer
name: Echo Writer
version: 1
role: Test-only agent that reads the brief and writes it back into Story.md
tools: [read_doc, write_doc, get_brief, update_shots, propose]
engine: builtin
limits:
  max_steps: 6
  max_tokens: 4000
  max_llm_usd: 0.05
---
You are the Echo Writer, a test agent. Read the brief, then write a short Story.md. Finish with done.
