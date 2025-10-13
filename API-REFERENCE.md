# API Reference

## Ticket Intent Classification

The LLM enrichment system classifies tickets into the following intents:

### Valid Intents

| Intent | Description | Severity Handling | Slack Alert Tag |
|--------|-------------|-------------------|-----------------|
| `bug_report` | Bugs/glitches that don't crash the app | Standard severity rules | - |
| `crash_report` | App crashes/force closes | Always HIGH | - |
| `billing_issue` | Payment/purchase/refund problems | At least MEDIUM | - |
| `delete_account` | User wants to delete their account or cancel a subscription | Standard severity rules | 🚨 DELETE_REQUEST |
| `lost_progress` | Save data lost | Always HIGH | - |
| `feedback` | General feedback/compliments | Standard severity rules | - |
| `question` | How-to questions | Standard severity rules | - |
| `incomplete_ticket` | Empty tickets (no real user message) | **Forced to LOW** | 📭 EMPTY_TICKET |
| `unreadable` | Incomprehensible/gibberish messages | **Forced to LOW** | ❓ UNREADABLE |

### Severity Rules

1. **Standard Computation**: `engine/severity.py` computes score based on:
   - Crash keywords
   - Progress loss indicators
   - Payment/billing terms
   - Entity extraction (version, platform, level)

2. **Forced Overrides** (always applied):
   - `crash_report` → **HIGH**
   - `lost_progress` → **HIGH**
   - `billing_issue` → At least **MEDIUM**
   - `incomplete_ticket` → **LOW** (override)
   - `unreadable` → **LOW** (override)

3. **Standard Bucketization** (score-based):
   - Score ≥ 50 → HIGH
   - Score ≥ 30 → MEDIUM
   - Score < 30 → LOW

### Slack Alert Behavior

Alerts are sent **only if the agent hasn't replied yet** to prevent spam.

Special tags are added to Slack alerts based on intent:
- 🚨 **DELETE_REQUEST**: Urgent account deletion requests
- 📭 **EMPTY_TICKET**: No real user message provided
- ❓ **UNREADABLE**: Incomprehensible or gibberish content

### Empty Ticket Detection

The system aggressively detects empty tickets to prevent LLM hallucinations:

1. **Pre-processing**: Removes all template patterns (User ID, OS, Device, HTML, etc.)
2. **Threshold**: If less than 40 characters remain after cleaning → `incomplete_ticket`
3. **Response**: Returns pre-defined empty ticket metadata without calling LLM

### Configuration

Set these environment variables to enable features:

```bash
# LLM Enrichment
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_MODEL=claude-3-haiku-20240307  # or claude-3-5-sonnet-20241022

# Slack Alerts
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_DEFAULT_CHANNEL_ID=C...

# Help Scout Webhook
HS_WEBHOOK_SECRET=...
```

## Webhook Flow

1. **Help Scout sends webhook** → `POST /helpscout/webhook`
2. **Fetch conversation** via Help Scout API
3. **Check if agent replied** → Skip Slack if yes
4. **Enrich with LLM** → Classify intent, extract entities
5. **Compute severity** → Apply forced overrides if needed
6. **Send Slack alert** → Include special tags
7. **Save to database** → Cache enrichment results

## Testing

Test webhook processing manually:
```bash
curl -X POST http://localhost:8080/admin/test-webhook?conv_id=12345
```

Test Slack alerts:
```bash
curl http://localhost:8080/admin/test-slack
```

