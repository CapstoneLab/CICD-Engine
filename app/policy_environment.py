"""Server-owned policy floor shared by API, webhooks and execution."""
import os


def effective_environment(requested=None):
    ranks = {"feature": 0, "development": 1, "staging": 2, "production": 3}
    aliases = {"prod":"production", "stage":"staging", "dev":"development", "develop":"development", "feat":"feature", "feature_branch":"feature"}
    floor = os.getenv("SECURITY_POLICY_MIN_ENVIRONMENT", "production").strip().lower()
    value = (requested or "development").strip().lower()
    value = aliases.get(value, value)
    if floor not in ranks or value not in ranks:
        raise ValueError("Invalid server security policy environment")
    return max((floor, value), key=ranks.get)
