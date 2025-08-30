import os
from dotenv import load_dotenv

# .env.local und .env laden (wie in deiner App)
load_dotenv('.env.local', override=True)
load_dotenv()

keys = ['SMTP_HOST','SMTP_PORT','SMTP_USE_TLS','SMTP_USE_SSL','SMTP_USER','SMTP_FROM']
for k in keys:
    print(f'{k} = {os.getenv(k)}')
