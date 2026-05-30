"""Runner-side event handler hooks.

Each module exposes a single async function that the orchestrator
(``suitest_runner.jobs.run_test_case``) calls when a step transitions to a
notable outcome (FAIL, ERROR, PASS-after-retry). Handlers MUST NOT raise into
the orchestrator — every handler wraps its real work in try/except so a
broken downstream pipeline (defect filer DB outage, slack adapter down) can
never poison the run record.
"""
