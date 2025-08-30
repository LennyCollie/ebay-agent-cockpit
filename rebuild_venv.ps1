Set-Location $PSScriptRoot
Remove-Item -Recurse -Force .\venv -ErrorAction SilentlyContinue
py -3 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# moderne, konfliktarme Basis
python -m pip install Flask==3.0.3 Werkzeug>=3.0.1 gunicorn==21.2.0 `
                        python-dotenv==1.0.1 requests==2.32.3 stripe==12.5.0