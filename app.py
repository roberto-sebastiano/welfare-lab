#!/usr/bin/env python3
import aws_cdk as cdk
from welfare_lab.welfare_lab_stack import WelfareLabStack
from welfare_lab.github_oidc_stack import GithubOidcStack

app = cdk.App()


GithubOidcStack(app, "WelfareLab-GithubOidc",
    sub_prefix="repo:roberto-sebastiano@11598131/welfare-lab@1474520299",
)
# Nome dell'ambiente passato con -c stage=... (default: dev)
stage = app.node.try_get_context("stage") or "dev"

WelfareLabStack(app, f"WelfareLab-{stage}", stage=stage)

# Tag su tutte le risorse: servono per costi, pulizia e ricerca
cdk.Tags.of(app).add("project", "welfare-lab")
cdk.Tags.of(app).add("stage", stage)

app.synth()