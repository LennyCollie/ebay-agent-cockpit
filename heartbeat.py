import os, ssl, smtplib, socket, datetime, requests

def send_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("FROM_EMAIL") or user
    to_email   = os.getenv("EMAIL_TO") or from_email
    if not all([host, port, user, pwd, from_email, to_email]):
        print("[heartbeat] missing SMTP config; skip")
        return
    msg = f"From: {from_email}\r\nTo: {to_email}\r\nSubject: {subject}\r\n\r\n{body}\r\n"
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=25) as s:
            s.login(user, pwd); s.sendmail(from_email, [to_email], msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as s:
            s.ehlo(); s.starttls(context=ctx); s.ehlo()
            s.login(user, pwd); s.sendmail(from_email, [to_email], msg)

def check_http(url: str) -> str:
    try:
        r = requests.get(url, timeout=10)
        return f"{r.status_code} {r.reason}"
    except Exception as e:
        return f"ERROR: {e}"

if __name__ == "__main__":
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    svc  = os.getenv("RENDER_SERVICE_NAME", "unknown-service")
    host = socket.gethostname()
    commit = os.getenv("RENDER_GIT_COMMIT", "")[:7] or "n/a"
    # Webservice Health (falls gesetzt)
    health_url = os.getenv("HEALTH_URL", "https://ebay-agent-cockpit.onrender.com/healthz")
    http_status = check_http(health_url)

    body = (
        f"✅ Heartbeat OK\n"
        f"- Time:   {now}\n"
        f"- Service:{svc}\n"
        f"- Host:   {host}\n"
        f"- Commit: {commit}\n"
        f"- Health: {health_url} -> {http_status}\n"
    )
    send_email(subject="ebay-agent: Daily heartbeat ✔", body=body)
    print("[heartbeat] sent")