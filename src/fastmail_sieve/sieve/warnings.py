def collect_warnings(rules, disabled, variable_warnings):
    warnings = [issue for rule in rules for issue in rule.issues]
    warnings += [
        ("disabled", f"UI rule {title} is commented out in Fastmail")
        for title in disabled
    ]
    warnings += [("variables", warning) for warning in variable_warnings]
    return warnings
