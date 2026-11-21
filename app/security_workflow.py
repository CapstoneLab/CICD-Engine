"""Validate mandatory checks before executing repository-controlled workflow steps."""
SECURITY_SCANS = frozenset({"lightweight_security_scan", "deep_security_scan"})


def validate_security_workflow(steps):
    positions = {}
    for name in SECURITY_SCANS:
        matches = [i for i, step in enumerate(steps) if step.kind == "builtin" and step.uses == name]
        if len(matches) != 1:
            raise ValueError(f"Workflow must run exactly one {name} step")
        positions[name] = matches[0]
    deep = positions["deep_security_scan"]
    if positions["lightweight_security_scan"] > deep:
        raise ValueError("Secret scanning must precede the deep security scan and gate")
    for i, step in enumerate(steps):
        if (step.uses == "deploy" or step.name.lower() == "deploy") and i <= deep:
            raise ValueError("Deployment must follow both security scans and the gate")
