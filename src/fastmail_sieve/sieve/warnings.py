from rich.text import Text


def collect_warnings(rules, disabled, variable_warnings):
    warnings = [issue for rule in rules for issue in rule.issues]
    warnings += [
        ("disabled", f"UI rule {title} is commented out in Fastmail")
        for title in disabled
    ]
    warnings += [("variables", warning) for warning in variable_warnings]
    return warnings


def run(warnings, strict, console):
    if not warnings:
        console.print("No warnings.", markup=False)
        return 0
    for kind, text in warnings:
        console.print(Text.assemble((f"{kind}:", "bold yellow"), f" {text}"))
    noun = "warning" if len(warnings) == 1 else "warnings"
    console.print(f"{len(warnings)} {noun}", style="dim", markup=False)
    return 1 if strict else 0
