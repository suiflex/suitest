# PRD 07: Apply Coupon

## Problem
Users need a reliable **apply coupon** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform apply coupon successfully (happy path).
- As a user, I see a clear error when apply coupon fails due to invalid input.
- As a user, my apply coupon action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
