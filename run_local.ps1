Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
$env:FLASK_APP="app.py"
$env:FLASK_DEBUG="0"
python -m flask run -h 127.0.0.1 -p 5000