import os

from stage_app.app import create_app

if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=int(os.getenv("STAGE_PORT", "5055")), debug=False)
