# Decisions

- Prioritized analysis depth over immediate code changes because the user requested a full, in-depth study and gap assessment.
- Treated `test_llm_turn.py` as true model-in-the-loop coverage, but explicitly classified it as actor-level rather than full runtime end-to-end due direct `_execute_turn(...)` invocation.
- Collected both default-suite evidence and real-vLLM execution evidence to avoid theoretical conclusions about LLM-path coverage.
- Framed recommendations around acceptance-level runtime tests as the highest ROI for closing real-world confidence gaps.
