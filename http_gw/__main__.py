"""Uvicorn entrypoint for the HTTP gateway."""

import uvicorn


def main() -> None:
    uvicorn.run("http_gw.app:app", host="0.0.0.0", port=8080, reload=False)


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    main()
