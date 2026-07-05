# Suitest Testing Report

## 1️⃣ Document Metadata
- **Project:** demo-shop
- **Mode:** frontend
- **Base URL:** http://localhost:3000
- **Date:** 2026-07-06
- **Prepared by:** Suitest
- **Summary:** 2 tests — 1 passed, 1 failed, 0 skipped, 0 error (130 ms)
- **Readiness:** ready (200 at /)

## 2️⃣ Requirement Validation Summary

### TC001 open home page
- **Status:** ✅ Passed
- **Description:** smoke
- **Duration:** 68 ms
- **Automation:** `TC001_open_home.py`

### TC002 checkout submit enabled
- **Status:** ❌ Failed
- **Description:** submit checkout
- **Duration:** 62 ms
- **Automation:** `TC002_checkout_submit.py`
- **Error:**
```
Traceback (most recent call last):
  File "frontend/TC002_checkout_submit.py", line 8, in <module>
    test()
  File "frontend/TC002_checkout_submit.py", line 6, in test
    raise AssertionError(f'TimeoutError: waiting for selector {selector} to be enabled (30000ms exceeded)')
AssertionError: TimeoutError: waiting for selector #submit-btn to be enabled (30000ms exceeded)
```

## 3️⃣ Coverage & Matching Metrics
- Pass rate: **50%** (1/2)

| Outcome | Count |
|---------|-------|
| FAILED | 1 |
| PASSED | 1 |

## 4️⃣ Key Gaps / Risks
- TC002 checkout submit enabled: AssertionError: TimeoutError: waiting for selector #submit-btn to be enabled (30000ms exceeded)
