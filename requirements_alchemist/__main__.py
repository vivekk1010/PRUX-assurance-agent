from requirements_alchemist.app import create_app
from requirements_alchemist.config import Settings


def main() -> None:
    settings = Settings.load()
    create_app(settings).run(
        host=settings.host,
        port=settings.port,
        debug=settings.debug,
    )


if __name__ == "__main__":
    main()
