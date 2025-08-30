import os, smtplib, ssl
from dotenv import load_dotenv

load_dotenv('.env.local', override=True)
load_dotenv()

host = os.getenv('SMTP_HOST')
port = int(os.getenv('SMTP_PORT','0'))
user = os.getenv('SMTP_USER')
pwd  = os.getenv('SMTP_PASS')

use_ssl = (os.getenv('SMTP_USE_SSL','0').lower() in ('1','true','yes','on'))
use_tls = (os.getenv('SMTP_USE_TLS','0').lower() in ('1','true','yes','on'))

print('TRY', host, port, 'SSL=',use_ssl, 'TLS=',use_tls, 'USER=',user)

try:
    if use_ssl:
        s = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15)
    else:
        s = smtplib.SMTP(host, port, timeout=15)
        if use_tls:
            s.starttls(context=ssl.create_default_context())
    s.login(user, pwd)
    print('LOGIN OK')
    s.quit()
except Exception as e:
    print('LOGIN FAIL:', e)
