"""User input prompts."""

from .sound import play_interaction_sound


def prompt_yes_no(message: str, default_yes: bool = True) -> bool:
    """Prompt user with Y/n question. Returns True for yes, False for no.

    Args:
        message: The question to ask
        default_yes: Default answer if user presses Enter

    Returns:
        True for yes, False for no

    Accepts:
    - Enter (empty): default choice
    - y/yes: yes
    - n/no: no
    - Ctrl+C: exits immediately
    """
    play_interaction_sound()
    prompt = f"{message} [{'Y/n' if default_yes else 'y/N'}]: "
    response = input(prompt).strip().lower()

    if response in ['n', 'no']:
        return False
    elif response in ['y', 'yes']:
        return True
    else:
        # Empty or anything else = default
        return default_yes


def prompt_skip_or_retry(message: str = "Skip or Retry?") -> str:
    """Prompt user to skip or retry after a failure.

    Args:
        message: The question to ask

    Returns:
        'skip' or 'retry'

    Accepts:
    - s/skip: skip this module
    - r/retry/Enter: retry this module (default)
    - Ctrl+C: exits immediately
    """
    play_interaction_sound()
    prompt = f"{message} [s/R]: "
    response = input(prompt).strip().lower()

    if response in ['s', 'skip']:
        return 'skip'
    else:
        # Empty, 'r', 'retry', or anything else = retry (default)
        return 'retry'
