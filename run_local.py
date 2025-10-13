# run_local.py – universeller Starter für deine Flask-App
from __future__ import annotations


def _get_app():
    # 1) Versuch: app.py enthält eine Variable "app"
    try:
        from app import app as application  # type: ignore

        return application
    except Exception:
        pass
    # 2) Versuch: app.py stellt eine Factory "create_app" bereit
    try:
        from app import create_app  # type: ignore

        return create_app()
    except Exception as e:
        raise RuntimeError(
            "Konnte die Flask-App nicht finden. "
            "Erwarte entweder 'app' oder 'create_app()' in app.py."
        ) from e


if __name__ == "__main__":
    application = _get_app()
    application.run(host="127.0.0.1", port=5000, debug=True)
