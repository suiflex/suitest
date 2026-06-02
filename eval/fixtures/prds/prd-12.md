# PRD 12: Two-Factor Auth

## Problem
Users need a reliable **two-factor auth** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform two-factor auth successfully (happy path).
- As a user, I see a clear error when two-factor auth fails due to invalid input.
- As a user, my two-factor auth action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
