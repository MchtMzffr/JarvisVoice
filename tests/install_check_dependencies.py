"""Install model-free CI dependencies using the project's existing pins.

Run with Python 3.11. --validate-only reads local TOML files and prints the plan;
it never invokes pip or downloads anything. --platform allows inspection of the
other supported CI target only in validate-only mode. No package is installed
merely because it appears in the generated constraints file.
"""
import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import tomllib


CHECK_PACKAGES = {"fastapi", "uvicorn", "websockets", "httpx", "numpy", "tzdata", "tiktoken"}
DESKTOP_PACKAGES = {"pywebview", "pythonnet"}
HEAVY_PACKAGES = {
    "torch", "torchaudio", "torchvision", "faster-whisper", "ctranslate2",
    "onnxruntime", "av", "huggingface-hub", "ema-lightning", "normalizer-tr",
    "tokenizers", "transformers",
}
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)\s*==\s*([A-Za-z0-9][A-Za-z0-9.!+_-]*)(?:\s*;\s*(.+))?")


def canonical(name):
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) is None:
        raise ValueError("Invalid package name in project or lock file.")
    return re.sub(r"[-_.]+", "-", name).lower()


def environment(target, *, inspect_target=False):
    if target not in {"linux", "win32"}:
        raise ValueError("Only the project's Linux x64 and Windows x64 CI targets are supported.")
    return {
        "sys_platform": target,
        "platform_machine": {"linux": "x86_64", "win32": "AMD64"}[target] if inspect_target else platform.machine(),
        "platform_system": {"linux": "Linux", "win32": "Windows"}[target],
        "os_name": "nt" if target == "win32" else "posix",
        "implementation_name": sys.implementation.name,
        "platform_python_implementation": platform.python_implementation(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_full_version": platform.python_version(),
        "extra": "",
    }


def marker_matches(marker, values):
    """Evaluate only the marker grammar used by this lock; never eval code.

    Unsupported future marker operators fail explicitly instead of selecting a
    different dependency resolution. Pip evaluates package metadata separately.
    """
    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) is str:
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            parts = [evaluate(value) for value in node.values]
            if not all(type(part) is bool for part in parts):
                raise ValueError("Non-boolean dependency marker expression.")
            return all(parts) if isinstance(node.op, ast.And) else any(parts)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            operation = node.ops[0]
            if type(left) is not str or type(right) is not str:
                raise ValueError("Invalid dependency marker operands.")
            if isinstance(operation, ast.Eq):
                return left == right
            if isinstance(operation, ast.NotEq):
                return left != right
            if isinstance(operation, ast.In):
                return left in right
            if isinstance(operation, ast.NotIn):
                return left not in right
        raise ValueError("Unsupported lock marker; update this CI helper before installing.")

    if not marker:
        return True
    try:
        result = evaluate(ast.parse(marker, mode="eval"))
    except SyntaxError:
        raise ValueError("Invalid lock marker syntax.") from None
    if type(result) is not bool:
        raise ValueError("Dependency marker must evaluate to a boolean.")
    return result


def installation_plan(root, target, *, inspect_target=False):
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    with (root / "uv.lock").open("rb") as stream:
        lock = tomllib.load(stream)
    values = environment(target, inspect_target=inspect_target)
    supported = lock.get("supported-markers", [])
    if supported and not any(marker_matches(marker, values) for marker in supported):
        raise ValueError("This interpreter platform is outside uv.lock's supported targets.")
    # All committed resolutions currently use Python 3.11. Never install an
    # unverified Python resolution silently if the project changes this range.
    if lock.get("requires-python") != f"=={values['python_version']}.*":
        raise ValueError("Use the Python minor version specified by uv.lock for these checks.")

    selected = set(CHECK_PACKAGES)
    requirements = list(project["dependencies"])
    if target == "win32":
        selected.update(DESKTOP_PACKAGES)
        requirements.extend(project.get("optional-dependencies", {}).get("desktop", []))
    requested = {}
    for requirement in requirements:
        match = PIN.fullmatch(requirement.strip())
        if match is None:
            raise ValueError("CI requires exact project requirement pins; review pyproject.toml.")
        name, version, marker = match.groups()
        name = canonical(name)
        if name in selected and marker_matches(marker, values):
            if name in requested and requested[name] != version:
                raise ValueError("Conflicting selected project requirement pins.")
            requested[name] = version
    if set(requested) != selected:
        raise ValueError("A required model-free dependency is missing from pyproject.toml.")

    candidates = defaultdict(list)
    project_entries = []
    for package in lock["package"]:
        name = canonical(package["name"])
        if name == canonical(project["name"]):
            project_entries.append(package)
        if "registry" not in package.get("source", {}):
            continue
        markers = package.get("resolution-markers", [])
        if not markers or any(marker_matches(marker, values) for marker in markers):
            candidates[name].append(package)
    if len(project_entries) != 1 or project_entries[0]["version"] != project["version"]:
        raise ValueError("pyproject.toml and uv.lock project versions differ.")
    packages, pins = {}, {}
    for name, entries in candidates.items():
        versions = {entry["version"] for entry in entries}
        if len(versions) != 1 or len(entries) != 1:
            raise ValueError("Ambiguous lock resolution for this platform; refusing to choose a pin.")
        version = entries[0]["version"]
        if PIN.fullmatch(f"{name}=={version}") is None:
            raise ValueError("Invalid package version in uv.lock.")
        packages[name], pins[name] = entries[0], version
    if any(pins.get(name) != version for name, version in requested.items()):
        raise ValueError("Selected project pins do not match uv.lock.")

    # Check the locked dependency closure before pip is allowed to access the
    # network. Constraints alone do not request the other locked packages.
    pending, closure = list(requested), set()
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        if name in HEAVY_PACKAGES or name.startswith("nvidia-"):
            raise ValueError("The selected test dependency graph includes a model/audio package.")
        if name not in packages:
            raise ValueError("A selected transitive dependency is absent from uv.lock.")
        closure.add(name)
        for dependency in packages[name].get("dependencies", []):
            if marker_matches(dependency.get("marker"), values):
                child = canonical(dependency["name"])
                if "version" in dependency and pins.get(child) != dependency["version"]:
                    raise ValueError("A transitive dependency pin conflicts with the selected resolution.")
                pending.append(child)
    return {
        "platform": target,
        "requirements": [f"{name}=={version}" for name, version in sorted(requested.items())],
        "constraints": [f"{name}=={version}" for name, version in sorted(pins.items())],
        "dependency_closure": sorted(closure),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="Read pins and print the plan without invoking pip.")
    parser.add_argument("--platform", choices=("linux", "win32"), help="Inspect another CI target; requires --validate-only.")
    args = parser.parse_args(argv)
    if args.platform and not args.validate_only:
        parser.error("--platform is only permitted with --validate-only")
    root = Path(__file__).resolve().parents[1]
    try:
        plan = installation_plan(root, args.platform or sys.platform, inspect_target=bool(args.platform))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Dependency validation failed: {exc}\n")
    if args.validate_only:
        print(json.dumps(plan, indent=2))
        return 0
    print("Installing model-free check requirements: " + ", ".join(plan["requirements"]), flush=True)
    with tempfile.TemporaryDirectory(prefix="jarvis-check-deps-") as temporary:
        constraints = Path(temporary) / "constraints.txt"
        constraints.write_text("\n".join(plan["constraints"]) + "\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
             "--constraint", str(constraints), *plan["requirements"]],
            shell=False, check=False,
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
