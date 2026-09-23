"""
Offline template validation — no AWS account or SAM CLI needed.

1. Runs the AWS SAM transform on template.yaml (what `sam deploy` does before
   handing the template to CloudFormation) and fails on any transform error.
2. Runs cfn-lint over every CloudFormation template in the repo.

Run:  python scripts/validate_templates.py      (or: make validate-offline)
"""

import os
import subprocess
import sys
from pathlib import Path

import yaml
from samtranslator.model.exceptions import InvalidDocumentException
from samtranslator.translator.managed_policy_translator import ManagedPolicyLoader
from samtranslator.translator.transform import transform

ROOT      = Path(__file__).resolve().parent.parent
TEMPLATES = ["template.yaml", "member-account-role.yaml", "oidc-bootstrap.yaml"]


class _CfnLoader(yaml.SafeLoader):
    """SafeLoader that understands CloudFormation short-form tags (!Ref, !Sub, …)."""


def _cfn_tag(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> dict[str, object]:
    name = "Ref" if tag_suffix == "Ref" else f"Fn::{tag_suffix}"
    if isinstance(node, yaml.ScalarNode):
        value: object = loader.construct_scalar(node)
        if tag_suffix == "GetAtt" and isinstance(value, str):
            value = value.split(".", 1)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)  # type: ignore[arg-type]
    return {name: value}


_CfnLoader.add_multi_constructor("!", _cfn_tag)


class _NoManagedPolicies(ManagedPolicyLoader):
    """The transform only needs AWS managed policy ARNs for policy templates we don't use."""

    def __init__(self) -> None:  # noqa: D107 — no IAM client needed offline
        pass

    def load(self) -> dict[str, str]:
        return {}


def sam_transform() -> bool:
    # The transform resolves pseudo-parameters (AWS::Region); any region works offline.
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    doc = yaml.load((ROOT / "template.yaml").read_text(encoding="utf-8"), Loader=_CfnLoader)
    # Mimic `sam package`: local CodeUri paths become S3 locations before the transform.
    for res in doc.get("Resources", {}).values():
        props = res.get("Properties", {})
        if res.get("Type") == "AWS::Serverless::Function" and not str(props.get("CodeUri", "")).startswith("s3://"):
            props["CodeUri"] = "s3://offline-validation/code.zip"
    try:
        out = transform(doc, {}, _NoManagedPolicies(), feature_toggle=None, passthrough_metadata=False)
    except InvalidDocumentException as exc:
        for cause in exc.causes:
            print(f"  SAM transform error: {cause.message}")
        return False
    types: dict[str, int] = {}
    for res in out.get("Resources", {}).values():
        types[res["Type"]] = types.get(res["Type"], 0) + 1
    print(f"  SAM transform OK -> {sum(types.values())} CloudFormation resources")
    for t, n in sorted(types.items()):
        print(f"    {n:>2} x {t}")
    return True


def cfn_lint() -> bool:
    exe = Path(sys.executable).with_name("cfn-lint.exe" if sys.platform == "win32" else "cfn-lint")
    cmd = [str(exe) if exe.exists() else "cfn-lint", *TEMPLATES]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    print(f"  cfn-lint {'OK' if result.returncode == 0 else 'FAILED'}" + (f"\n{output}" if output else ""))
    return result.returncode == 0


def main() -> int:
    print("SAM transform (template.yaml):")
    ok_sam = sam_transform()
    print("cfn-lint (all templates):")
    ok_lint = cfn_lint()
    return 0 if ok_sam and ok_lint else 1


if __name__ == "__main__":
    sys.exit(main())
