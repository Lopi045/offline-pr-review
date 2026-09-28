"""Entry point. Run: `python app.py` or `python app.py <port>`."""
import sys

from prreview import create_app

app = create_app()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"Offline PR Review -> http://127.0.0.1:{port}")
    app.run(port=port, debug=True)
