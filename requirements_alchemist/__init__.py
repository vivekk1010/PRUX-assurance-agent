"""Requirements Alchemist: grounded product-intent to Jira-story generation."""


def create_app(*args, **kwargs):
    from requirements_alchemist.app import create_app as factory

    return factory(*args, **kwargs)


__all__ = ["create_app"]
