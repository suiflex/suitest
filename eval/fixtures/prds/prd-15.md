# PRD 15: Refund Request

## Problem
Users need a reliable **refund request** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform refund request successfully (happy path).
- As a user, I see a clear error when refund request fails due to invalid input.
- As a user, my refund request action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
