"""WSGI entrypoint for Azure startup command compatibility."""

from app import app


if __name__ == "__main__":
    app.run()
