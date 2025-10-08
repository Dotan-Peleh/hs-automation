# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Unreadable ticket detection**: New `unreadable` intent for incomprehensible/gibberish messages
- **Slack alert tags**: Special visual tags for different ticket types:
  - 🚨 `DELETE_REQUEST` for account deletion requests
  - 📭 `EMPTY_TICKET` for tickets with no real user message
  - ❓ `UNREADABLE` for incomprehensible/gibberish content
- **Severity overrides**: Empty and unreadable tickets are now forced to LOW severity to prevent false alarms

### Changed
- LLM system prompt updated to recognize unreadable messages
- Severity bucketing now includes special handling for `incomplete_ticket` and `unreadable` intents
- Slack alerts now only sent if agent hasn't replied yet (prevents spam)

### Fixed
- Prevented unreadable/gibberish tickets from being classified as critical or high severity
- Improved empty ticket detection to avoid hallucinations

## Previous Changes
See git history for earlier modifications.

