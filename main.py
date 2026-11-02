"""Inicializa a API HTTP.

Uso, a partir da raiz do projeto: python main.py
"""

from pathlib import Path

import uvicorn


def main() -> None:
    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir=str(Path(__file__).resolve().parent),
    )


if __name__ == "__main__":
    main()
