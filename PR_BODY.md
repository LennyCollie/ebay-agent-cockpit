# docs: Add RUNBOOK & Übergabeprotokoll

**Scope**
- Add `RUNBOOK.md` (mini-runbook, stable: mails running)
- Add `UEBERGABE_PROTOKOLL.md` (handover checklist)
- Add `.env.local.example` (non-secret example env)

**Context**
- Branch: `staging` (connected to Render)
- Service URL: https://ebay-agent-heartbeat.onrender.com
- Health: `/healthz` • Debug: `/_debug/ebay`, `/_debug/amazon`, `/debug`

**Checklist**
- [ ] Render env contains SMTP (Gmail: port 587, TLS=1, SSL=0)
- [ ] `AGENT_TRIGGER_TOKEN` set on Render
- [ ] Tag stable release (e.g., `v0.9.0`) post-merge

**Smoke after merge**
- `/healthz` returns OK
- `/_debug/ebay` shows `configured=true`, `token_valid_for_s>0`
- `POST /alerts/send-now` logs `[mail] sent via ...`

---
_This PR is documentation-only._