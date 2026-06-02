# PRD 02: Checkout Flow

## Problem
Users need a reliable **checkout flow** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform checkout flow successfully (happy path).
- As a user, I see a clear error when checkout flow fails due to invalid input.
- As a user, my checkout flow action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
